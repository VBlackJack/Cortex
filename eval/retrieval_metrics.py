# Copyright 2026 Julien Bombled
# Licensed under the Apache License, Version 2.0.
"""Document-level relevance metrics; repeated chunks never inflate recall."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def metrics(paths: Sequence[str], expected: Sequence[str], top_k: int) -> dict[str, float]:
    """Compute recall, reciprocal rank and binary nDCG at the document cutoff."""
    relevant = set(expected)
    if not relevant or top_k < 1:
        raise ValueError("Expected documents and a positive cutoff are required")
    ranked = list(dict.fromkeys(paths))[:top_k]
    ranks = [rank for rank, path in enumerate(ranked, 1) if path in relevant]
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(top_k, len(relevant)) + 1))
    return {
        "recall": len(ranks) / len(relevant),
        "mrr": 1 / ranks[0] if ranks else 0.0,
        "ndcg": sum(1 / math.log2(rank + 1) for rank in ranks) / ideal,
    }


def percentile(values: Sequence[float], fraction: float) -> float:
    """Return a nearest-rank percentile for nonempty measured samples."""
    if not values or not 0 < fraction <= 1:
        raise ValueError("Invalid percentile input")
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def regressions(
    current: dict[str, Any],
    baseline: dict[str, Any],
    max_recall_drop: float,
    max_latency_ratio: float | None,
) -> list[str]:
    """Compare like-for-like reports against explicitly selected acceptance thresholds."""
    if (
        current["corpus_sha256"] != baseline["corpus_sha256"]
        or current["top_k"] != baseline["top_k"]
    ):
        raise ValueError("Baseline corpus and cutoff must match")
    if max_recall_drop < 0 or max_latency_ratio is not None and max_latency_ratio <= 0:
        raise ValueError("Regression tolerances must be nonnegative (latency ratio positive)")
    failures = []
    for mode, summary in current["summaries"].items():
        previous = baseline["summaries"][mode]
        if summary["recall"] + max_recall_drop < previous["recall"]:
            failures.append(f"{mode}: recall decreased beyond tolerance")
        if max_latency_ratio is not None and (
            summary["p95_seconds"] > previous["p95_seconds"] * max_latency_ratio
        ):
            failures.append(f"{mode}: p95 latency exceeded the configured ratio")
    if any(row["degraded"] for row in current["trials"]):
        failures.append("A retrieval strategy degraded during the comparison")
    return failures
