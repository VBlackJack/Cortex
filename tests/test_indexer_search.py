# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Unit tests for search bounds and typed failures."""

from __future__ import annotations

from typing import Any

import pytest

import indexer


class Collection:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.n_results: list[int] = []

    def query(self, *, n_results: int, **_kwargs: object) -> dict[str, Any]:
        self.n_results.append(n_results)
        if self.error:
            raise self.error
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}


class Lexical:
    def __init__(
        self,
        *,
        present: bool = True,
        compatible: bool = True,
        hits: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.path = type("PathState", (), {"is_file": lambda _self: present})()
        self.compatible = compatible
        self.hits = hits or []
        self.error = error

    def is_compatible(self) -> bool:
        return self.compatible

    def search(self, *_args: object, **_kwargs: object) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        return self.hits


@pytest.mark.parametrize(("requested", "expected"), [(0, 1), (1, 1), (10, 10), (99, 10)])
def test_search_clamps_top_k(
    monkeypatch: pytest.MonkeyPatch,
    requested: int,
    expected: int,
) -> None:
    collection = Collection()
    monkeypatch.setattr(indexer, "get_collection", lambda: collection)
    monkeypatch.setattr(indexer, "LexicalIndex", lambda: Lexical(present=False))

    results = indexer.search("query", top_k=requested)
    assert results == []
    assert results.mode == "vector-only"
    assert collection.n_results == [expected]


def test_search_raises_typed_error_instead_of_pseudo_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = Collection(RuntimeError("database unavailable"))
    monkeypatch.setattr(indexer, "get_collection", lambda: collection)
    monkeypatch.setattr(indexer, "LexicalIndex", lambda: Lexical(present=False))

    with pytest.raises(indexer.CortexSearchError, match="database unavailable"):
        indexer.search("query")


def test_rrf_known_ranks_and_deterministic_ties() -> None:
    vector = [{"id": chunk_id} for chunk_id in ("a", "b", "c")]
    lexical = [{"id": chunk_id} for chunk_id in ("b", "d", "a")]

    fused = indexer.reciprocal_rank_fusion(vector, lexical, rrf_k=60)

    assert [hit["id"] for hit in fused] == ["b", "a", "d", "c"]
    tied = indexer.reciprocal_rank_fusion([{"id": "z"}], [{"id": "y"}], rrf_k=60)
    assert [hit["id"] for hit in tied] == ["y", "z"]
    assert all("lexical_only" in hit for hit in tied)


def test_lexical_only_hit_carries_freshness_contract_metadata() -> None:
    content_hash = "a" * 64
    chunk_id = f"knowledge/note.md::{content_hash}::v3::0"

    fused = indexer.reciprocal_rank_fusion(
        [],
        [
            {
                "id": chunk_id,
                "path": "knowledge/note.md",
                "section": "knowledge",
                "text": "exact",
            }
        ],
    )

    metadata = fused[0]["metadata"]
    assert metadata["content_hash"] == content_hash
    assert metadata["contract_id"] == "freshness-contract-v1"
    assert metadata["content_hash_contract_version"] == "v1"


def test_hybrid_search_uses_twenty_candidates_and_bounds_final_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HybridCollection(Collection):
        def query(self, *, n_results: int, **_kwargs: object) -> dict[str, Any]:
            self.n_results.append(n_results)
            ids = [f"v{index}" for index in range(n_results)]
            return {
                "ids": [ids],
                "documents": [[f"vector {index}" for index in range(n_results)]],
                "metadatas": [[{"path": f"knowledge/v{index}.md"} for index in range(n_results)]],
                "distances": [[index / 100 for index in range(n_results)]],
            }

    collection = HybridCollection()
    lexical_hits = [
        {
            "id": "lexical-only",
            "path": "knowledge/lexical.md",
            "section": "knowledge",
            "text": "lexical",
            "bm25": -1.0,
            "metadata": {"path": "knowledge/lexical.md", "section": "knowledge"},
        }
    ]
    monkeypatch.setattr(indexer, "get_collection", lambda: collection)
    monkeypatch.setattr(indexer, "LexicalIndex", lambda: Lexical(hits=lexical_hits))

    results = indexer.search("query", top_k=99)

    assert results.mode == "hybrid"
    assert len(results) == 10
    assert collection.n_results == [20]


def test_hybrid_search_exposes_rerank_mode_and_bounds_final_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HybridCollection(Collection):
        def query(self, *, n_results: int, **_kwargs: object) -> dict[str, Any]:
            self.n_results.append(n_results)
            ids = [f"v{index}" for index in range(n_results)]
            return {
                "ids": [ids],
                "documents": [[f"vector {index}" for index in range(n_results)]],
                "metadatas": [[{"path": f"knowledge/v{index}.md"} for index in range(n_results)]],
                "distances": [[index / 100 for index in range(n_results)]],
            }

    collection = HybridCollection()
    monkeypatch.setattr(indexer, "get_collection", lambda: collection)
    monkeypatch.setattr(indexer, "LexicalIndex", lambda: Lexical())

    observed: list[int] = []

    def rerank(
        _query: str, hits: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], None]:
        observed.append(len(hits))
        reranked = [dict(hit, rerank_score=1.0) for hit in reversed(hits[:10])]
        return reranked, None

    monkeypatch.setattr(indexer, "rerank_fused_hits", rerank)

    results = indexer.search("query", top_k=99)

    assert results.mode == "hybrid+rerank"
    assert len(results) == 10
    assert observed == [20]
    assert collection.n_results == [20]
    assert all("rerank_score" in hit and "rrf_score" in hit for hit in results)


def test_reranker_failure_exposes_hybrid_fallback_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HybridCollection(Collection):
        def query(self, *, n_results: int, **_kwargs: object) -> dict[str, Any]:
            ids = [f"v{index}" for index in range(n_results)]
            return {
                "ids": [ids],
                "documents": [[f"vector {index}" for index in range(n_results)]],
                "metadatas": [[{"path": f"knowledge/v{index}.md"} for index in range(n_results)]],
                "distances": [[index / 100 for index in range(n_results)]],
            }

    monkeypatch.setattr(indexer, "get_collection", HybridCollection)
    monkeypatch.setattr(indexer, "LexicalIndex", lambda: Lexical())
    monkeypatch.setattr(
        indexer,
        "rerank_fused_hits",
        lambda _query, hits: (hits, "reranker query failed: ONNX unavailable"),
    )

    results = indexer.search("query", top_k=5)

    assert results.mode == "hybrid"
    assert "ONNX unavailable" in str(results.fallback_reason)
    assert [hit["id"] for hit in results] == [f"v{index}" for index in range(5)]


@pytest.mark.parametrize(
    ("lexical", "reason"),
    [
        (Lexical(present=False), "absent"),
        (Lexical(compatible=False), "incompatible"),
    ],
)
def test_vector_only_fallback_is_explicit_and_never_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
    lexical: Lexical,
    reason: str,
) -> None:
    collection = Collection()
    monkeypatch.setattr(indexer, "get_collection", lambda: collection)
    monkeypatch.setattr(indexer, "LexicalIndex", lambda: lexical)
    monkeypatch.setattr(
        indexer,
        "prepare_lexical_index",
        lambda *_args, **_kwargs: pytest.fail("server search must not rebuild"),
    )

    results = indexer.search("query")

    assert results.mode == "vector-only"
    assert reason in str(results.fallback_reason)


def test_sqlite_query_error_falls_back_to_vector_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    collection = Collection()
    monkeypatch.setattr(indexer, "get_collection", lambda: collection)
    monkeypatch.setattr(
        indexer,
        "LexicalIndex",
        lambda: Lexical(error=sqlite3.OperationalError("broken FTS")),
    )

    results = indexer.search("query")

    assert results.mode == "vector-only"
    assert "broken FTS" in str(results.fallback_reason)
