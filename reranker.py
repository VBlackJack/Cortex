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
"""Stateless ONNX cross-encoder reranking with explicit degradation."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from fastembed.rerank.cross_encoder import TextCrossEncoder

from config import RERANKER_MODEL, SEARCH_RERANK_CANDIDATES

log = logging.getLogger("cortex.search")


class CrossEncoder(Protocol):
    """Minimal fastembed cross-encoder surface used by Cortex."""

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        batch_size: int = 64,
    ) -> Iterable[float]: ...


_model: CrossEncoder | None = None
_load_failure = "reranker is not warmed up"


def warmup_reranker() -> str | None:
    """Load the configured model once; return an explicit failure reason."""
    global _load_failure, _model
    if _model is not None:
        return None
    try:
        _model = TextCrossEncoder(RERANKER_MODEL, threads=None, cuda=False)
    except Exception as exc:  # noqa: BLE001 -- startup must degrade, never fail hard.
        _load_failure = f"reranker load failed: {type(exc).__name__}: {exc}"
        log.warning("reranker_warmup_failed reason=%s", _load_failure)
        return _load_failure
    _load_failure = ""
    return None


def rerank_fused_hits(
    query: str,
    hits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Rerank one bounded fused batch, preserving RRF order on any failure."""
    if _model is None:
        return hits, _load_failure
    candidates = hits[:SEARCH_RERANK_CANDIDATES]
    try:
        scores = [
            float(score)
            for score in _model.rerank(
                query,
                [str(hit.get("text", "")) for hit in candidates],
                batch_size=SEARCH_RERANK_CANDIDATES,
            )
        ]
        if len(scores) != len(candidates):
            raise ValueError(
                f"reranker returned {len(scores)} scores for {len(candidates)} hits"
            )
    except Exception as exc:  # noqa: BLE001 -- query must degrade, never fail hard.
        reason = f"reranker query failed: {type(exc).__name__}: {exc}"
        log.warning("reranker_query_failed reason=%s", reason)
        return hits, reason

    order = sorted(range(len(candidates)), key=lambda index: (-scores[index], index))
    reranked: list[dict[str, Any]] = []
    for index in order:
        hit = dict(candidates[index])
        hit["rerank_score"] = scores[index]
        reranked.append(hit)
    return reranked, None


def _reset_for_tests() -> None:
    """Reset process state for isolated unit tests."""
    global _load_failure, _model
    _model = None
    _load_failure = "reranker is not warmed up"
