# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Read-only latency and MRR probe for fastembed 0.8.0 cross-encoders."""

from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fastembed  # noqa: E402
from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: E402

from config import SEARCH_HYBRID_CANDIDATES, SEARCH_RRF_K  # noqa: E402
from indexer import _vector_search, get_collection, reciprocal_rank_fusion  # noqa: E402
from lexical_index import LexicalIndex  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_PROBE_SET = EVAL_DIR / "baselines" / "lot6c-reranker" / "rerank_probe_set.json"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "baselines" / "lot6c-reranker"
WARM_RUNS = 5
CUTOFF = 5
RERANK_LATENCY_BUDGET_MS = 250.0
FULL_SEARCH_BUDGET_MS = 300.0

# Ordered by contract preference: multilingual/plausibly cross-lingual first,
# then compact English-only second-curtain candidates.
CANDIDATE_MODELS = (
    "jinaai/jina-reranker-v2-base-multilingual",
    "BAAI/bge-reranker-base",
    "Xenova/ms-marco-MiniLM-L-6-v2",
    "jinaai/jina-reranker-v1-tiny-en",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-set", type=Path, default=DEFAULT_PROBE_SET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--candidates",
        type=int,
        default=SEARCH_HYBRID_CANDIDATES,
        help="Number of fused candidates passed to one reranker batch",
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Model to probe (repeatable; defaults to all plausible candidates)",
    )
    return parser.parse_args()


def rss_mb() -> float:
    """Return approximate resident memory using only the standard library."""
    if sys.platform == "win32":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        )
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return float(counters.WorkingSetSize) / (1024 * 1024)
    import resource

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return float(rss) / (1024 if sys.platform != "darwin" else 1024 * 1024)


def metric_rank(hits: list[dict[str, Any]], expected_paths: set[str]) -> int | None:
    for rank, hit in enumerate(hits[:CUTOFF], start=1):
        if hit.get("metadata", {}).get("path") in expected_paths:
            return rank
    return None


def summarize_ranks(ranks: dict[str, int | None]) -> dict[str, Any]:
    reciprocal_ranks = [1.0 / rank if rank is not None else 0.0 for rank in ranks.values()]
    return {
        "mrr_at_5": statistics.mean(reciprocal_ranks),
        "hit_at_1": sum(rank == 1 for rank in ranks.values()) / len(ranks),
        "hits_at_5": sum(rank is not None for rank in ranks.values()),
        "query_count": len(ranks),
        "ranks": ranks,
    }


def fused_candidates(
    collection: Any,
    lexical: LexicalIndex,
    query: str,
    candidate_count: int,
) -> list[dict[str, Any]]:
    vector = _vector_search(collection, query, None, SEARCH_HYBRID_CANDIDATES)
    lexical_hits = lexical.search(query, limit=SEARCH_HYBRID_CANDIDATES)
    return reciprocal_rank_fusion(vector, lexical_hits, rrf_k=SEARCH_RRF_K)[
        :candidate_count
    ]


def rerank_hits(
    model: TextCrossEncoder,
    query: str,
    hits: list[dict[str, Any]],
    batch_size: int,
) -> tuple[list[dict[str, Any]], list[float]]:
    scores = [
        float(score)
        for score in model.rerank(
            query,
            [str(hit.get("text", "")) for hit in hits],
            batch_size=batch_size,
        )
    ]
    if len(scores) != len(hits):
        raise RuntimeError(f"reranker returned {len(scores)} scores for {len(hits)} hits")
    order = sorted(range(len(hits)), key=lambda index: (-scores[index], index))
    return [hits[index] for index in order], scores


def benchmark_latency(
    model: TextCrossEncoder,
    query: str,
    hits: list[dict[str, Any]],
    candidate_count: int,
) -> dict[str, Any]:
    if len(hits) != candidate_count:
        raise RuntimeError(
            f"latency probe requires {candidate_count} real candidates"
        )
    rerank_hits(model, query, hits, candidate_count)
    samples: list[float] = []
    for _ in range(WARM_RUNS):
        started = time.perf_counter()
        rerank_hits(model, query, hits, candidate_count)
        samples.append((time.perf_counter() - started) * 1000)
    median_ms = statistics.median(samples)
    return {
        "samples_ms": [round(sample, 3) for sample in samples],
        "median_ms": round(median_ms, 3),
        "within_rerank_budget": median_ms <= RERANK_LATENCY_BUDGET_MS,
    }


def probe_model(
    descriptor: dict[str, Any],
    queries: list[dict[str, Any]],
    candidates_by_query: dict[str, list[dict[str, Any]]],
    candidate_count: int,
) -> dict[str, Any]:
    name = str(descriptor["model"])
    memory_before = rss_mb()
    load_started = time.perf_counter()
    model = TextCrossEncoder(name, threads=None, cuda=False)
    load_ms = (time.perf_counter() - load_started) * 1000
    memory_after = rss_mb()

    latency = {
        "k5": benchmark_latency(
            model,
            str(queries[0]["query"]),
            candidates_by_query[str(queries[0]["id"])],
            candidate_count,
        ),
        "k10": benchmark_latency(
            model,
            str(queries[4]["query"]),
            candidates_by_query[str(queries[4]["id"])],
            candidate_count,
        ),
    }
    ranks: dict[str, int | None] = {}
    per_query: dict[str, dict[str, Any]] = {}
    for item in queries:
        query_id = str(item["id"])
        reranked, scores = rerank_hits(
            model,
            str(item["query"]),
            candidates_by_query[query_id],
            candidate_count,
        )
        rank = metric_rank(reranked, set(item["expected_paths"]))
        ranks[query_id] = rank
        per_query[query_id] = {
            "rank": rank,
            "score_min": min(scores),
            "score_max": max(scores),
        }

    quality = summarize_ranks(ranks)
    result = {
        "model": name,
        "description": descriptor.get("description"),
        "license": descriptor.get("license"),
        "declared_size_gb": descriptor.get("size_in_GB"),
        "load_ms_including_first_download": round(load_ms, 3),
        "rss_before_mb": round(memory_before, 3),
        "rss_after_load_mb": round(memory_after, 3),
        "rss_delta_mb_approx": round(memory_after - memory_before, 3),
        "latency": latency,
        "quality": quality,
        "per_query": per_query,
    }
    del model
    gc.collect()
    return result


def main() -> None:
    args = parse_args()
    raw_probe_set = args.probe_set.read_bytes()
    probe_set = json.loads(raw_probe_set.decode("utf-8"))
    queries: list[dict[str, Any]] = probe_set["queries"]
    max_candidates = int(probe_set.get("candidates", 0))
    if len(queries) != 13 or max_candidates != SEARCH_HYBRID_CANDIDATES:
        raise SystemExit("frozen probe set does not match the lot 6c contract")
    if not 1 <= args.candidates <= max_candidates:
        raise SystemExit(f"--candidates must be between 1 and {max_candidates}")

    supported = TextCrossEncoder.list_supported_models()
    descriptors = {str(item["model"]): item for item in supported}
    selected_models = tuple(args.models or CANDIDATE_MODELS)
    missing = [name for name in selected_models if name not in descriptors]
    if missing:
        raise SystemExit(f"contract candidates unavailable in fastembed: {missing}")

    collection = get_collection()
    lexical = LexicalIndex()
    if not lexical.is_compatible():
        raise SystemExit("lexical index is absent or incompatible; run cortex sync first")

    candidates_by_query: dict[str, list[dict[str, Any]]] = {}
    baseline_ranks: dict[str, int | None] = {}
    for item in queries:
        query_id = str(item["id"])
        hits = fused_candidates(
            collection,
            lexical,
            str(item["query"]),
            args.candidates,
        )
        if len(hits) != args.candidates:
            raise SystemExit(
                f"{query_id} returned {len(hits)} candidates, "
                f"expected {args.candidates}"
            )
        candidates_by_query[query_id] = hits
        baseline_ranks[query_id] = metric_rank(hits, set(item["expected_paths"]))

    results: list[dict[str, Any]] = []
    for name in selected_models:
        print(f"[probe] {name}", flush=True)
        try:
            result = probe_model(
                descriptors[name],
                queries,
                candidates_by_query,
                args.candidates,
            )
            result["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 -- one candidate must not erase the probe.
            result = {
                "model": name,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    measured_names = set(selected_models)
    excluded = [
        {
            "model": item["model"],
            "reason": "larger same-family alternative excluded before measurement",
        }
        for item in supported
        if item["model"] not in measured_names
    ]
    measured_at = datetime.now(timezone.utc)
    report = {
        "schema_version": 1,
        "measured_at_utc": measured_at.isoformat(),
        "read_only": True,
        "fastembed_version": fastembed.__version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "probe_set": str(args.probe_set),
        "probe_set_sha256": hashlib.sha256(raw_probe_set).hexdigest(),
        "budgets_ms": {
            "rerank_batch": RERANK_LATENCY_BUDGET_MS,
            "full_search": FULL_SEARCH_BUDGET_MS,
        },
        "candidate_count": args.candidates,
        "supported_models": supported,
        "selected_candidates": list(selected_models),
        "excluded_supported_models": excluded,
        "rrf_baseline": summarize_ranks(baseline_ranks),
        "candidates": results,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = measured_at.strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir / f"probe-{timestamp}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Written to {output}")


if __name__ == "__main__":
    main()
