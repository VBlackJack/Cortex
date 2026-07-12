# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
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
)
from lexical_index import LexicalIndex
from write_lock import chroma_write_lock

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
        "errors": 0,
    }


def merge_sync_stats(target: dict[str, int], source: dict[str, int]) -> None:
    """Add one section's counters to an aggregate counter set."""
    for key in target:
        target[key] += source[key]


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
    hashes = {item.get("content_hash") for item in metadata}
    freshness_contracts = {item.get("contract_id") for item in metadata}
    freshness_versions = {
        item.get("content_hash_contract_version") for item in metadata
    }
    chunking_versions = {item.get("chunking_contract_version") for item in metadata}
    expected_counts = {item.get("expected_chunk_count") for item in metadata}
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
    path, content_hash, expected_ids = _validate_chunks(chunks)
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
        and all(meta.get("content_hash") == content_hash for meta in found_metadata)
        and all(
            meta.get("chunking_contract_version") == CHUNKING_CONTRACT_VERSION
            for meta in found_metadata
        )
        and all(meta.get("expected_chunk_count") == len(chunks) for meta in found_metadata)
    )
    if found_ids != expected_ids or not coherent_metadata:
        raise RuntimeError(f"published file verification failed for {path}")

    obsolete_ids = set(existing_ids_for_path) - expected_ids
    deleted = _delete_ids(collection, obsolete_ids) if obsolete_ids else 0
    return len(chunks), deleted


def _existing_by_path(
    collection: Any, section: str
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
    content_hash = chunks[0]["metadata"]["content_hash"]
    return all(
        meta.get("content_hash") == content_hash
        and meta.get("chunking_contract_version") == CHUNKING_CONTRACT_VERSION
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
    with chroma_write_lock():
        return _sync_section_locked(
            collection,
            root,
            section,
            checkpoint=checkpoint,
            verbose=verbose,
            lexical_index=lexical_index,
        )


def _sync_section_locked(
    collection: Any,
    root: Path,
    section: str,
    checkpoint: SyncCheckpoint | None = None,
    verbose: bool = False,
    lexical_index: LexicalIndex | None = None,
) -> dict[str, int]:
    """Reconcile live, excluded and removed paths for one section."""
    stats = empty_sync_stats()
    section_root = root / section
    if not section_root.is_dir():
        stats["errors"] += 1
        _LOG.error(
            "section_unavailable section=%s path=%s; preserving indexed content",
            section,
            section_root,
        )
        return stats

    existing = _existing_by_path(collection, section)
    files = sorted(
        path
        for path in section_root.rglob("*")
        if path.is_file() and path.suffix.lower() in CHUNKERS
    )
    eligible_paths: set[str] = set()

    if verbose:
        _LOG.info(
            "section_scan section=%s files=%d indexed_paths=%d",
            section,
            len(files),
            len(existing),
        )

    for path in files:
        rel_path = path.relative_to(root).as_posix()
        if is_excluded_path(path.relative_to(root)):
            continue
        eligible_paths.add(rel_path)
        result = CHUNKERS[path.suffix.lower()](path)
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
                    continue
            if checkpoint:
                checkpoint.mark_completed(rel_path)
            continue

        if result.status in {"empty", "too_large"}:
            if old_ids:
                try:
                    stats["deleted_chunks"] += _delete_ids(collection, old_ids)
                except Exception:  # noqa: BLE001 -- reconciliation errors are isolated per file.
                    stats["errors"] += 1
                    _LOG.exception(
                        "file_remove_error path=%s reason=%s", rel_path, result.status
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

    for rel_path in sorted(set(existing) - eligible_paths):
        old_ids, _ = existing[rel_path]
        try:
            stats["deleted_chunks"] += _delete_ids(collection, old_ids)
        except Exception:  # noqa: BLE001 -- reconciliation errors are isolated per file.
            stats["errors"] += 1
            _LOG.exception("file_reconcile_remove_error path=%s", rel_path)
            continue
        stats["removed_files"] += 1
        _LOG.info("file_removed path=%s removed_reason=absent_or_excluded", rel_path)
        if lexical_index is not None:
            try:
                lexical_index.delete_path(rel_path)
            except Exception:  # noqa: BLE001 -- Chroma remains authoritative.
                stats["errors"] += 1
                _LOG.exception("lexical_reconcile_remove_error path=%s", rel_path)
                continue
        if checkpoint:
            checkpoint.mark_completed(f"removed:absent_or_excluded:{rel_path}")

    return stats
