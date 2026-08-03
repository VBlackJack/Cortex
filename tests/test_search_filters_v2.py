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
"""Vector, lexical and MCP metadata v2 parity tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import freshness
import server
from chunker_utils import METADATA_CONTRACT_FIELDS
from indexer import SearchResults, _vector_search, build_chroma_where
from lexical_index import LexicalIndex


class FilteredCollection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    @staticmethod
    def _matches(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
        if where is None:
            return True
        if "$and" in where:
            return all(FilteredCollection._matches(metadata, item) for item in where["$and"])
        key, expected = next(iter(where.items()))
        actual = metadata.get(key)
        if not isinstance(expected, dict):
            return actual == expected
        if "$in" in expected:
            return actual in expected["$in"]
        if "$gte" in expected:
            return isinstance(actual, int) and actual >= expected["$gte"]
        if "$lte" in expected:
            return isinstance(actual, int) and actual <= expected["$lte"]
        return False

    def query(self, **kwargs: Any) -> dict[str, Any]:
        selected = [
            row for row in self.rows if self._matches(row["metadata"], kwargs.get("where"))
        ][: kwargs["n_results"]]
        return {
            "ids": [[row["id"] for row in selected]],
            "documents": [[row["text"] for row in selected]],
            "metadatas": [[row["metadata"] for row in selected]],
            "distances": [[0.1 for _row in selected]],
        }

    def get(self, *, limit: int, offset: int, include: list[str]) -> dict[str, Any]:
        del include
        selected = self.rows[offset : offset + limit]
        return {
            "ids": [row["id"] for row in selected],
            "documents": [row["text"] for row in selected],
            "metadatas": [row["metadata"] for row in selected],
        }


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "id": "doc",
            "text": "shared filter token",
            "metadata": {
                "schema_version": 2,
                "path": "docs/doc.md",
                "section": "docs",
                "source_kind": "doc",
                "author": "Julien",
                "occurred_at_epoch_ms": 1_785_744_900_000,
                "updated_at_epoch_ms": 1_785_747_600_000,
            },
        },
        {
            "id": "note",
            "text": "shared filter token",
            "metadata": {
                "schema_version": 2,
                "path": "docs/note.md",
                "section": "docs",
                "source_kind": "note",
                "author": "Other",
                "occurred_at_epoch_ms": 1_700_000_000_000,
                "updated_at_epoch_ms": 1_700_000_000_000,
            },
        },
    ]


def test_epoch_range_and_identity_filters_match_both_search_branches(tmp_path: Path) -> None:
    rows = _rows()
    collection = FilteredCollection(rows)
    lexical = LexicalIndex(tmp_path / "lexical.db")
    lexical.rebuild(collection)
    where, lexical_filters = build_chroma_where(
        section="docs",
        source_kinds=["doc"],
        authors=["Julien"],
        occurred_at_from="2026-08-03T08:00:00Z",
        occurred_at_to="2026-08-03T08:30:00Z",
        updated_at_from="2026-08-03T08:30:00Z",
        updated_at_to="2026-08-03T09:30:00Z",
    )

    vector_ids = [hit["id"] for hit in _vector_search(collection, "filter", where, 20)]
    lexical_ids = [
        hit["id"]
        for hit in lexical.search(
            "filter",
            section="docs",
            **lexical_filters,
            limit=20,
        )
    ]

    assert vector_ids == ["doc"]
    assert lexical_ids == ["doc"]
    assert where is not None
    assert {"occurred_at_epoch_ms": {"$gte": 1_785_744_000_000}} in where["$and"]
    assert {"updated_at_epoch_ms": {"$lte": 1_785_749_400_000}} in where["$and"]


def test_mcp_success_is_structured_with_complete_contract_and_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freshness, "KB_PATH", None)
    monkeypatch.setattr(
        server,
        "search",
        lambda **_kwargs: SearchResults(
            [
                {
                    "id": "doc",
                    "text": "structured content",
                    "metadata": {
                        "schema_version": 2,
                        "source_kind": "doc",
                        "source_system": "confluence",
                        "title": "Architecture",
                        "path": "docs/architecture.md",
                        "canonical_uri": "https://example.test/pages/123",
                    },
                    "distance": 0.1,
                }
            ],
            mode="hybrid",
        ),
    )

    response = server.cortex_search("architecture", source_kinds=["doc"])

    assert isinstance(response, dict)
    assert response["schema_version"] == 2
    assert set(response["results"][0]["metadata"]) == set(METADATA_CONTRACT_FIELDS)
    assert response["results"][0]["citation"] == "https://example.test/pages/123"
    assert "**Source:** doc / confluence" in response["markdown"]
    assert "[Architecture](https://example.test/pages/123)" in response["markdown"]
