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
"""SQLite FTS5 indexing, sanitization, rebuild and filtering tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from config import LEXICAL_INDEX_CONTRACT_VERSION
from lexical_index import LexicalIndex, prepare_lexical_index, sanitize_fts5_query


class Collection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def get(self, *, limit: int, offset: int, include: list[str]) -> dict[str, Any]:
        del include
        selected = self.rows[offset : offset + limit]
        return {
            "ids": [row["id"] for row in selected],
            "documents": [row["text"] for row in selected],
            "metadatas": [row["metadata"] for row in selected],
        }


def _chunk(
    chunk_id: str,
    text: str,
    *,
    path: str = "knowledge/note.md",
    section: str = "knowledge",
) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "text": text,
        "metadata": {"path": path, "section": section},
    }


def test_sanitize_fts5_query_neutralizes_operators(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.db")
    index.rebuild(Collection([_chunk("one", "NEAR exact café alpha beta")]))

    assert sanitize_fts5_query('"alpha" * NEAR(beta) - café') == (
        '"alpha" OR "NEAR" OR "beta" OR "café"'
    )
    assert sanitize_fts5_query('"*-') is None
    for query in ('"alpha"', "alpha*", "NEAR(alpha beta)", "-alpha", "café", ""):
        index.search(query)


def test_incremental_replace_delete_and_section_filter(tmp_path: Path) -> None:
    index = LexicalIndex(tmp_path / "lexical.db")
    index.rebuild(
        Collection(
            [
                _chunk("old", "obsolete token"),
                _chunk(
                    "other",
                    "replacement token",
                    path="projects/other.md",
                    section="projects",
                ),
            ]
        )
    )

    index.replace_file([_chunk("new", "replacement token")])

    assert index.ids() == {"new", "other"}
    assert [hit["id"] for hit in index.search("replacement", section="knowledge")] == [
        "new"
    ]
    assert [hit["id"] for hit in index.search("replacement", section="projects")] == [
        "other"
    ]
    index.delete_path("knowledge/note.md")
    assert index.ids() == {"other"}


def test_rebuild_repairs_missing_and_incompatible_index(tmp_path: Path) -> None:
    path = tmp_path / "lexical.db"
    rows = [_chunk("one", "first"), _chunk("two", "second")]

    rebuilt = prepare_lexical_index(Collection(rows), path)

    assert rebuilt.count() == 2
    assert rebuilt.ids() == {"one", "two"}
    with rebuilt._connect_write() as connection:
        connection.execute(
            "UPDATE meta SET value = 'unexpected' WHERE key = 'contract_version'"
        )
    repaired = prepare_lexical_index(Collection(rows), path)
    assert repaired.metadata()["contract_version"] == LEXICAL_INDEX_CONTRACT_VERSION  # type: ignore[index]


def test_replace_file_rolls_back_on_sqlite_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = LexicalIndex(tmp_path / "lexical.db")
    index.rebuild(Collection([_chunk("old", "old text")]))

    class BrokenConnection:
        def __enter__(self) -> BrokenConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, *_args: object) -> None:
            raise RuntimeError("sqlite failed")

        def close(self) -> None:
            return None

    monkeypatch.setattr(index, "_connect_write", lambda: BrokenConnection())
    with pytest.raises(RuntimeError, match="sqlite failed"):
        index.replace_file([_chunk("new", "new text")])
    assert index.ids() == {"old"}
