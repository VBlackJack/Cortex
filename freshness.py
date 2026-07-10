# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Read-only source freshness reporting for the Cortex index."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from config import (
    EXCLUDE_DIRS,
    EXCLUDE_FILES,
    FRESHNESS_CONTRACT_ID,
    FRESHNESS_CONTRACT_VERSION,
    FRESHNESS_EXCLUDED_DIRS,
    KB_PATH,
)
from chunker_utils import sha256_bytes

_LOG = logging.getLogger("cortex.freshness")
_HASH_LENGTH = 64


@dataclass(frozen=True)
class FileSnapshot:
    """One exact, strict binary read of an eligible Markdown source."""

    path: str
    content_hash: str


def read_markdown_snapshot(path: Path, kb_root: Path) -> FileSnapshot:
    """Read, contain, hash and strictly decode a Markdown file exactly once."""
    root = kb_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        rel_path = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("source path escapes KB_PATH") from exc
    raw = resolved.read_bytes()
    raw.decode("utf-8", errors="strict")
    return FileSnapshot(path=rel_path.as_posix(), content_hash=sha256_bytes(raw))


def cortex_freshness_report(
    collection: Any, section: str | None = None
) -> dict[str, Any]:
    """Compare live sources with index metadata without writing either system."""
    started = perf_counter()
    root = Path(KB_PATH)
    indexed, invalid_paths = _indexed_metadata(collection, section)
    entries: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    for path, reason in invalid_paths.items():
        entries.append({"path": path, "status": "error", "reason": reason})

    if not root.is_dir():
        return _report(entries, started, scope_error="KB_PATH is not a directory")

    for excluded in _discover_excluded(root, section):
        rel_path = excluded.relative_to(root).as_posix()
        seen_paths.add(rel_path)
        entries.append({"path": rel_path, "status": "excluded"})

    for source in _discover_sources(root, section):
        if source.suffix.lower() == ".pdf":
            entries.append(
                {"path": source.relative_to(root).as_posix(), "status": "unsupported"}
            )
            continue
        rel_path = source.relative_to(root).as_posix()
        seen_paths.add(rel_path)
        try:
            snapshot = read_markdown_snapshot(source, root)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            entries.append({"path": rel_path, "status": "error", "reason": str(exc)})
            continue
        entries.append(_classify_present(snapshot, indexed.pop(rel_path, [])))

    for rel_path, metadata in sorted(indexed.items()):
        if rel_path in seen_paths:
            continue
        status = "unsupported" if rel_path.lower().endswith(".pdf") else "missing"
        if _is_excluded(Path(rel_path)):
            status = "excluded"
        entries.append(
            {"path": rel_path, "status": status, "chunks": str(len(metadata))}
        )

    return _report(entries, started)


def _discover_sources(root: Path, section: str | None) -> list[Path]:
    base = root / section if section else root
    if not base.is_dir():
        return []
    paths: list[Path] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".pdf"}:
            continue
        rel = path.relative_to(root)
        if _is_excluded(rel) or path.name in EXCLUDE_FILES:
            continue
        paths.append(path)
    return paths


def _discover_excluded(root: Path, section: str | None) -> list[Path]:
    base = root / section if section else root
    if not base.is_dir():
        return []
    return [
        path
        for path in sorted(base.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in {".md", ".pdf"}
        and (_is_excluded(path.relative_to(root)) or path.name in EXCLUDE_FILES)
    ]


def _is_excluded(rel_path: Path) -> bool:
    return any(
        part in EXCLUDE_DIRS or part in FRESHNESS_EXCLUDED_DIRS or part.startswith(".")
        for part in rel_path.parts[:-1]
    )


def _indexed_metadata(
    collection: Any, section: str | None
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    indexed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid: dict[str, str] = {}
    offset = 0
    page_size = 5_000
    while True:
        result = collection.get(
            where={"section": section} if section else None,
            include=["metadatas"],
            limit=page_size,
            offset=offset,
        )
        metadatas = result.get("metadatas") or []
        if not metadatas:
            break
        for metadata in metadatas:
            if not metadata:
                continue
            raw_path = metadata.get("path")
            normalized = _normalize_index_path(raw_path)
            if normalized is None:
                invalid[str(raw_path)] = "untrusted indexed path"
                continue
            indexed[normalized].append(dict(metadata))
        if len(metadatas) < page_size:
            break
        offset += page_size
    return indexed, invalid


def _normalize_index_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def _classify_present(
    snapshot: FileSnapshot, metadata: list[dict[str, Any]]
) -> dict[str, str]:
    if not metadata:
        return {"path": snapshot.path, "status": "unindexed"}
    hashes = {item.get("content_hash") for item in metadata}
    contracts = {item.get("contract_id") for item in metadata}
    versions = {item.get("content_hash_contract_version") for item in metadata}
    valid_hashes = {
        value
        for value in hashes
        if isinstance(value, str) and len(value) == _HASH_LENGTH
    }
    coherent = (
        len(hashes) == 1
        and len(valid_hashes) == 1
        and contracts == {FRESHNESS_CONTRACT_ID}
        and versions == {FRESHNESS_CONTRACT_VERSION}
    )
    if not coherent:
        return {
            "path": snapshot.path,
            "status": "unknown",
            "chunks": str(len(metadata)),
        }
    stored_hash = next(iter(valid_hashes))
    return {
        "path": snapshot.path,
        "status": "fresh" if stored_hash == snapshot.content_hash else "stale",
        "chunks": str(len(metadata)),
    }


def _report(
    entries: list[dict[str, str]], started: float, scope_error: str | None = None
) -> dict[str, Any]:
    entries.sort(key=lambda item: item["path"])
    summary: dict[str, int] = defaultdict(int)
    for entry in entries:
        summary[entry["status"]] += 1
    report: dict[str, Any] = {
        "contract_id": FRESHNESS_CONTRACT_ID,
        "read_only": True,
        "freshness_is_not_completeness": True,
        "scope": {
            "excluded_dirs": sorted(FRESHNESS_EXCLUDED_DIRS),
            "cortex_extra_excluded_dirs": sorted(EXCLUDE_DIRS),
            "pdf": "unsupported_by_contract_v1",
        },
        "summary": dict(sorted(summary.items())),
        "entries": entries,
        "duration_ms": round((perf_counter() - started) * 1000, 3),
    }
    if scope_error:
        report["error"] = scope_error
    _LOG.info(
        "freshness_report section_entries=%d summary=%s",
        len(entries),
        report["summary"],
    )
    return report
