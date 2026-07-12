# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Failure-safety and reconciliation tests for hash-aware publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sync_hash_aware
from chunker_utils import ChunkResult
from config import (
    CHUNKING_CONTRACT_VERSION,
    FRESHNESS_CONTRACT_ID,
    FRESHNESS_CONTRACT_VERSION,
)
from sync_hash_aware import _sync_section_locked, sync_file


class Collection:
    def __init__(
        self,
        fail_upsert_call: int | None = None,
        fail_delete_call: int | None = None,
    ) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.upsert_calls = 0
        self.delete_calls = 0
        self.fail_upsert_call = fail_upsert_call
        self.fail_delete_call = fail_delete_call

    def seed(self, chunks: list[dict[str, Any]]) -> None:
        for chunk in chunks:
            self.rows[chunk["id"]] = {
                "document": chunk["text"],
                "metadata": dict(chunk["metadata"]),
            }

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        self.upsert_calls += 1
        if self.upsert_calls == self.fail_upsert_call:
            raise RuntimeError("interrupted upsert")
        for chunk_id, document, metadata in zip(ids, documents, metadatas):
            self.rows[chunk_id] = {
                "document": document,
                "metadata": dict(metadata),
            }

    def delete(self, ids: list[str]) -> None:
        self.delete_calls += 1
        if self.delete_calls == self.fail_delete_call:
            raise RuntimeError("interrupted delete")
        for chunk_id in ids:
            self.rows.pop(chunk_id, None)

    def get(
        self,
        ids: list[str] | None = None,
        where: dict[str, str] | None = None,
        include: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, list[Any]]:
        del include
        selected = []
        wanted = set(ids) if ids is not None else None
        for chunk_id, row in sorted(self.rows.items()):
            if wanted is not None and chunk_id not in wanted:
                continue
            metadata = row["metadata"]
            if where and any(metadata.get(key) != value for key, value in where.items()):
                continue
            selected.append((chunk_id, metadata))
        if limit is not None:
            selected = selected[offset : offset + limit]
        return {
            "ids": [chunk_id for chunk_id, _ in selected],
            "metadatas": [metadata for _, metadata in selected],
        }


def _chunks(
    count: int = 1,
    *,
    path: str = "knowledge/note.md",
    content_hash: str = "a" * 64,
    chunking_version: str = CHUNKING_CONTRACT_VERSION,
) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{path}::{content_hash}::{chunking_version}::{index}",
            "text": f"text {index}",
            "metadata": {
                "path": path,
                "section": path.split("/", 1)[0],
                "content_hash": content_hash,
                "contract_id": FRESHNESS_CONTRACT_ID,
                "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
                "chunking_contract_version": chunking_version,
                "expected_chunk_count": count,
                "chunk_index": index,
            },
        }
        for index in range(count)
    ]


def test_failure_after_second_batch_preserves_old_and_retry_repairs() -> None:
    old = _chunks(content_hash="0" * 64)
    new = _chunks(101, content_hash="1" * 64)
    collection = Collection(fail_upsert_call=2)
    collection.seed(old)

    with pytest.raises(RuntimeError, match="interrupted upsert"):
        sync_file(collection, new, [old[0]["id"]])

    assert old[0]["id"] in collection.rows
    assert len(set(collection.rows) & {chunk["id"] for chunk in new}) == 100

    collection.fail_upsert_call = None
    added, deleted = sync_file(collection, new, list(collection.rows))

    assert added == 101
    assert deleted == 1
    assert set(collection.rows) == {chunk["id"] for chunk in new}


def test_crash_after_verification_before_delete_repairs_on_retry() -> None:
    old = _chunks(content_hash="0" * 64)
    new = _chunks(3, content_hash="1" * 64)
    collection = Collection(fail_delete_call=1)
    collection.seed(old)

    with pytest.raises(RuntimeError, match="interrupted delete"):
        sync_file(collection, new, [old[0]["id"]])

    assert old[0]["id"] in collection.rows
    assert {chunk["id"] for chunk in new} <= set(collection.rows)

    collection.fail_delete_call = None
    sync_file(collection, new, list(collection.rows))
    assert set(collection.rows) == {chunk["id"] for chunk in new}


def test_exact_expected_ids_remove_same_hash_orphans() -> None:
    current = _chunks(3)
    old_larger = _chunks(5)
    collection = Collection()
    collection.seed(old_larger)

    _, deleted = sync_file(collection, current, list(collection.rows))

    assert deleted == 2
    assert set(collection.rows) == {chunk["id"] for chunk in current}


def test_rechunking_same_bytes_replaces_old_chunking_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _chunks(2, chunking_version="v1")
    new = _chunks(3, chunking_version="v2")
    collection = Collection()
    collection.seed(old)
    monkeypatch.setattr(sync_hash_aware, "CHUNKING_CONTRACT_VERSION", "v2")

    sync_file(collection, new, list(collection.rows))

    assert set(collection.rows) == {chunk["id"] for chunk in new}


@pytest.mark.parametrize(
    ("status", "deletes_old", "errors"),
    [
        ("empty", True, 0),
        ("too_large", True, 0),
        ("read_error", False, 1),
        ("extraction_error", False, 1),
    ],
)
def test_zero_chunk_statuses_have_explicit_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    deletes_old: bool,
    errors: int,
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    source = section / "note.md"
    source.write_text("source present", encoding="utf-8")
    old = _chunks(content_hash="0" * 64)
    collection = Collection()
    collection.seed(old)
    monkeypatch.setitem(
        sync_hash_aware.CHUNKERS,
        ".md",
        lambda _path: ChunkResult(status=status, error="boom"),  # type: ignore[arg-type]
    )

    stats = _sync_section_locked(collection, root, "knowledge")

    assert stats["errors"] == errors
    assert (old[0]["id"] not in collection.rows) is deletes_old
    assert stats["removed_files"] == int(deletes_old)


def test_reconciliation_removes_absent_and_newly_excluded_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "kb"
    archive = root / "knowledge" / "_archive"
    archive.mkdir(parents=True)
    (archive / "secret.md").write_text("still present but excluded", encoding="utf-8")
    missing = _chunks(path="knowledge/missing.md", content_hash="0" * 64)
    excluded = _chunks(path="knowledge/_archive/secret.md", content_hash="1" * 64)
    collection = Collection()
    collection.seed(missing + excluded)

    stats = _sync_section_locked(collection, root, "knowledge")

    assert collection.rows == {}
    assert stats["removed_files"] == 2
    assert stats["deleted_chunks"] == 2


def test_complete_hash_and_chunking_version_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    (section / "note.md").write_text("source present", encoding="utf-8")
    current = _chunks()
    collection = Collection()
    collection.seed(current)
    monkeypatch.setitem(
        sync_hash_aware.CHUNKERS,
        ".md",
        lambda _path: ChunkResult(status="ok", chunks=current),
    )

    stats = _sync_section_locked(collection, root, "knowledge")

    assert stats["skipped_files"] == 1
    assert collection.upsert_calls == 0
