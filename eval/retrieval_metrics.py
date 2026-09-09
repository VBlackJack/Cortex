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
    for mode, previous in baseline["summaries"].items():
        if mode not in current["summaries"]:
            raise ValueError("Current report omits a baseline retrieval strategy")
        summary = current["summaries"][mode]
        if summary["recall"] + max_recall_drop < previous["recall"]:
            failures.append(f"{mode}: recall decreased beyond tolerance")
        if max_latency_ratio is not None and (
            summary["p95_seconds"] > previous["p95_seconds"] * max_latency_ratio
        ):
            failures.append(f"{mode}: p95 latency exceeded the configured ratio")
    if any(row["degraded"] for row in current["trials"]):
        failures.append("A retrieval strategy degraded during the comparison")
    return failures


def acceptance_failures(report: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    """Gate the actual default per language, rejecting an incomparable or partial run."""
    if (policy.get("schema_version") != 1
            or report["corpus_sha256"] != policy.get("corpus_sha256")
            or report["top_k"] != policy.get("top_k")):
        raise ValueError("Acceptance corpus and cutoff must match")
    languages = policy.get("languages")
    if not isinstance(languages, dict) or not languages:
        raise ValueError("Acceptance policy must define languages")
    failures = []
    defaults = [row for row in report["trials"] if row["requested_mode"] == "default"]
    for language, limits in languages.items():
        minimum = limits["min_recall"]
        count = limits["questions"]
        if (not isinstance(minimum, (float, int)) or not math.isfinite(minimum)
                or not 0 <= minimum <= 1 or type(count) is not int or count < 1):
            raise ValueError("Invalid acceptance limits")
        rows = [row for row in defaults if row["language"] == language]
        if len(rows) != count or len({row["id"] for row in rows}) != count:
            failures.append(f"{language}: default trials missing or duplicated")
            continue
        if any(row["degraded"] for row in rows):
            failures.append(f"{language}: default retrieval degraded")
        scores = [row["recall"] for row in rows]
        if any(not math.isfinite(score) or not 0 <= score <= 1 for score in scores):
            raise ValueError("Invalid recall measurement")
        if sum(scores) / count < minimum:
            failures.append(f"{language}: default recall below acceptance minimum")
    return failures
