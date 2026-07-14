# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Read-only probe for lot 6e: per-path cap on fused candidates before rerank.

The embedding, index, lexical database and reranker are unchanged. This probe
only reorders the fused RRF candidates so that at most `cap` chunks per source
path enter the reranker window, then replays the production reranker. The
production index is never written. cap=inf reproduces the current behavior.
"""

from __future__ import annotations

import argparse
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
from probe_reranker import metric_rank, rss_mb, summarize_ranks  # noqa: E402

from config import (  # noqa: E402
    SEARCH_HYBRID_CANDIDATES,
    SEARCH_RERANK_CANDIDATES,
    SEARCH_RRF_K,
)
from indexer import _vector_search, get_collection, reciprocal_rank_fusion  # noqa: E402
from lexical_index import LexicalIndex  # noqa: E402
from reranker import rerank_fused_hits, warmup_reranker  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_PROBE_SET = EVAL_DIR / "baselines" / "lot6e-fusion" / "rerank_probe_set_v2.json"
DEFAULT_OUTPUT_DIR = EVAL_DIR / "baselines" / "lot6e-fusion"
EXPECTED_QUERY_COUNT = 21
# None means "no cap": identity ordering that reproduces production behavior.
DEFAULT_CAPS: tuple[int | None, ...] = (1, 2, 3, None)
CAP_MICROBENCH_RUNS = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-set", type=Path, default=DEFAULT_PROBE_SET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--window",
        type=int,
        default=SEARCH_RERANK_CANDIDATES,
        help="Reranker window size (defaults to the production value)",
    )
    return parser.parse_args()


def _cap_label(cap: int | None) -> str:
    return "inf" if cap is None else str(cap)


def cap_candidates_per_path(
    fused: list[dict[str, Any]], cap: int | None, window: int
) -> list[dict[str, Any]]:
    """Stable admitted/overflow partition capping chunks per path in the window.

    Walks the RRF-ordered fused list and admits a hit while its path count is
    below `cap` and the admitted list is shorter than `window`; other hits are
    kept in a stable overflow tail. No hit is dropped: the returned set equals
    the input set. cap=None returns the input unchanged (identity).
    """
    if cap is None:
        return list(fused)
    admitted: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for hit in fused:
        path = str(hit.get("metadata", {}).get("path", ""))
        if len(admitted) < window and counts.get(path, 0) < cap:
            admitted.append(hit)
            counts[path] = counts.get(path, 0) + 1
        else:
            overflow.append(hit)
    return admitted + overflow


def full_fused(
    collection: Any, lexical: LexicalIndex, query: str
) -> list[dict[str, Any]]:
    """Return the complete RRF fusion (not truncated) for one query."""
    vector = _vector_search(collection, query, None, SEARCH_HYBRID_CANDIDATES)
    lexical_hits = lexical.search(query, limit=SEARCH_HYBRID_CANDIDATES)
    return reciprocal_rank_fusion(vector, lexical_hits, rrf_k=SEARCH_RRF_K)


def _path_multiplicity(fused: list[dict[str, Any]], window: int) -> int:
    """Max number of chunks sharing one path within the top `window` of fused."""
    counts: dict[str, int] = {}
    for hit in fused[:window]:
        path = str(hit.get("metadata", {}).get("path", ""))
        counts[path] = counts.get(path, 0) + 1
    return max(counts.values()) if counts else 0


def _diff_vs_baseline(
    ranks: dict[str, int | None], baseline: dict[str, int | None]
) -> dict[str, list[str]]:
    entered = [
        query_id
        for query_id, rank in ranks.items()
        if rank is not None and baseline.get(query_id) is None
    ]
    left = [
        query_id
        for query_id, rank in ranks.items()
        if rank is None and baseline.get(query_id) is not None
    ]
    return {"entered_top5": sorted(entered), "left_top5": sorted(left)}


def _microbench_cap(
    fused_by_query: dict[str, list[dict[str, Any]]], window: int
) -> dict[str, Any]:
    lists = list(fused_by_query.values())
    samples: list[float] = []
    for _ in range(CAP_MICROBENCH_RUNS):
        started = time.perf_counter()
        for fused in lists:
            cap_candidates_per_path(fused, 2, window)
        samples.append((time.perf_counter() - started) * 1000)
    return {
        "runs": CAP_MICROBENCH_RUNS,
        "queries_per_run": len(lists),
        "median_ms_all_queries": round(statistics.median(samples), 4),
    }


def evaluate_cap(
    cap: int | None,
    queries: list[dict[str, Any]],
    fused_by_query: dict[str, list[dict[str, Any]]],
    window: int,
) -> dict[str, Any]:
    reranked_ranks: dict[str, int | None] = {}
    rrf_ranks: dict[str, int | None] = {}
    per_query: dict[str, dict[str, Any]] = {}
    for item in queries:
        query_id = str(item["id"])
        expected = set(item["expected_paths"])
        ordered = cap_candidates_per_path(fused_by_query[query_id], cap, window)
        reranked, failure = rerank_fused_hits(str(item["query"]), ordered)
        reranked_ranks[query_id] = metric_rank(reranked, expected)
        rrf_ranks[query_id] = metric_rank(ordered, expected)
        per_query[query_id] = {
            "reranked_rank": reranked_ranks[query_id],
            "rrf_rank": rrf_ranks[query_id],
            "rerank_failure": failure,
        }
    return {
        "cap": _cap_label(cap),
        "reranked": summarize_ranks(reranked_ranks),
        "rrf_only": summarize_ranks(rrf_ranks),
        "per_query": per_query,
        "_reranked_ranks": reranked_ranks,
    }


def main() -> None:
    args = parse_args()
    raw_probe_set = args.probe_set.read_bytes()
    probe_set = json.loads(raw_probe_set.decode("utf-8"))
    queries: list[dict[str, Any]] = probe_set["queries"]
    if len(queries) != EXPECTED_QUERY_COUNT:
        raise SystemExit(
            f"frozen probe set v2 must hold {EXPECTED_QUERY_COUNT} queries, "
            f"found {len(queries)}"
        )
    if int(probe_set.get("candidates", 0)) != SEARCH_HYBRID_CANDIDATES:
        raise SystemExit("frozen probe set candidate budget does not match config")
    if args.window < 1:
        raise SystemExit("--window must be >= 1")

    load_failure = warmup_reranker()
    if load_failure is not None:
        raise SystemExit(f"production reranker is required for this probe: {load_failure}")

    collection = get_collection()
    lexical = LexicalIndex()
    if not lexical.is_compatible():
        raise SystemExit("lexical index is absent or incompatible; run cortex sync first")

    rss_before = rss_mb()
    fused_by_query: dict[str, list[dict[str, Any]]] = {}
    fusion_stats: dict[str, dict[str, int]] = {}
    for item in queries:
        query_id = str(item["id"])
        fused = full_fused(collection, lexical, str(item["query"]))
        fused_by_query[query_id] = fused
        fusion_stats[query_id] = {
            "fused_size": len(fused),
            "max_path_multiplicity_in_window": _path_multiplicity(fused, args.window),
        }

    cap_results = [
        evaluate_cap(cap, queries, fused_by_query, args.window) for cap in DEFAULT_CAPS
    ]
    baseline_ranks = next(
        result["_reranked_ranks"]
        for result in cap_results
        if result["cap"] == "inf"
    )
    for result in cap_results:
        result["vs_baseline_inf"] = _diff_vs_baseline(
            result.pop("_reranked_ranks"), baseline_ranks
        )

    measured_at = datetime.now(timezone.utc)
    report = {
        "schema_version": 1,
        "lot": "6e-fusion-diversity",
        "measured_at_utc": measured_at.isoformat(),
        "read_only": True,
        "fastembed_version": fastembed.__version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "probe_set": str(args.probe_set),
        "probe_set_sha256": hashlib.sha256(raw_probe_set).hexdigest(),
        "window": args.window,
        "rrf_k": SEARCH_RRF_K,
        "hybrid_candidates": SEARCH_HYBRID_CANDIDATES,
        "caps_probed": [_cap_label(cap) for cap in DEFAULT_CAPS],
        "baseline_cap": "inf",
        "rss_before_mb": round(rss_before, 3),
        "rss_after_mb": round(rss_mb(), 3),
        "cap_apply_microbench": _microbench_cap(fused_by_query, args.window),
        "fusion_stats": fusion_stats,
        "results": cap_results,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = measured_at.strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir / f"probe-{timestamp}.json"
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for result in cap_results:
        summary = result["reranked"]
        print(
            f"[cap={result['cap']}] "
            f"MRR@5={summary['mrr_at_5']:.3f} "
            f"hit@1={summary['hit_at_1']:.3f} "
            f"hits@5={summary['hits_at_5']}/{summary['query_count']} "
            f"entered={result['vs_baseline_inf']['entered_top5']} "
            f"left={result['vs_baseline_inf']['left_top5']}",
            flush=True,
        )
    print(f"Written to {output}")


if __name__ == "__main__":
    main()
