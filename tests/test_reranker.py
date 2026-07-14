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
"""Unit tests for bounded, deterministic cross-encoder reranking."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pytest

import reranker
from config import SEARCH_RERANK_CANDIDATES, SEARCH_TOP_K_MAX


class FakeCrossEncoder:
    def __init__(
        self,
        scores: list[float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.scores = scores or []
        self.error = error
        self.calls: list[tuple[str, list[str], int]] = []

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        batch_size: int = 64,
    ) -> Iterable[float]:
        self.calls.append((query, list(documents), batch_size))
        if self.error is not None:
            raise self.error
        return self.scores[: len(documents)]


@pytest.fixture(autouse=True)
def reset_reranker() -> Iterable[None]:
    reranker._reset_for_tests()
    yield
    reranker._reset_for_tests()


def _hits(count: int) -> list[dict[str, object]]:
    return [
        {"id": f"c{index}", "text": f"document {index}", "rrf_score": 1 / (61 + index)}
        for index in range(count)
    ]


def test_rerank_candidate_budget_covers_maximum_top_k() -> None:
    assert SEARCH_RERANK_CANDIDATES >= SEARCH_TOP_K_MAX


def test_rerank_exact_order_tie_break_scores_and_single_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeCrossEncoder([0.1, 0.9, 0.9])
    monkeypatch.setattr(reranker, "_model", model)

    result, failure = reranker.rerank_fused_hits("query", _hits(3))

    assert failure is None
    assert [hit["id"] for hit in result] == ["c1", "c2", "c0"]
    assert [hit["rerank_score"] for hit in result] == [0.9, 0.9, 0.1]
    assert all("rrf_score" in hit for hit in result)
    assert model.calls == [
        ("query", ["document 0", "document 1", "document 2"], 10)
    ]


def test_rerank_is_bounded_to_ten_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeCrossEncoder([float(index) for index in range(10)])
    monkeypatch.setattr(reranker, "_model", model)

    result, failure = reranker.rerank_fused_hits("query", _hits(12))

    assert failure is None
    assert len(result) == 10
    assert len(model.calls[0][1]) == 10
    assert [hit["id"] for hit in result] == [f"c{index}" for index in range(9, -1, -1)]


def test_unwarmed_model_preserves_rrf_order_with_reason() -> None:
    hits = _hits(3)

    result, failure = reranker.rerank_fused_hits("query", hits)

    assert result is hits
    assert failure == "reranker is not warmed up"


def test_query_exception_preserves_rrf_order_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = _hits(3)
    monkeypatch.setattr(
        reranker,
        "_model",
        FakeCrossEncoder(error=RuntimeError("ONNX unavailable")),
    )

    result, failure = reranker.rerank_fused_hits("query", hits)

    assert result is hits
    assert "ONNX unavailable" in str(failure)


def test_load_failure_is_explicit_and_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_load(*_args: object, **_kwargs: object) -> None:
        raise OSError("model absent")

    monkeypatch.setattr(reranker, "TextCrossEncoder", fail_load)

    assert "model absent" in str(reranker.warmup_reranker())
    assert "model absent" in str(reranker.rerank_fused_hits("query", _hits(1))[1])


def test_two_identical_executions_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeCrossEncoder([0.2, 0.3, 0.1])
    monkeypatch.setattr(reranker, "_model", model)

    first, _ = reranker.rerank_fused_hits("query", _hits(3))
    second, _ = reranker.rerank_fused_hits("query", _hits(3))

    assert first == second
    assert len(model.calls) == 2
