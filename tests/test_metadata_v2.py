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
"""Metadata v2 chunk storage and reconstruction tests."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

import chunker
from chunker_utils import METADATA_CONTRACT_FIELDS, reconstruct_contract_metadata
from sync_hash_aware import _is_complete_current_version


def _note(root: Path, frontmatter: str = "") -> Path:
    section = root / "knowledge"
    section.mkdir(parents=True)
    note = section / "note.md"
    note.write_text(frontmatter + "# Note\n\n" + ("meaningful content. " * 40), encoding="utf-8")
    return note


def test_note_without_information_date_omits_nulls_and_keeps_mtime_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "vault"
    note = _note(root)
    modified = datetime(2025, 5, 4, 12, 30, tzinfo=timezone.utc)
    os.utime(note, (modified.timestamp(), modified.timestamp()))
    monkeypatch.setattr(chunker, "KB_PATH", str(root))

    metadata = chunker.chunk_markdown_file(note).chunks[0]["metadata"]
    contract = reconstruct_contract_metadata(metadata)

    assert set(contract) == set(METADATA_CONTRACT_FIELDS)
    assert contract["occurred_at"] is None
    assert contract["updated_at"] is None
    assert contract["author"] is None
    assert "occurred_at" not in metadata
    assert "occurred_at_epoch_ms" not in metadata
    assert metadata["file_modified_at"] == "2025-05-04T12:30:00Z"
    assert contract["source_kind"] == "note"
    assert contract["source_system"] == "vault"


def test_frontmatter_dates_are_utc_with_numeric_filter_projections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "vault"
    note = _note(
        root,
        "---\n"
        'title: "Dated note"\n'
        'author: "Julien"\n'
        "date: 2026-08-03T10:15:00+02:00\n"
        "updated: 2026-08-03T09:00:00Z\n"
        "---\n",
    )
    monkeypatch.setattr(chunker, "KB_PATH", str(root))

    metadata = chunker.chunk_markdown_file(note).chunks[0]["metadata"]

    assert metadata["occurred_at"] == "2026-08-03T08:15:00Z"
    assert metadata["updated_at"] == "2026-08-03T09:00:00Z"
    assert metadata["occurred_at_epoch_ms"] == 1_785_744_900_000
    assert metadata["updated_at_epoch_ms"] == 1_785_747_600_000
    assert metadata["author"] == "Julien"


def test_confluence_frontmatter_nulls_are_omitted_and_contract_hash_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "vault"
    contract_hash = "a" * 64
    note = _note(
        root,
        "---\n"
        "schema_version: 2\n"
        'source_kind: "doc"\n'
        'source_system: "confluence"\n'
        'source_uid: "123"\n'
        "author: null\n"
        "occurred_at: null\n"
        f'content_hash: "{contract_hash}"\n'
        "---\n",
    )
    monkeypatch.setattr(chunker, "KB_PATH", str(root))

    metadata = chunker.chunk_markdown_file(note).chunks[0]["metadata"]

    assert metadata["content_hash"] == contract_hash
    assert metadata["file_content_hash"] != contract_hash
    assert metadata["source_kind"] == "doc"
    assert metadata["source_system"] == "confluence"
    assert "author" not in metadata
    assert "occurred_at" not in metadata


def test_pre_v2_chunks_are_never_considered_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "vault"
    note = _note(root)
    monkeypatch.setattr(chunker, "KB_PATH", str(root))
    chunks = chunker.chunk_markdown_file(note).chunks
    current_metadata = [dict(chunk["metadata"]) for chunk in chunks]
    legacy_metadata = [dict(metadata) for metadata in current_metadata]
    for metadata in legacy_metadata:
        metadata.pop("schema_version")

    assert _is_complete_current_version(
        chunks, [str(chunk["id"]) for chunk in chunks], current_metadata
    )
    assert not _is_complete_current_version(
        chunks, [str(chunk["id"]) for chunk in chunks], legacy_metadata
    )
