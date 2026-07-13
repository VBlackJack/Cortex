# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Build and evaluate the isolated lot 6d multilingual-e5-large index."""

from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import importlib.metadata
import json
import math
import platform
import statistics
import sys
import time
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chromadb  # noqa: E402
import fastembed  # noqa: E402
from fastembed import TextEmbedding  # noqa: E402
from fastembed.common.model_description import ModelSource, PoolingType  # noqa: E402
from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: E402

from chroma_client import create_persistent_client, iter_collection_pages  # noqa: E402
from config import (  # noqa: E402
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    EMBEDDING_POOLING,
    RERANKER_MODEL,
    SEARCH_HYBRID_CANDIDATES,
    SEARCH_RERANK_CANDIDATES,
    SEARCH_RRF_K,
)
from indexer import reciprocal_rank_fusion  # noqa: E402
from lexical_index import LexicalIndex  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
MODEL_NAME = "intfloat/multilingual-e5-large"
RUNTIME_MODEL_ALIAS = "cortex-probe/multilingual-e5-large"
MODEL_ARCHIVE_URL = (
    "https://storage.googleapis.com/qdrant-fastembed/fast-multilingual-e5-large.tar.gz"
)
MODEL_DIMENSIONS = 1024
MODEL_POOLING = "mean"
MODEL_NORMALIZATION = "l2"
PREFIX_POLICY = "explicit-query-passage-v1"
ONNXRUNTIME_VERSION = importlib.metadata.version("onnxruntime")
PROBE_COLLECTION_NAME = "cortex_probe"
PROBE_SET = EVAL_DIR / "baselines" / "lot6c-reranker" / "rerank_probe_set.json"
PROBE_SET_SHA256 = "a4a9a95806d2a338a9d58bbc9095f10ca40e33fe78fb9453df7ca4e565892b3f"
OUTPUT_DIR = EVAL_DIR / "baselines" / "lot6d-embedding"
WARM_RUNS = 5
CUTOFF = 5
QUERY_EMBED_BUDGET_MS = 200.0
FULL_SEARCH_BUDGET_MS = 400.0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-set", type=Path, default=PROBE_SET)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--probe-path",
        type=Path,
        default=Path(CHROMA_PATH).parent / "chroma_probe" / "multilingual-e5-large",
    )
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--page-size", type=int, default=512)
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Stop after the resumable parallel build (no quality report)",
    )
    return parser.parse_args(argv)


def _sha256_strings(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(values):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _vector(values: Any) -> list[float]:
    return [float(value) for value in values]


def _norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    denominator = _norm(left) * _norm(right)
    if denominator == 0:
        raise ValueError("cannot compare a zero embedding")
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def rss_mb() -> float:
    """Return current resident memory on Windows and peak RSS elsewhere."""
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
        if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return float(counters.WorkingSetSize) / (1024 * 1024)
    import resource

    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / (
        1024 * 1024 if sys.platform == "darwin" else 1024
    )


class E5Embedding:
    """Explicit E5 asymmetric adapter, isolated from the product adapter."""

    def __init__(self) -> None:
        # The built-in descriptor tries Hugging Face before its official archive.
        # On Windows without symlink privileges, huggingface_hub can leave a broken
        # snapshot even though fastembed's fallback archive is valid. Registering the
        # same official weights as an URL-only alias makes restarts deterministic.
        if RUNTIME_MODEL_ALIAS not in {
            str(item["model"]) for item in TextEmbedding.list_supported_models()
        }:
            TextEmbedding.add_custom_model(
                model=RUNTIME_MODEL_ALIAS,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(url=MODEL_ARCHIVE_URL, _deprecated_tar_struct=True),
                dim=MODEL_DIMENSIONS,
                model_file="model.onnx",
                description=f"URL-only runtime alias for {MODEL_NAME}",
                license="mit",
                size_in_gb=2.24,
                additional_files=["model.onnx_data"],
            )
        self.model = TextEmbedding(model_name=RUNTIME_MODEL_ALIAS, cuda=False)

    def documents(self, texts: Iterable[str], *, batch_size: int) -> list[list[float]]:
        prefixed = (f"passage: {text}" for text in texts)
        return [_vector(item) for item in self.model.embed(prefixed, batch_size=batch_size)]

    def query(self, text: str) -> list[float]:
        return _vector(next(iter(self.model.embed([f"query: {text}"]))))


def inspect_fastembed_prefixes(model: TextEmbedding) -> dict[str, Any]:
    """Empirically attest whether fastembed 0.8.0 adds E5 prefixes itself."""
    witness = "durcissement Windows avec AppLocker"
    raw = _vector(next(iter(model.embed([witness]))))
    query_api = _vector(next(iter(model.query_embed(witness))))
    passage_api = _vector(next(iter(model.passage_embed([witness]))))
    explicit_query = _vector(next(iter(model.embed([f"query: {witness}"]))))
    explicit_passage = _vector(next(iter(model.embed([f"passage: {witness}"]))))
    api_cosine = _cosine(query_api, passage_api)
    fastembed_distinguishes_roles = api_cosine < 1.0 - 1e-6
    if fastembed_distinguishes_roles:
        raise RuntimeError(
            "fastembed now distinguishes E5 query/passage roles; the frozen explicit "
            "prefix policy must be reviewed before this probe can continue"
        )
    return {
        "witness": witness,
        "query_api_vs_passage_api_cosine": api_cosine,
        "query_api_vs_raw_cosine": _cosine(query_api, raw),
        "passage_api_vs_raw_cosine": _cosine(passage_api, raw),
        "explicit_query_vs_passage_cosine": _cosine(explicit_query, explicit_passage),
        "fastembed_distinguishes_roles": False,
        "selected_policy": PREFIX_POLICY,
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
    }


def embedding_fingerprint() -> dict[str, Any]:
    return {
        "embedding_model": MODEL_NAME,
        "fastembed_version": fastembed.__version__,
        "onnxruntime_version": ONNXRUNTIME_VERSION,
        "dimensions": MODEL_DIMENSIONS,
        "pooling": MODEL_POOLING,
        "normalization": MODEL_NORMALIZATION,
        "prefix_policy": PREFIX_POLICY,
    }


def _checkpoint_path(probe_path: Path) -> Path:
    return probe_path / "lot6d-checkpoint.json"


def _load_checkpoint(probe_path: Path) -> dict[str, Any]:
    path = _checkpoint_path(probe_path)
    if not path.is_file():
        return {
            "schema_version": 1,
            "fingerprint": embedding_fingerprint(),
            "sections": {},
            "cumulative_embedding_seconds": 0.0,
        }
    checkpoint = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if checkpoint.get("fingerprint") != embedding_fingerprint():
        raise RuntimeError(f"probe checkpoint fingerprint mismatch: {path}")
    return checkpoint


def _save_checkpoint(probe_path: Path, checkpoint: dict[str, Any]) -> None:
    path = _checkpoint_path(probe_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(checkpoint, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _source_sections(source: Any, page_size: int) -> list[str]:
    sections: set[str] = set()
    for page in iter_collection_pages(source, page_size=page_size, include=["metadatas"]):
        for metadata in page.get("metadatas") or []:
            if isinstance(metadata, dict) and isinstance(metadata.get("section"), str):
                sections.add(metadata["section"])
    if not sections:
        raise RuntimeError("production collection contains no section metadata")
    return sorted(sections)


def _section_records(source: Any, section: str, page_size: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in iter_collection_pages(
        source,
        page_size=page_size,
        where={"section": section},
        include=["documents", "metadatas"],
    ):
        ids = page.get("ids") or []
        documents = page.get("documents") or []
        metadatas = page.get("metadatas") or []
        for chunk_id, document, metadata in zip(ids, documents, metadatas, strict=True):
            if not isinstance(document, str) or not isinstance(metadata, dict):
                raise RuntimeError(f"invalid production record in section {section}")
            records.append({"id": str(chunk_id), "text": document, "metadata": metadata})
    return records


def _probe_section_ids(collection: Any, section: str) -> list[str]:
    result = collection.get(where={"section": section}, include=["metadatas"])
    return [str(chunk_id) for chunk_id in result.get("ids") or []]


def _probe_collection(client: Any) -> Any:
    fingerprint = embedding_fingerprint()
    try:
        collection = client.get_collection(PROBE_COLLECTION_NAME)
    except Exception as exc:
        if not isinstance(exc, chromadb.errors.NotFoundError):
            raise
        return client.create_collection(
            PROBE_COLLECTION_NAME,
            metadata={**fingerprint, "hnsw:space": "cosine"},
        )
    stored = dict(collection.metadata or {})
    mismatches = {
        key: (stored.get(key), expected)
        for key, expected in fingerprint.items()
        if stored.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(f"parallel collection fingerprint mismatch: {mismatches}")
    return collection


def build_parallel_index(
    source: Any,
    probe_path: Path,
    embedder: E5Embedding,
    *,
    batch_size: int,
    page_size: int,
) -> tuple[Any, dict[str, Any]]:
    """Copy stable production chunks into a resumable, isolated vector index."""
    if batch_size <= 0 or page_size <= 0:
        raise ValueError("batch and page sizes must be positive")
    if probe_path.resolve() == Path(CHROMA_PATH).resolve():
        raise RuntimeError("refusing to use the production Chroma path as a probe")
    probe_path.mkdir(parents=True, exist_ok=True)
    checkpoint = _load_checkpoint(probe_path)
    client = create_persistent_client(probe_path)
    collection = _probe_collection(client)
    invocation_started = time.perf_counter()
    rebuilt: list[str] = []
    resumed: list[str] = []

    for section in _source_sections(source, page_size):
        records = _section_records(source, section, page_size)
        source_ids = [str(record["id"]) for record in records]
        source_sha = _sha256_strings(source_ids)
        saved = checkpoint["sections"].get(section)
        # A missing checkpoint can still leave a partially written section after
        # interruption. Inspect it unconditionally, then rebuild that section.
        probe_ids = _probe_section_ids(collection, section)
        if (
            isinstance(saved, dict)
            and saved.get("count") == len(source_ids)
            and saved.get("ids_sha256") == source_sha
            and _sha256_strings(probe_ids) == source_sha
        ):
            resumed.append(section)
            print(f"[build] {section}: checkpoint valid ({len(records)} chunks)", flush=True)
            continue

        if probe_ids or saved:
            collection.delete(where={"section": section})
        section_started = time.perf_counter()
        for offset in range(0, len(records), batch_size):
            batch = records[offset : offset + batch_size]
            embeddings = embedder.documents(
                (str(record["text"]) for record in batch),
                batch_size=batch_size,
            )
            collection.add(
                ids=[str(record["id"]) for record in batch],
                documents=[str(record["text"]) for record in batch],
                metadatas=[record["metadata"] for record in batch],
                embeddings=embeddings,
            )
            print(
                f"[build] {section}: {min(offset + len(batch), len(records))}/"
                f"{len(records)}",
                end="\r",
                flush=True,
            )
        elapsed = time.perf_counter() - section_started
        print(f"[build] {section}: complete in {elapsed:.1f}s" + " " * 20, flush=True)
        checkpoint["sections"][section] = {
            "count": len(source_ids),
            "ids_sha256": source_sha,
            "embedding_seconds": elapsed,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        checkpoint["cumulative_embedding_seconds"] = sum(
            float(item["embedding_seconds"])
            for item in checkpoint["sections"].values()
        )
        _save_checkpoint(probe_path, checkpoint)
        rebuilt.append(section)

    source_count = int(source.count())
    probe_count = int(collection.count())
    if source_count != probe_count:
        raise RuntimeError(
            f"parallel index count mismatch: production={source_count}, probe={probe_count}"
        )
    report = {
        "probe_path": str(probe_path.resolve()),
        "production_path": str(Path(CHROMA_PATH).resolve()),
        "production_writes": 0,
        "source_chunks": source_count,
        "probe_chunks": probe_count,
        "sections_total": len(checkpoint["sections"]),
        "sections_rebuilt": rebuilt,
        "sections_resumed": resumed,
        "invocation_seconds": time.perf_counter() - invocation_started,
        "cumulative_embedding_seconds": checkpoint["cumulative_embedding_seconds"],
        "checkpoint": str(_checkpoint_path(probe_path).resolve()),
    }
    return collection, report


def _query_vector(collection: Any, embedding: list[float], count: int) -> list[dict[str, Any]]:
    result = collection.query(
        query_embeddings=[embedding],
        n_results=count,
        include=["documents", "metadatas", "distances"],
    )
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    return [
        {"id": chunk_id, "text": text, "metadata": metadata or {}, "distance": distance}
        for chunk_id, text, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        )
    ]


def _rank(hits: list[dict[str, Any]], expected_paths: set[str]) -> int | None:
    for rank, hit in enumerate(hits[:CUTOFF], start=1):
        if hit.get("metadata", {}).get("path") in expected_paths:
            return rank
    return None


def _summarize(ranks: dict[str, int | None]) -> dict[str, Any]:
    return {
        "mrr_at_5": statistics.mean(
            1.0 / rank if rank is not None else 0.0 for rank in ranks.values()
        ),
        "hit_at_1": sum(rank == 1 for rank in ranks.values()) / len(ranks),
        "hits_at_5": sum(rank is not None for rank in ranks.values()),
        "query_count": len(ranks),
        "ranks": ranks,
    }


def _rerank(
    model: TextCrossEncoder, query: str, hits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates = hits[:SEARCH_RERANK_CANDIDATES]
    scores = [
        float(score)
        for score in model.rerank(
            query,
            [str(hit.get("text", "")) for hit in candidates],
            batch_size=SEARCH_RERANK_CANDIDATES,
        )
    ]
    if len(scores) != len(candidates):
        raise RuntimeError("reranker returned an incomplete score batch")
    order = sorted(range(len(candidates)), key=lambda index: (-scores[index], index))
    return [dict(candidates[index], rerank_score=scores[index]) for index in order]


def _mini_vector_quality(source: Any, queries: list[dict[str, Any]]) -> dict[str, Any]:
    model = TextEmbedding(model_name=EMBEDDING_MODEL, cuda=False)
    ranks: dict[str, int | None] = {}
    for item in queries:
        query = str(item["query"])
        embedding = _vector(next(iter(model.embed([query]))))
        hits = _query_vector(source, embedding, SEARCH_HYBRID_CANDIDATES)
        ranks[str(item["id"])] = _rank(hits, set(item["expected_paths"]))
    result = _summarize(ranks)
    result["fingerprint"] = {
        "embedding_model": EMBEDDING_MODEL,
        "pooling": EMBEDDING_POOLING,
        "prefix_policy": "none",
    }
    del model
    gc.collect()
    return result


def evaluate_quality(
    source: Any,
    probe: Any,
    embedder: E5Embedding,
    lexical: LexicalIndex,
    reranker: TextCrossEncoder,
    queries: list[dict[str, Any]],
) -> dict[str, Any]:
    vector_ranks: dict[str, int | None] = {}
    pipeline_ranks: dict[str, int | None] = {}
    for item in queries:
        query_id = str(item["id"])
        query = str(item["query"])
        vector = _query_vector(
            probe, embedder.query(query), SEARCH_HYBRID_CANDIDATES
        )
        vector_ranks[query_id] = _rank(vector, set(item["expected_paths"]))
        lexical_hits = lexical.search(query, limit=SEARCH_HYBRID_CANDIDATES)
        fused = reciprocal_rank_fusion(vector, lexical_hits, rrf_k=SEARCH_RRF_K)
        reranked = _rerank(reranker, query, fused)
        pipeline_ranks[query_id] = _rank(reranked, set(item["expected_paths"]))
    return {
        "minilm_vector_only": _mini_vector_quality(source, queries),
        "e5_vector_only": _summarize(vector_ranks),
        "e5_full_pipeline": _summarize(pipeline_ranks),
        "frozen_lot6c_full_pipeline_baseline": {
            "mrr_at_5": 0.7307692307692307,
            "hit_at_1": 0.6153846153846154,
            "hits_at_5": 13,
        },
    }


def _warm_samples(operation: Any) -> list[float]:
    operation()
    samples: list[float] = []
    for _ in range(WARM_RUNS):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def _latency_summary(samples: list[float], budget: float | None = None) -> dict[str, Any]:
    median = statistics.median(samples)
    result: dict[str, Any] = {
        "samples_ms": [round(sample, 3) for sample in samples],
        "median_ms": round(median, 3),
    }
    if budget is not None:
        result["budget_ms"] = budget
        result["within_budget"] = median <= budget
    return result


def evaluate_latency(
    probe: Any,
    embedder: E5Embedding,
    lexical: LexicalIndex,
    reranker: TextCrossEncoder,
    query: str,
) -> dict[str, Any]:
    query_embedding = embedder.query(query)

    def vector_only() -> None:
        _query_vector(probe, query_embedding, SEARCH_HYBRID_CANDIDATES)

    def complete() -> None:
        vector = _query_vector(
            probe, embedder.query(query), SEARCH_HYBRID_CANDIDATES
        )
        lexical_hits = lexical.search(query, limit=SEARCH_HYBRID_CANDIDATES)
        fused = reciprocal_rank_fusion(vector, lexical_hits, rrf_k=SEARCH_RRF_K)
        _rerank(reranker, query, fused)[:10]

    return {
        "warm_runs": WARM_RUNS,
        "query": query,
        "query_embedding": _latency_summary(
            _warm_samples(lambda: embedder.query(query)), QUERY_EMBED_BUDGET_MS
        ),
        "vector_index_only_excluding_embedding": _latency_summary(
            _warm_samples(vector_only)
        ),
        "complete_search_k10": _latency_summary(
            _warm_samples(complete), FULL_SEARCH_BUDGET_MS
        ),
    }


def _load_probe_set(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PROBE_SET_SHA256:
        raise RuntimeError(
            f"frozen lot 6c probe SHA mismatch: expected {PROBE_SET_SHA256}, got {digest}"
        )
    payload = json.loads(raw.decode("utf-8"))
    queries: list[dict[str, Any]] = payload["queries"]
    if len(queries) != 13 or payload.get("candidates") != SEARCH_HYBRID_CANDIDATES:
        raise RuntimeError("frozen lot 6c probe structure mismatch")
    return raw, queries


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    probe_started = time.perf_counter()
    raw_probe_set, queries = _load_probe_set(args.probe_set)
    production_client = create_persistent_client(CHROMA_PATH)
    source = production_client.get_collection(COLLECTION_NAME)
    memory_before = rss_mb()
    load_started = time.perf_counter()
    embedder = E5Embedding()
    model_load_seconds = time.perf_counter() - load_started
    memory_after_e5 = rss_mb()
    prefix_attestation = inspect_fastembed_prefixes(embedder.model)
    probe, build = build_parallel_index(
        source,
        args.probe_path,
        embedder,
        batch_size=args.batch_size,
        page_size=args.page_size,
    )
    build["end_to_end_invocation_seconds_including_model_load"] = (
        time.perf_counter() - probe_started
    )
    if args.build_only:
        print(json.dumps(build, indent=2, ensure_ascii=False))
        return 0

    lexical = LexicalIndex(Path(CHROMA_PATH).parent / "lexical.db")
    if not lexical.is_compatible() or lexical.count() != source.count():
        raise RuntimeError("production lexical index is absent, incompatible, or incomplete")
    reranker = TextCrossEncoder(RERANKER_MODEL, threads=None, cuda=False)
    quality = evaluate_quality(source, probe, embedder, lexical, reranker, queries)
    latency = evaluate_latency(
        probe,
        embedder,
        lexical,
        reranker,
        str(queries[4]["query"]),
    )
    measured_at = datetime.now(timezone.utc)
    pipeline = quality["e5_full_pipeline"]
    gate = {
        "strict_mrr_improvement": pipeline["mrr_at_5"] > 0.7307692307692307,
        "hit_at_1_non_regression": pipeline["hit_at_1"] >= 0.6153846153846154,
        "all_queries_top_5": pipeline["hits_at_5"] == 13,
        "query_embedding_budget": latency["query_embedding"]["within_budget"],
        "complete_search_budget": latency["complete_search_k10"]["within_budget"],
    }
    gate["pass"] = all(gate.values())
    report = {
        "schema_version": 1,
        "measured_at_utc": measured_at.isoformat(),
        "stage": "lot6d-stage1-commit-a",
        "model_fingerprint": embedding_fingerprint(),
        "prefix_attestation": prefix_attestation,
        "probe_set": str(args.probe_set.resolve()),
        "probe_set_sha256": hashlib.sha256(raw_probe_set).hexdigest(),
        "isolation": {
            "production_chroma": str(Path(CHROMA_PATH).resolve()),
            "parallel_chroma": str(args.probe_path.resolve()),
            "chunk_ids_embedding_independent": True,
            "production_writes": 0,
            "lexical_source": "production lexical.db (read-only)",
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "fastembed_version": fastembed.__version__,
            "onnxruntime_version": ONNXRUNTIME_VERSION,
        },
        "build": build,
        "memory": {
            "rss_before_model_mb": round(memory_before, 3),
            "rss_after_e5_load_mb": round(memory_after_e5, 3),
            "rss_e5_delta_mb_approx": round(memory_after_e5 - memory_before, 3),
            "rss_after_full_probe_mb": round(rss_mb(), 3),
            "e5_load_seconds_including_download": round(model_load_seconds, 3),
        },
        "latency": latency,
        "quality": quality,
        "gate_inputs": gate,
        "decision": "pending avenant 1; this probe does not promote an index",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"probe-{measured_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(gate, indent=2, ensure_ascii=False))
    print(f"Written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
