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


@pytest.mark.parametrize(("requested", "expected"), [(0, 1), (1, 1), (10, 10), (99, 10)])
def test_search_clamps_top_k(
    monkeypatch: pytest.MonkeyPatch,
    requested: int,
    expected: int,
) -> None:
    collection = Collection()
    monkeypatch.setattr(indexer, "get_collection", lambda: collection)

    assert indexer.search("query", top_k=requested) == []
    assert collection.n_results == [expected]


def test_search_raises_typed_error_instead_of_pseudo_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = Collection(RuntimeError("database unavailable"))
    monkeypatch.setattr(indexer, "get_collection", lambda: collection)

    with pytest.raises(indexer.CortexSearchError, match="database unavailable"):
        indexer.search("query")
