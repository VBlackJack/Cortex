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
"""Central Chroma pagination helper tests."""

from __future__ import annotations

from typing import Any

import pytest

from chroma_client import iter_collection_pages


class FakeCollection:
    def __init__(self, ids: list[str], error_offset: int | None = None) -> None:
        self.ids = ids
        self.error_offset = error_offset
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        offset = int(kwargs["offset"])
        limit = int(kwargs["limit"])
        if self.error_offset == offset:
            raise RuntimeError("page failure")
        return {"ids": self.ids[offset : offset + limit]}


def test_iter_collection_pages_covers_exact_multiple_and_terminal_page() -> None:
    collection = FakeCollection(["a", "b", "c", "d"])

    pages = list(
        iter_collection_pages(
            collection,
            page_size=2,
            include=["metadatas"],
        )
    )

    assert [page["ids"] for page in pages] == [["a", "b"], ["c", "d"], []]
    assert [call["offset"] for call in collection.calls] == [0, 2, 4]
    assert all(call["include"] == ["metadatas"] for call in collection.calls)


def test_iter_collection_pages_propagates_collection_errors() -> None:
    collection = FakeCollection(["a", "b", "c"], error_offset=2)

    with pytest.raises(RuntimeError, match="page failure"):
        list(iter_collection_pages(collection, page_size=2))


def test_iter_collection_pages_rejects_invalid_page_size() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        list(iter_collection_pages(FakeCollection([]), page_size=0))
