# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
"""Measured scope preview contracts for novice-safe configuration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
    def __init__(self) -> None:
        self.root = _page("100", "Root")
        self.descendants = (_page("101", "Child"), _page("102", "Grandchild"))
        self.space = (*self.descendants, self.root, _page("200", "Other"))

    def get_page_by_id(self, page_id: str) -> RemotePage:
        assert page_id == "100"
        return self.root

    def enumerate_subtree(self, root_id: str, space_key: str) -> tuple[RemotePage, ...]:
        assert (root_id, space_key) == ("100", "DOC")
        return self.descendants

    def enumerate_pages(self, space_key: str) -> tuple[RemotePage, ...]:
        assert space_key == "DOC"
        return self.space


def test_preview_measures_all_choices_and_recommends_subtree() -> None:
    settings = ConfluenceSettings(
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

    preview = preview_scope(
        "100",
        settings=settings,
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
