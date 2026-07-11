# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Resumable per-file SHA-256 sync primitives for B2."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from config import FRESHNESS_CONTRACT_ID, FRESHNESS_CONTRACT_VERSION
from chunker import chunk_markdown_file
from chunker_utils import is_excluded_path
from write_lock import chroma_write_lock


class SyncCheckpoint:
    """Durable, idempotent completion checkpoint keyed by POSIX source path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.completed = set(json.loads(path.read_text())["completed"]) if path.exists() else set()

    def mark_completed(self, rel_path: str) -> None:
        self.completed.add(rel_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"completed": sorted(self.completed)}) + "\n")


def sync_file(collection: Any, chunks: list[dict[str, Any]], old_ids: list[str]) -> None:
    """Publish one coherent file version before removing superseded chunk IDs."""
    if not chunks:
        raise ValueError("cannot publish an empty chunk set")
    metadata = [chunk["metadata"] for chunk in chunks]
    hashes = {item.get("content_hash") for item in metadata}
    contracts = {item.get("contract_id") for item in metadata}
    versions = {item.get("content_hash_contract_version") for item in metadata}
    if len(hashes) != 1 or contracts != {FRESHNESS_CONTRACT_ID} or versions != {FRESHNESS_CONTRACT_VERSION}:
        raise ValueError("new chunks do not describe one coherent freshness version")
    for start in range(0, len(chunks), 100):
        batch = chunks[start : start + 100]
        collection.upsert(ids=[chunk["id"] for chunk in batch], documents=[chunk["text"] for chunk in batch], metadatas=[chunk["metadata"] for chunk in batch])
    obsolete = sorted(set(old_ids).difference(chunk["id"] for chunk in chunks))
    if obsolete:
        collection.delete(ids=obsolete)


def _trace(verbose: bool, message: str) -> None:
    if verbose:
        print(message, file=sys.stderr, flush=True)


def sync_section(
    collection: Any, root: Path, section: str, checkpoint: SyncCheckpoint, verbose: bool = False
) -> dict[str, int]:
    """Synchronize one section by re-reading each source before every decision.

    Acquires the exclusive Chroma write lock for the whole call - see
    write_lock.chroma_write_lock(). Reentrant: a caller that already holds
    the lock (e.g. scripts/b2_sync_vault.py wrapping a multi-section run)
    nests safely instead of deadlocking. Raises CortexWriteLockedError,
    without writing anything, if a different process holds it.
    """
    with chroma_write_lock():
        return _sync_section_locked(collection, root, section, checkpoint, verbose)


def _sync_section_locked(
    collection: Any, root: Path, section: str, checkpoint: SyncCheckpoint, verbose: bool = False
) -> dict[str, int]:
    existing: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}
    offset = 0
    _trace(verbose, f"[{section}] fetching existing chunk metadata...")
    while True:
        page = collection.get(where={"section": section}, include=["metadatas"], limit=5_000, offset=offset)
        ids, metas = page.get("ids", []), page.get("metadatas", []) or []
        for chunk_id, meta in zip(ids, metas):
            if meta and isinstance(meta.get("path"), str):
                old_ids, old_metas = existing.setdefault(meta["path"].replace("\\", "/"), ([], []))
                old_ids.append(chunk_id)
                old_metas.append(meta)
        _trace(verbose, f"[{section}] existing fetch: offset={offset} rows={len(ids)}")
        if len(ids) < 5_000:
            break
        offset += 5_000
    _trace(verbose, f"[{section}] existing fetch done: {len(existing)} paths")
    stats = {"published": 0, "skipped": 0}
    files = sorted((root / section).rglob("*.md"))
    _trace(verbose, f"[{section}] {len(files)} files on disk")
    for index, path in enumerate(files, start=1):
        if is_excluded_path(path.relative_to(root)):
            continue
        _trace(verbose, f"[{section}] ({index}/{len(files)}) chunking {path.name}")
        chunks = chunk_markdown_file(path)
        if not chunks:
            checkpoint.mark_completed(f"no-chunks:{path.relative_to(root).as_posix()}")
            continue
        rel_path = chunks[0]["metadata"]["path"]
        old_ids, old_metas = existing.get(rel_path, ([], []))
        hashes = {meta.get("content_hash") for meta in old_metas}
        if len(hashes) == 1 and hashes == {chunks[0]["metadata"]["content_hash"]}:
            stats["skipped"] += 1
            continue
        _trace(verbose, f"[{section}] ({index}/{len(files)}) publishing {len(chunks)} chunks for {path.name}")
        sync_file(collection, chunks, old_ids)
        checkpoint.mark_completed(rel_path)
        stats["published"] += 1
        _trace(verbose, f"[{section}] ({index}/{len(files)}) done {path.name}")
    return stats
