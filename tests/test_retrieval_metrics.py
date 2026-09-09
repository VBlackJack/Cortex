# Copyright 2026 Julien Bombled
# Licensed under the Apache License, Version 2.0.
"""Discriminating tests for document-level retrieval scores and corpus integrity."""

import json
from pathlib import Path

import pytest

from eval.retrieval_metrics import acceptance_failures, metrics, percentile, regressions


def test_duplicate_chunks_do_not_inflate_recall() -> None:
    assert metrics(["a", "a", "x", "b"], ["a", "b"], 3)["recall"] == 1
    assert metrics(["a", "a"], ["a", "b"], 5)["recall"] == 0.5


def test_rank_penalty_and_no_hit() -> None:
    result = metrics(["noise", "answer"], ["answer"], 5)
    assert result["mrr"] == 0.5
    assert 0 < result["ndcg"] < 1
    assert metrics(["noise"], ["answer"], 5) == {"recall": 0, "mrr": 0, "ndcg": 0}
    assert percentile([1, 2, 3, 4, 100], 0.95) == 100
    with pytest.raises(ValueError):
        metrics([], [], 5)


def test_corpus_has_thirty_bilingual_questions_with_existing_targets() -> None:
    corpus = json.loads(
        (Path(__file__).parents[1] / "eval/retrieval_corpus.json").read_text("utf-8")
    )
    paths = {doc["path"] for doc in corpus["documents"]}
    assert len(corpus["questions"]) == 30
    assert len({q["id"] for q in corpus["questions"]}) == 30
    assert {q["language"] for q in corpus["questions"]} == {"fr", "en"}
    assert all(set(q["expected"]) <= paths for q in corpus["questions"])


def test_baseline_gate_rejects_regression_and_incomparable_corpus() -> None:
    baseline = {
        "corpus_sha256": "same",
        "top_k": 5,
        "summaries": {"vector": {"recall": 1.0, "p95_seconds": 1.0}},
        "trials": [],
    }
    current = {**baseline, "summaries": {"vector": {"recall": 0.9, "p95_seconds": 3.0}}}
    assert len(regressions(current, baseline, 0, 2)) == 2
    assert regressions(current, baseline, 0.2, None) == []
    with pytest.raises(ValueError, match="corpus"):
        regressions({**current, "corpus_sha256": "different"}, baseline, 0, None)


def test_bilingual_acceptance_cannot_hide_french_losses_behind_english_scores() -> None:
    policy = {"schema_version": 1, "corpus_sha256": "same", "top_k": 5,
              "languages": {"fr": {"questions": 1, "min_recall": 0.9},
                            "en": {"questions": 1, "min_recall": 1.0}}}
    trials = [{"requested_mode": "default", "id": language, "language": language,
               "recall": score, "degraded": False}
              for language, score in (("fr", 0.5), ("en", 1.0))]
    report = {"corpus_sha256": "same", "top_k": 5, "trials": trials}
    assert acceptance_failures(report, policy) == ["fr: default recall below acceptance minimum"]
    trials[0]["recall"] = 1.0
    assert acceptance_failures(report, policy) == []
    trials[0]["degraded"] = True
    assert acceptance_failures(report, policy) == ["fr: default retrieval degraded"]
    trials.pop()
    assert "en: default trials missing or duplicated" in acceptance_failures(report, policy)
    with pytest.raises(ValueError, match="corpus"):
        acceptance_failures({**report, "corpus_sha256": "other"}, policy)


def test_committed_acceptance_is_bound_to_the_evaluated_corpus() -> None:
    import hashlib

    root = Path(__file__).parents[1] / "eval"
    policy = json.loads((root / "retrieval_acceptance.json").read_text("utf-8"))
    assert hashlib.sha256((root / "retrieval_corpus.json").read_bytes()).hexdigest() == (
        policy["corpus_sha256"]
    )
