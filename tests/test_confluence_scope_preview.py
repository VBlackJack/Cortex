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

from confluence_writer.config import ConfluenceSettings, PageSelection, SpaceMapping
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

    def __init__(
        self,
        *,
        descendant_count: int = 2,
        space_count: int = 4,
        ancestors: tuple[str, ...] = (),
    ) -> None:
        self.root = _page("100", "Root")
        self.descendant_count = descendant_count
        self.space_count = space_count
        self.ancestors = ancestors
        self.ancestor_calls = 0

    def ancestor_ids(self, page_id: str) -> tuple[str, ...]:
        assert page_id == "100"
        self.ancestor_calls += 1
        return self.ancestors

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


def _settings(selection: str = "pages", pages: tuple[str, ...] = ()) -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=3,
        base_url="https://wiki.example.test",
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="confluence/DOC",
                classification="pro-confidentiel",
                selection=selection,  # type: ignore[arg-type]
                pages=None
                if selection == "whole_space"
                else tuple(PageSelection(page_id=page_id) for page_id in pages),
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
    assert preview.coverage == "none"
    assert preview.covering_root is None


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


def _preview(client: PreviewClient, settings: ConfluenceSettings):  # type: ignore[no-untyped-def]
    return preview_scope(
        "100",
        settings=settings,
        client=client,  # type: ignore[arg-type]
        storage_root=str(Path("C:/state")),
        retention_generations=2,
    )


def test_preview_reports_an_unlisted_page_as_uncovered_without_asking_for_ancestors() -> None:
    client = PreviewClient(ancestors=("7",))

    preview = _preview(client, _settings("pages", ("7",)))

    assert (preview.coverage, preview.covering_root) == ("none", None)
    assert client.ancestor_calls == 0


def test_preview_reports_a_listed_page_as_covered_by_itself() -> None:
    client = PreviewClient(ancestors=("7",))

    preview = _preview(client, _settings("subtree", ("7", "100")))

    assert (preview.coverage, preview.covering_root) == ("page", "100")
    assert client.ancestor_calls == 0


def test_preview_reports_a_descendant_as_covered_by_its_listed_root() -> None:
    """The chain runs from the top of the space down, so the first listed ancestor met
    is the highest configured root above the page."""
    client = PreviewClient(ancestors=("9", "7", "8"))

    preview = _preview(client, _settings("subtree", ("8", "7")))

    assert (preview.coverage, preview.covering_root) == ("subtree", "7")
    assert client.ancestor_calls == 1


def test_preview_reports_a_page_outside_every_subtree_as_uncovered() -> None:
    client = PreviewClient(ancestors=("9",))

    preview = _preview(client, _settings("subtree", ("7",)))

    assert (preview.coverage, preview.covering_root) == ("none", None)
    assert client.ancestor_calls == 1


def test_preview_reports_a_whole_space_as_covering_the_page() -> None:
    client = PreviewClient()

    preview = _preview(client, _settings("whole_space"))

    assert (preview.coverage, preview.covering_root) == ("whole_space", None)
    assert client.ancestor_calls == 0
