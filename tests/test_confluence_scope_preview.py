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
"""Measured scope preview contracts for novice-safe configuration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from confluence_writer.config import ConfluenceSettings, SpaceMapping
from confluence_writer.models import RemotePage
from confluence_writer.resolver import preview_scope

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _page(page_id: str, title: str) -> RemotePage:
    return RemotePage(
        page_id=page_id,
        title=title,
        space_key="DOC",
        version_number=1,
        version_when=_NOW,
        last_updated=_NOW,
        author="Fixture",
        occurred_at=_NOW,
        canonical_uri=f"https://wiki.example.test/spaces/DOC/pages/{page_id}",
    )


class PreviewClient:
    """Answer the preview with counts, and fail loudly on any enumeration."""

    def __init__(self, *, descendant_count: int = 2, space_count: int = 4) -> None:
        self.root = _page("100", "Root")
        self.descendant_count = descendant_count
        self.space_count = space_count

    def get_page_by_id(self, page_id: str) -> RemotePage:
        assert page_id == "100"
        return self.root

    def get_space_homepage(self, space_key: str) -> RemotePage:
        assert space_key == "DOC"
        return self.root

    def count_subtree(self, root_id: str, space_key: str) -> int:
        assert (root_id, space_key) == ("100", "DOC")
        return self.descendant_count

    def count_pages(self, space_key: str) -> int:
        assert space_key == "DOC"
        return self.space_count

    def enumerate_subtree(self, root_id: str, space_key: str) -> tuple[RemotePage, ...]:
        raise AssertionError("preview must not enumerate the subtree")

    def enumerate_pages(self, space_key: str) -> tuple[RemotePage, ...]:
        raise AssertionError("preview must not enumerate the whole space")


def _settings() -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=3,
        base_url="https://wiki.example.test",
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="confluence/DOC",
                classification="pro-confidentiel",
                selection="pages",
                pages=(),
            ),
        ),
    )


@pytest.mark.parametrize(
    "reference",
    [
        "100",
        "https://wiki.example.test/spaces/DOC",
        "https://wiki.example.test/spaces/DOC/overview",
        "https://wiki.example.test/display/DOC",
    ],
)
def test_preview_measures_all_choices_and_recommends_subtree(reference: str) -> None:
    preview = preview_scope(
        reference,
        settings=_settings(),
        client=PreviewClient(),  # type: ignore[arg-type]
        storage_root=str(Path("C:/state")),
        retention_generations=2,
    )

    assert preview.title == "Root"
    assert preview.page_only.page_count == 1
    assert preview.subtree.page_count == 3
    assert preview.whole_space.page_count == 4
    assert preview.recommended_selection == "subtree"
    assert preview.subtree.estimated_bytes == 3 * 384 * 1024
    assert preview.retention_generations == 2


def test_preview_recommends_pages_when_the_root_has_no_descendant() -> None:
    preview = preview_scope(
        "100",
        settings=_settings(),
        client=PreviewClient(descendant_count=0, space_count=7),  # type: ignore[arg-type]
        storage_root=str(Path("C:/state")),
        retention_generations=2,
    )

    assert preview.recommended_selection == "pages"
    assert preview.subtree.page_count == 1
    assert preview.whole_space.page_count == 7


def test_preview_reports_an_empty_space_as_empty() -> None:
    """Folding the resolved root into the whole-space set gave that number a floor of
    one. The count has none, so a space the caller can see no page in now measures
    zero, which is a value no released client has ever been handed."""
    preview = preview_scope(
        "100",
        settings=_settings(),
        client=PreviewClient(descendant_count=0, space_count=0),  # type: ignore[arg-type]
        storage_root=str(Path("C:/state")),
        retention_generations=2,
    )

    assert preview.whole_space.page_count == 0
    assert preview.whole_space.estimated_bytes == 0
    assert preview.page_only.page_count == 1
