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
"""Failure-safe, hash-aware synchronization primitives."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chroma_client import iter_collection_pages
from chunker import chunk_markdown_file
from chunker_pdf import chunk_pdf_file
from chunker_utils import ChunkResult, is_excluded_path
from config import (
    CHUNKING_CONTRACT_VERSION,
    FRESHNESS_CONTRACT_ID,
    FRESHNESS_CONTRACT_VERSION,
    INGESTION_DOCUMENT_SECTION,
    INGESTION_DOCUMENT_SOURCE_KIND,
    INGESTION_DOCUMENT_SUFFIX,
    METADATA_SCHEMA_VERSION,
    ROOT_SECTION,
    VAULT_SOURCE_KIND,
)
from ingestion.constants import DOCUMENTS_DIRECTORY_NAME
from ingestion.storage import IngestionStorage, IngestionStorageError
from lexical_index import LexicalIndex
from sync_contract import SYNC_ERROR_SAMPLE_LIMIT, SyncError
from write_lock import chroma_write_lock

# Receives (files processed so far, files to process) for one ownership
# domain: a section, or the current ingestion generation. The counter
# restarts for each domain; the caller labels the phase.
ProgressCallback = Callable[[int, int], None]

_LOG = logging.getLogger("cortex.sync")
_UPSERT_BATCH_SIZE = 100
_DELETE_BATCH_SIZE = 500
_GET_BATCH_SIZE = 500
_PAGE_SIZE = 5_000

Chunker = Callable[[Path], ChunkResult]
CHUNKERS: dict[str, Chunker] = {
    ".md": chunk_markdown_file,
    ".pdf": chunk_pdf_file,
}


def _file_content_hash(metadata: dict[str, Any]) -> Any:
    return metadata.get("file_content_hash", metadata.get("content_hash"))


class SyncCheckpoint:
    """Durable, idempotent completion checkpoint keyed by POSIX source path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.completed = (
            set(json.loads(path.read_text(encoding="utf-8"))["completed"])
            if path.exists()
            else set()
        )

    def mark_completed(self, value: str) -> None:
        self.completed.add(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"completed": sorted(self.completed)}) + "\n",
            encoding="utf-8",
        )


def empty_sync_stats() -> dict[str, int]:
    """Return a fresh public synchronization counter set."""
    return {
        "published_files": 0,
        "added_chunks": 0,
        "deleted_chunks": 0,
        "removed_files": 0,
        "skipped_files": 0,
        "empty_files": 0,
        "errors": 0,
    }


def merge_sync_stats(target: dict[str, int], source: dict[str, int]) -> None:
    """Add one section's counters to an aggregate counter set."""
    for key in target:
        target[key] += source[key]


def _record_sync_error(
    errors: list[SyncError] | None,
    *,
    code: str,
    phase: str,
    path: str | None,
) -> None:
    """Append one ordered error sample without affecting exact counters."""
    if errors is not None and len(errors) < SYNC_ERROR_SAMPLE_LIMIT:
        errors.append(SyncError(code=code, phase=phase, path=path))


def _delete_ids(collection: Any, ids: set[str] | list[str]) -> int:
    ordered = sorted(ids)
    for start in range(0, len(ordered), _DELETE_BATCH_SIZE):
        collection.delete(ids=ordered[start : start + _DELETE_BATCH_SIZE])
    return len(ordered)


def _fetch_ids_and_metadata(
    collection: Any, ids: set[str]
) -> tuple[set[str], list[dict[str, Any]]]:
    found_ids: set[str] = set()
    found_metadata: list[dict[str, Any]] = []
    ordered = sorted(ids)
    for start in range(0, len(ordered), _GET_BATCH_SIZE):
        page = collection.get(
            ids=ordered[start : start + _GET_BATCH_SIZE],
            include=["metadatas"],
        )
        page_ids = page.get("ids", [])
        page_metadata = page.get("metadatas", []) or []
        found_ids.update(page_ids)
        found_metadata.extend(meta for meta in page_metadata if meta)
    return found_ids, found_metadata


def _validate_chunks(chunks: list[dict[str, Any]]) -> tuple[str, str, set[str]]:
    if not chunks:
        raise ValueError("cannot publish an empty chunk set")
    metadata = [chunk["metadata"] for chunk in chunks]
    paths = {item.get("path") for item in metadata}
    hashes = {_file_content_hash(item) for item in metadata}
    freshness_contracts = {item.get("contract_id") for item in metadata}
    freshness_versions = {
        item.get("content_hash_contract_version") for item in metadata
    }
    chunking_versions = {item.get("chunking_contract_version") for item in metadata}
    expected_counts = {item.get("expected_chunk_count") for item in metadata}
    metadata_versions = {item.get("schema_version") for item in metadata}
    expected_ids = {chunk["id"] for chunk in chunks}
    if len(expected_ids) != len(chunks):
        raise ValueError("new chunks contain duplicate IDs")
    if len(paths) != 1 or not isinstance(next(iter(paths)), str):
        raise ValueError("new chunks do not describe one source path")
    if len(hashes) != 1 or not isinstance(next(iter(hashes)), str):
        raise ValueError("new chunks do not describe one content hash")
    if freshness_contracts != {FRESHNESS_CONTRACT_ID}:
        raise ValueError("new chunks use an unexpected freshness contract")
    if freshness_versions != {FRESHNESS_CONTRACT_VERSION}:
        raise ValueError("new chunks use an unexpected freshness contract version")
    if chunking_versions != {CHUNKING_CONTRACT_VERSION}:
        raise ValueError("new chunks use an unexpected chunking contract version")
    if metadata_versions not in ({METADATA_SCHEMA_VERSION}, {None}):
        raise ValueError("new chunks use an unexpected metadata schema version")
    if expected_counts != {len(chunks)}:
        raise ValueError("new chunks contain an incoherent expected chunk count")
    return next(iter(paths)), next(iter(hashes)), expected_ids


def sync_file(
    collection: Any,
    chunks: list[dict[str, Any]],
    existing_ids_for_path: list[str],
) -> tuple[int, int]:
    """Publish, verify, then remove every ID outside the expected file version.

    Versioned IDs ensure that a failed batch cannot overwrite the previous
    complete version. A later retry upserts the complete expected set and then
    removes both superseded versions and any partial version left by a crash.
    """
    path, file_content_hash, expected_ids = _validate_chunks(chunks)
    for start in range(0, len(chunks), _UPSERT_BATCH_SIZE):
        batch = chunks[start : start + _UPSERT_BATCH_SIZE]
        collection.upsert(
            ids=[chunk["id"] for chunk in batch],
            documents=[chunk["text"] for chunk in batch],
            metadatas=[chunk["metadata"] for chunk in batch],
        )

    found_ids, found_metadata = _fetch_ids_and_metadata(collection, expected_ids)
    coherent_metadata = (
        len(found_metadata) == len(chunks)
        and all(meta.get("path") == path for meta in found_metadata)
        and all(_file_content_hash(meta) == file_content_hash for meta in found_metadata)
        and all(
            meta.get("chunking_contract_version") == CHUNKING_CONTRACT_VERSION
            for meta in found_metadata
        )
        and all(meta.get("expected_chunk_count") == len(chunks) for meta in found_metadata)
        and all(
            chunks[0]["metadata"].get("schema_version") is None
            or meta.get("schema_version") == METADATA_SCHEMA_VERSION
            for meta in found_metadata
        )
    )
    if found_ids != expected_ids or not coherent_metadata:
        raise RuntimeError(f"published file verification failed for {path}")

    obsolete_ids = set(existing_ids_for_path) - expected_ids
    deleted = _delete_ids(collection, obsolete_ids) if obsolete_ids else 0
    return len(chunks), deleted


def _existing_by_path(
    collection: Any,
    section: str,
    *,
    source_kind: str | None,
) -> dict[str, tuple[list[str], list[dict[str, Any]]]]:
    existing: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}
    for page in iter_collection_pages(
        collection,
        page_size=_PAGE_SIZE,
        where={"section": section},
        include=["metadatas"],
    ):
        ids = page.get("ids", [])
        metadata = page.get("metadatas", []) or []
        for chunk_id, meta in zip(ids, metadata):
            indexed_kind = meta.get("source_kind") if meta else None
            if source_kind is None:
                if indexed_kind not in {None, VAULT_SOURCE_KIND}:
                    continue
            elif indexed_kind != source_kind:
                continue
            if meta and isinstance(meta.get("path"), str):
                path = meta["path"].replace("\\", "/")
                old_ids, old_metadata = existing.setdefault(path, ([], []))
                old_ids.append(chunk_id)
                old_metadata.append(meta)
    return existing


def _is_complete_current_version(
    chunks: list[dict[str, Any]],
    old_ids: list[str],
    old_metadata: list[dict[str, Any]],
) -> bool:
    expected_ids = {chunk["id"] for chunk in chunks}
    if set(old_ids) != expected_ids or len(old_metadata) != len(chunks):
        return False
    content_hash = _file_content_hash(chunks[0]["metadata"])
    metadata_schema_version = chunks[0]["metadata"].get("schema_version")
    return all(
        _file_content_hash(meta) == content_hash
        and meta.get("chunking_contract_version") == CHUNKING_CONTRACT_VERSION
        and (
            metadata_schema_version is None
            or meta.get("schema_version") == metadata_schema_version
        )
        and meta.get("expected_chunk_count") == len(chunks)
        for meta in old_metadata
    )


def sync_section(
    collection: Any,
    root: Path,
    section: str,
    checkpoint: SyncCheckpoint | None = None,
    verbose: bool = False,
    lexical_index: LexicalIndex | None = None,
) -> dict[str, int]:
    """Reconcile one section under the exclusive Chroma write lock."""
    return sync_section_report(
        collection,
        root,
        section,
        checkpoint=checkpoint,
        verbose=verbose,
        lexical_index=lexical_index,
        errors=[],
    )


def sync_section_report(
    collection: Any,
    root: Path,
    section: str,
    checkpoint: SyncCheckpoint | None = None,
    verbose: bool = False,
    lexical_index: LexicalIndex | None = None,
    *,
    errors: list[SyncError],
    progress: ProgressCallback | None = None,
) -> dict[str, int]:
    """Reconcile one section and append structured error samples."""
    with chroma_write_lock():
        return _sync_section_locked(
            collection,
            root,
            section,
            checkpoint=checkpoint,
            verbose=verbose,
            lexical_index=lexical_index,
            errors=errors,
            progress=progress,
        )


def sync_ingestion_documents(
    collection: Any,
    ingestion_root: Path,
    *,
    retention_generations: int,
    checkpoint: SyncCheckpoint | None = None,
    verbose: bool = False,
    lexical_index: LexicalIndex | None = None,
) -> dict[str, int]:
    """Reconcile the current published document generation into both indexes."""
    return sync_ingestion_documents_report(
        collection,
        ingestion_root,
        retention_generations=retention_generations,
        checkpoint=checkpoint,
        verbose=verbose,
        lexical_index=lexical_index,
    )[0]


def sync_ingestion_documents_report(
    collection: Any,
    ingestion_root: Path,
    *,
    retention_generations: int,
    checkpoint: SyncCheckpoint | None = None,
    verbose: bool = False,
    lexical_index: LexicalIndex | None = None,
    errors: list[SyncError] | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[dict[str, int], str | None]:
    """Reconcile ingestion documents and return counters plus selected generation."""
    error_samples = [] if errors is None else errors
    with chroma_write_lock():
        return _sync_ingestion_documents_locked_report(
            collection,
            ingestion_root,
            retention_generations=retention_generations,
            checkpoint=checkpoint,
            verbose=verbose,
            lexical_index=lexical_index,
            errors=error_samples,
            progress=progress,
        )


def _sync_ingestion_documents_locked(
    collection: Any,
    ingestion_root: Path,
    *,
    retention_generations: int,
    checkpoint: SyncCheckpoint | None = None,
    verbose: bool = False,
    lexical_index: LexicalIndex | None = None,
) -> dict[str, int]:
    """Resolve only the current pointer and fail closed on invalid published state."""
    return _sync_ingestion_documents_locked_report(
        collection,
        ingestion_root,
        retention_generations=retention_generations,
        checkpoint=checkpoint,
        verbose=verbose,
        lexical_index=lexical_index,
        errors=[],
    )[0]


def _sync_ingestion_documents_locked_report(
    collection: Any,
    ingestion_root: Path,
    *,
    retention_generations: int,
    checkpoint: SyncCheckpoint | None = None,
    verbose: bool = False,
    lexical_index: LexicalIndex | None = None,
    errors: list[SyncError],
    progress: ProgressCallback | None = None,
) -> tuple[dict[str, int], str | None]:
    """Resolve one immutable generation and append structured error samples."""
    stats = empty_sync_stats()
    storage = IngestionStorage(
        ingestion_root,
        INGESTION_DOCUMENT_SOURCE_KIND,
        retention_generations,
    )
    if not storage.source_root.exists():
        return stats, None
    try:
        generation_id = storage.current_generation_id()
        if generation_id is None:
            return stats, None
        manifest = storage.load_manifest(generation_id)
    except IngestionStorageError:
        stats["errors"] += 1
        _LOG.exception(
            "ingestion_generation_unavailable source_kind=%s; preserving indexed content",
            INGESTION_DOCUMENT_SOURCE_KIND,
        )
        _record_sync_error(
            errors,
            code="inconsistent_generation",
            phase="resolve_generation",
            path=str(storage.source_root),
        )
        return stats, None

    documents_root = storage.generation_path(generation_id) / DOCUMENTS_DIRECTORY_NAME
    if not documents_root.is_dir():
        stats["errors"] += 1
        _LOG.error(
            "ingestion_documents_unavailable source_kind=%s generation_id=%s path=%s; "
            "preserving indexed content",
            INGESTION_DOCUMENT_SOURCE_KIND,
            generation_id,
            documents_root,
        )
        _record_sync_error(
            errors,
            code="inconsistent_generation",
            phase="resolve_generation",
            path=str(documents_root),
        )
        return stats, None

    expected_paths = {document.path for document in manifest.documents}
    files = sorted(
        path
        for path in documents_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() == INGESTION_DOCUMENT_SUFFIX
        and path.relative_to(documents_root).as_posix() in expected_paths
    )
    discovered_paths = {path.relative_to(documents_root).as_posix() for path in files}
    missing_paths = expected_paths - discovered_paths
    if missing_paths:
        stats["errors"] += 1
        _LOG.error(
            "ingestion_generation_incomplete source_kind=%s generation_id=%s "
            "missing_documents=%d; preserving indexed content",
            INGESTION_DOCUMENT_SOURCE_KIND,
            generation_id,
            len(missing_paths),
        )
        _record_sync_error(
            errors,
            code="inconsistent_generation",
            phase="resolve_generation",
            path=sorted(missing_paths)[0],
        )
        return stats, None

    return (
        _sync_files_locked(
            collection,
            root=documents_root,
            section=INGESTION_DOCUMENT_SECTION,
            files=files,
            source_kind=INGESTION_DOCUMENT_SOURCE_KIND,
            checkpoint=checkpoint,
            verbose=verbose,
            lexical_index=lexical_index,
            rebase_chunks=True,
            apply_exclusions=False,
            generation_id=generation_id,
            errors=errors,
            progress=progress,
        ),
        generation_id,
    )


def _sync_section_locked(
    collection: Any,
    root: Path,
    section: str,
    checkpoint: SyncCheckpoint | None = None,
    verbose: bool = False,
    lexical_index: LexicalIndex | None = None,
    errors: list[SyncError] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, int]:
    """Reconcile live, excluded and removed paths for one section."""
    stats = empty_sync_stats()
    section_root = root if section == ROOT_SECTION else root / section
    if not section_root.is_dir():
        stats["errors"] += 1
        _LOG.error(
            "section_unavailable section=%s path=%s; preserving indexed content",
            section,
            section_root,
        )
        _record_sync_error(
            errors,
            code="section_unavailable",
            phase="validate",
            path=str(section_root),
        )
        return stats

    files = sorted(
        path
        for path in section_root.rglob("*")
        if path.is_file() and path.suffix.lower() in CHUNKERS
    )
    return _sync_files_locked(
        collection,
        root=root,
        section=section,
        files=files,
        source_kind=None,
        checkpoint=checkpoint,
        verbose=verbose,
        lexical_index=lexical_index,
        rebase_chunks=False,
        apply_exclusions=True,
        errors=errors,
        progress=progress,
    )


def _rebase_chunks(
    chunks: list[dict[str, Any]],
    *,
    rel_path: str,
    section: str,
) -> None:
    """Rebase chunk identity from the vault root to an ingestion documents root."""
    for chunk in chunks:
        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("ingestion chunk metadata is invalid")
        if metadata.get("source_kind") != INGESTION_DOCUMENT_SOURCE_KIND:
            raise ValueError("ingestion document does not declare source_kind=doc")
        chunk_index = metadata.get("chunk_index")
        file_content_hash = metadata.get("file_content_hash")
        if not isinstance(chunk_index, int) or not isinstance(file_content_hash, str):
            raise ValueError("ingestion chunk identity metadata is invalid")
        metadata["path"] = rel_path
        metadata["section"] = section
        chunk["id"] = (
            f"{rel_path}::{file_content_hash}::{CHUNKING_CONTRACT_VERSION}::{chunk_index}"
        )


def _sync_files_locked(
    collection: Any,
    *,
    root: Path,
    section: str,
    files: list[Path],
    source_kind: str | None,
    checkpoint: SyncCheckpoint | None,
    verbose: bool,
    lexical_index: LexicalIndex | None,
    rebase_chunks: bool,
    apply_exclusions: bool,
    generation_id: str | None = None,
    errors: list[SyncError] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, int]:
    """Reconcile an explicit immutable file set for one ownership domain."""
    stats = empty_sync_stats()
    existing = _existing_by_path(
        collection,
        section,
        source_kind=source_kind,
    )
    eligible_paths: set[str] = set()

    if verbose:
        _LOG.info(
            "section_scan section=%s files=%d indexed_paths=%d generation_id=%s",
            section,
            len(files),
            len(existing),
            generation_id,
        )

    total_files = len(files)
    for index, path in enumerate(files, 1):
        if progress is not None:
            progress(index - 1, total_files)
        rel_path = path.relative_to(root).as_posix()
        if apply_exclusions and is_excluded_path(path.relative_to(root)):
            continue
        eligible_paths.add(rel_path)
        result = CHUNKERS[path.suffix.lower()](path)
        if result.status == "ok":
            try:
                if rebase_chunks:
                    _rebase_chunks(
                        result.chunks,
                        rel_path=rel_path,
                        section=section,
                    )
                else:
                    for chunk in result.chunks:
                        metadata = chunk.get("metadata")
                        if isinstance(metadata, dict):
                            metadata["section"] = section
            except ValueError as exc:
                result = ChunkResult(status="extraction_error", error=str(exc))
        old_ids, old_metadata = existing.get(rel_path, ([], []))

        if result.status == "ok":
            if _is_complete_current_version(result.chunks, old_ids, old_metadata):
                stats["skipped_files"] += 1
                continue
            try:
                added, deleted = sync_file(collection, result.chunks, old_ids)
            except Exception:  # noqa: BLE001 -- preserve the old version on any backend failure.
                stats["errors"] += 1
                _LOG.exception("file_publish_error path=%s", rel_path)
                _record_sync_error(
                    errors,
                    code="chroma_publication_failed",
                    phase="publish_chroma",
                    path=rel_path,
                )
                continue
            stats["published_files"] += 1
            stats["added_chunks"] += added
            stats["deleted_chunks"] += deleted
            if lexical_index is not None:
                try:
                    lexical_index.replace_file(result.chunks)
                except Exception:  # noqa: BLE001 -- Chroma remains authoritative.
                    stats["errors"] += 1
                    _LOG.exception("lexical_publish_error path=%s", rel_path)
                    _record_sync_error(
                        errors,
                        code="lexical_publication_failed",
                        phase="publish_lexical",
                        path=rel_path,
                    )
                    continue
            if checkpoint:
                checkpoint.mark_completed(rel_path)
            continue

        if result.status in {"empty", "too_large"}:
            stats["empty_files"] += 1
            _LOG.info(
                "file_not_indexable path=%s reason=%s", rel_path, result.status
            )
            if old_ids:
                try:
                    stats["deleted_chunks"] += _delete_ids(collection, old_ids)
                except Exception:  # noqa: BLE001 -- reconciliation errors are isolated per file.
                    stats["errors"] += 1
                    _LOG.exception(
                        "file_remove_error path=%s reason=%s", rel_path, result.status
                    )
                    _record_sync_error(
                        errors,
                        code="chroma_publication_failed",
                        phase="publish_chroma",
                        path=rel_path,
                    )
                    continue
                stats["removed_files"] += 1
                _LOG.info(
                    "file_removed path=%s removed_reason=%s", rel_path, result.status
                )
                if lexical_index is not None:
                    try:
                        lexical_index.delete_path(rel_path)
                    except Exception:  # noqa: BLE001 -- Chroma remains authoritative.
                        stats["errors"] += 1
                        _LOG.exception("lexical_remove_error path=%s", rel_path)
                        _record_sync_error(
                            errors,
                            code="lexical_publication_failed",
                            phase="publish_lexical",
                            path=rel_path,
                        )
                        continue
            else:
                stats["skipped_files"] += 1
            if checkpoint:
                checkpoint.mark_completed(f"removed:{result.status}:{rel_path}")
            continue

        stats["errors"] += 1
        _LOG.error(
            "file_chunk_error path=%s status=%s reason=%s",
            rel_path,
            result.status,
            result.error or "unknown",
        )
        _record_sync_error(
            errors,
            code="extraction_failed",
            phase="extract",
            path=rel_path,
        )

    if progress is not None:
        progress(total_files, total_files)

    for rel_path in sorted(set(existing) - eligible_paths):
        old_ids, _ = existing[rel_path]
        try:
            stats["deleted_chunks"] += _delete_ids(collection, old_ids)
        except Exception:  # noqa: BLE001 -- reconciliation errors are isolated per file.
            stats["errors"] += 1
            _LOG.exception("file_reconcile_remove_error path=%s", rel_path)
            _record_sync_error(
                errors,
                code="chroma_publication_failed",
                phase="publish_chroma",
                path=rel_path,
            )
            continue
        stats["removed_files"] += 1
        _LOG.info("file_removed path=%s removed_reason=absent_or_excluded", rel_path)
        if lexical_index is not None:
            try:
                lexical_index.delete_path(rel_path)
            except Exception:  # noqa: BLE001 -- Chroma remains authoritative.
                stats["errors"] += 1
                _LOG.exception("lexical_reconcile_remove_error path=%s", rel_path)
                _record_sync_error(
                    errors,
                    code="lexical_publication_failed",
                    phase="publish_lexical",
                    path=rel_path,
                )
                continue
        if checkpoint:
            checkpoint.mark_completed(f"removed:absent_or_excluded:{rel_path}")

    return stats
