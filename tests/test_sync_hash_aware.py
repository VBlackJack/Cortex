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
"""Failure-safety and reconciliation tests for hash-aware publication."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import sync_hash_aware
from chunker_utils import ChunkResult
from config import (
    CHUNKING_CONTRACT_VERSION,
    FRESHNESS_CONTRACT_ID,
    FRESHNESS_CONTRACT_VERSION,
    ROOT_SECTION,
)
from confluence_writer.frontmatter import render_document
from confluence_writer.models import RemotePage
from freshness import cortex_ingestion_index_freshness_report
from ingestion.engine import GenerationEngine
from ingestion.models import CollectedDocument, GenerationAttempt
from ingestion.storage import IngestionStorage
from lexical_index import LexicalIndex
from sync_hash_aware import (
    _sync_section_locked,
    sync_file,
    sync_ingestion_documents,
)

_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


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
            "documents": [self.rows[chunk_id]["document"] for chunk_id, _ in selected],
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
    old = _chunks(2, chunking_version="v2")
    new = _chunks(3, chunking_version="v3")
    collection = Collection()
    collection.seed(old)
    monkeypatch.setattr(sync_hash_aware, "CHUNKING_CONTRACT_VERSION", "v3")

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


def test_unavailable_section_preserves_all_indexed_content(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir()
    old = _chunks(path="knowledge/note.md", content_hash="0" * 64)
    collection = Collection()
    collection.seed(old)

    stats = _sync_section_locked(collection, root, "knowledge")

    assert set(collection.rows) == {old[0]["id"]}
    assert stats["errors"] == 1
    assert stats["deleted_chunks"] == 0
    assert stats["removed_files"] == 0


def test_root_section_recurses_forces_metadata_and_reconciles_deletions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    nested = root / "arbitrary"
    nested.mkdir(parents=True)
    root_source = root / "root.md"
    nested_source = nested / "nested.md"
    root_source.write_text("root source", encoding="utf-8")
    nested_source.write_text("nested source", encoding="utf-8")
    collection = Collection()

    def chunk(path: Path) -> ChunkResult:
        rel_path = path.relative_to(root).as_posix()
        return ChunkResult(status="ok", chunks=_chunks(path=rel_path))

    monkeypatch.setitem(sync_hash_aware.CHUNKERS, ".md", chunk)

    first = _sync_section_locked(collection, root, ROOT_SECTION)

    assert first["published_files"] == 2
    assert first["errors"] == 0
    assert {
        row["metadata"]["section"] for row in collection.rows.values()
    } == {ROOT_SECTION}
    assert {
        row["metadata"]["path"] for row in collection.rows.values()
    } == {"root.md", "arbitrary/nested.md"}

    nested_source.unlink()
    second = _sync_section_locked(collection, root, ROOT_SECTION)

    assert second["removed_files"] == 1
    assert {
        row["metadata"]["path"] for row in collection.rows.values()
    } == {"root.md"}


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
    assert stats["empty_files"] == 0


def test_non_indexable_document_is_counted_apart_from_unchanged_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    (section / "note.md").write_text("", encoding="utf-8")
    collection = Collection()
    monkeypatch.setitem(
        sync_hash_aware.CHUNKERS,
        ".md",
        lambda _path: ChunkResult(status="empty"),
    )

    stats = _sync_section_locked(collection, root, "knowledge")

    assert stats["empty_files"] == 1
    assert stats["skipped_files"] == 1
    assert stats["removed_files"] == 0
    assert stats["errors"] == 0


def test_document_that_became_non_indexable_is_removed_and_still_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    (section / "note.md").write_text("", encoding="utf-8")
    collection = Collection()
    collection.seed(_chunks())
    monkeypatch.setitem(
        sync_hash_aware.CHUNKERS,
        ".md",
        lambda _path: ChunkResult(status="empty"),
    )

    stats = _sync_section_locked(collection, root, "knowledge")

    assert stats["empty_files"] == 1
    assert stats["removed_files"] == 1
    assert stats["skipped_files"] == 0
    assert collection.rows == {}


def test_lexical_failure_is_reported_after_chroma_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    source = section / "note.md"
    source.write_text("source present", encoding="utf-8")
    current = _chunks(content_hash="1" * 64)
    collection = Collection()

    class FailingLexical:
        def replace_file(self, _chunks: list[dict[str, Any]]) -> None:
            raise RuntimeError("sqlite failed")

        def delete_path(self, _path: str) -> None:
            return None

    monkeypatch.setitem(
        sync_hash_aware.CHUNKERS,
        ".md",
        lambda _path: ChunkResult(status="ok", chunks=current),
    )

    stats = _sync_section_locked(
        collection,
        root,
        "knowledge",
        lexical_index=FailingLexical(),  # type: ignore[arg-type]
    )

    assert stats["published_files"] == 1
    assert stats["errors"] == 1
    assert set(collection.rows) == {current[0]["id"]}


def _ingestion_document(
    source_uid: str,
    body: str,
    *,
    observed_at: datetime,
) -> CollectedDocument:
    path = f"sources/confluence-sync/CCSP/markdown/{source_uid}.md"
    page = RemotePage(
        page_id=source_uid,
        title=f"Document {source_uid}",
        space_key="CCSP",
        version_number=1,
        version_when=observed_at,
        last_updated=observed_at,
        author="Julien",
        occurred_at=observed_at,
        canonical_uri=f"https://confluence.example.test/pages/{source_uid}",
    )
    return CollectedDocument(
        source_uid=source_uid,
        path=path,
        content=render_document(
            page,
            path=path,
            body=f"# {source_uid}\n\n{body}\n",
            captured_at=observed_at,
        ),
        source_revision=f"revision-{observed_at.isoformat()}",
    )


def _publish_generation(
    storage: IngestionStorage,
    documents: tuple[CollectedDocument, ...],
    remote_seen: frozenset[str],
    *,
    observed_at: datetime,
) -> str:
    result = GenerationEngine(storage).run(
        GenerationAttempt(
            documents=documents,
            remote_seen_source_uids=remote_seen,
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=observed_at,
    )
    assert result.published
    assert result.generation_id is not None
    return result.generation_id


def test_generation_pointer_switch_cannot_publish_stale_document_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ingestion_root = tmp_path / "ingestion"
    storage = IngestionStorage(ingestion_root, "doc", retention_generations=3)
    generation_a = _publish_generation(
        storage,
        (
            _ingestion_document("shared", "Generation A content.", observed_at=_NOW),
            _ingestion_document("only-a", "Generation A only.", observed_at=_NOW),
        ),
        frozenset({"shared", "only-a"}),
        observed_at=_NOW,
    )
    next_observed_at = _NOW + timedelta(hours=1)
    generation_b = _publish_generation(
        storage,
        (
            _ingestion_document(
                "shared",
                "Generation B content.",
                observed_at=next_observed_at,
            ),
        ),
        frozenset({"shared"}),
        observed_at=next_observed_at,
    )
    generation_ids = iter((generation_a, generation_b))

    def current_generation_id(_storage: IngestionStorage) -> str:
        return next(generation_ids, generation_b)

    monkeypatch.setattr(IngestionStorage, "current_generation_id", current_generation_id)
    collection = Collection()

    stats = sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=3,
    )

    assert stats["published_files"] == 2
    assert stats["errors"] == 0
    assert {row["metadata"]["source_uid"] for row in collection.rows.values()} == {
        "shared",
        "only-a",
    }
    assert any("Generation A only." in row["document"] for row in collection.rows.values())


def test_incomplete_generation_with_missing_document_preserves_index(
    tmp_path: Path,
) -> None:
    ingestion_root = tmp_path / "ingestion"
    storage = IngestionStorage(ingestion_root, "doc", retention_generations=3)
    shared_document = _ingestion_document("shared", "Shared content.", observed_at=_NOW)
    missing_document = _ingestion_document("missing", "Missing content.", observed_at=_NOW)
    generation_id = _publish_generation(
        storage,
        (shared_document, missing_document),
        frozenset({"shared", "missing"}),
        observed_at=_NOW,
    )
    storage.document_path(generation_id, missing_document.path).unlink()
    collection = Collection()
    collection.seed(_chunks(path="knowledge/preserved.md"))
    rows_before = dict(collection.rows)

    stats = sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=3,
    )

    assert stats["errors"] == 1
    assert stats["published_files"] == 0
    assert collection.rows == rows_before
    assert collection.upsert_calls == 0
    assert collection.delete_calls == 0


def test_current_document_generation_reconciles_chroma_and_lexical(
    tmp_path: Path,
) -> None:
    ingestion_root = tmp_path / "ingestion"
    storage = IngestionStorage(ingestion_root, "doc", retention_generations=3)
    first_documents = (
        _ingestion_document("unchanged", "Stable shared filter token.", observed_at=_NOW),
        _ingestion_document("modified", "Original shared filter token.", observed_at=_NOW),
        _ingestion_document("removed", "Removed shared filter token.", observed_at=_NOW),
    )
    first_generation = _publish_generation(
        storage,
        first_documents,
        frozenset(document.source_uid for document in first_documents),
        observed_at=_NOW,
    )
    collection = Collection()
    lexical = LexicalIndex(tmp_path / "lexical.db")
    lexical.rebuild(collection)

    before = cortex_ingestion_index_freshness_report(
        collection,
        ingestion_root,
        retention_generations=3,
        include_entries=True,
    )
    first = sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=3,
        lexical_index=lexical,
    )
    second = sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=3,
        lexical_index=lexical,
    )

    assert before["status"] == "degraded"
    assert before["summary"] == {"unindexed": 3}
    assert first["published_files"] == 3
    assert first["errors"] == 0
    assert second["skipped_files"] == 3
    assert second["published_files"] == 0
    assert {row["metadata"]["source_kind"] for row in collection.rows.values()} == {"doc"}
    assert {row["metadata"]["section"] for row in collection.rows.values()} == {"sources"}
    assert all(
        row["metadata"]["canonical_uri"].startswith("https://confluence.example.test/pages/")
        for row in collection.rows.values()
    )
    assert {
        hit["metadata"]["source_kind"]
        for hit in lexical.search(
            "shared filter token",
            source_kinds=["doc"],
            limit=20,
        )
    } == {"doc"}

    next_observed_at = _NOW + timedelta(hours=1)
    next_documents = (
        _ingestion_document(
            "modified",
            "Updated shared filter token.",
            observed_at=next_observed_at,
        ),
        _ingestion_document(
            "added",
            "Added shared filter token.",
            observed_at=next_observed_at,
        ),
    )
    next_generation = _publish_generation(
        storage,
        next_documents,
        frozenset({"unchanged", "modified", "added"}),
        observed_at=next_observed_at,
    )
    switched = sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=3,
        lexical_index=lexical,
    )

    assert next_generation != first_generation
    assert switched == {
        "published_files": 2,
        "added_chunks": 2,
        "deleted_chunks": 2,
        "removed_files": 1,
        "skipped_files": 1,
        "empty_files": 0,
        "errors": 0,
    }
    expected_paths = {
        "sources/confluence-sync/CCSP/markdown/unchanged.md",
        "sources/confluence-sync/CCSP/markdown/modified.md",
        "sources/confluence-sync/CCSP/markdown/added.md",
    }
    assert {row["metadata"]["path"] for row in collection.rows.values()} == expected_paths
    assert {
        hit["path"]
        for hit in lexical.search(
            "shared filter token",
            source_kinds=["doc"],
            limit=20,
        )
    } == expected_paths
    after = cortex_ingestion_index_freshness_report(
        collection,
        ingestion_root,
        retention_generations=3,
        include_entries=True,
    )
    assert after["status"] == "ok"
    assert after["generation_id"] == next_generation
    assert after["summary"] == {"fresh": 3}


def test_pending_generation_and_absent_document_source_are_no_ops(
    tmp_path: Path,
) -> None:
    collection = Collection()
    absent = sync_ingestion_documents(
        collection,
        tmp_path / "absent",
        retention_generations=2,
    )
    assert absent == sync_hash_aware.empty_sync_stats()

    ingestion_root = tmp_path / "ingestion"
    storage = IngestionStorage(ingestion_root, "doc", retention_generations=2)
    current = _ingestion_document("current", "Current document body.", observed_at=_NOW)
    _publish_generation(
        storage,
        (current,),
        frozenset({"current"}),
        observed_at=_NOW,
    )
    first = sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=2,
    )
    pending_root = storage.create_pending_generation("pending-generation")
    pending_document = _ingestion_document(
        "pending",
        "Pending document body.",
        observed_at=_NOW + timedelta(hours=1),
    )
    pending_path = pending_root / "documents" / pending_document.path
    pending_path.parent.mkdir(parents=True)
    pending_path.write_bytes(pending_document.content)

    pending_run = sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=2,
    )

    assert first["published_files"] == 1
    assert pending_run["skipped_files"] == 1
    assert {row["metadata"]["source_uid"] for row in collection.rows.values()} == {"current"}


def test_vault_and_ingestion_reconciliation_do_not_purge_each_other(
    tmp_path: Path,
) -> None:
    ingestion_root = tmp_path / "ingestion"
    storage = IngestionStorage(ingestion_root, "doc", retention_generations=2)
    document = _ingestion_document("doc", "Document source body.", observed_at=_NOW)
    _publish_generation(
        storage,
        (document,),
        frozenset({"doc"}),
        observed_at=_NOW,
    )
    collection = Collection()
    sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=2,
    )

    vault_root = tmp_path / "vault"
    vault_source = vault_root / "sources" / "legacy.md"
    vault_source.parent.mkdir(parents=True)
    vault_source.write_text(
        "# Legacy\n\nLegacy note body long enough for indexing.\n",
        encoding="utf-8",
    )
    vault_stats = _sync_section_locked(collection, vault_root, "sources")
    document_stats = sync_ingestion_documents(
        collection,
        ingestion_root,
        retention_generations=2,
    )

    assert vault_stats["published_files"] == 1
    assert document_stats["skipped_files"] == 1
    assert {row["metadata"]["source_kind"] for row in collection.rows.values()} == {
        "doc",
        "note",
    }
