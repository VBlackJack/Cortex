# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
chunker_utils.py - Shared utilities for markdown and PDF chunkers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from config import EXCLUDE_FILES, EXCLUDED_DIRS, INCLUDED_SECTIONS

ChunkStatus = Literal[
    "ok",
    "empty",
    "too_large",
    "read_error",
    "extraction_error",
]


@dataclass(frozen=True)
class ChunkResult:
    """Typed outcome of reading and chunking one source snapshot."""

    status: ChunkStatus
    chunks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def is_excluded_path(rel_path: Path) -> bool:
    """True if any parent directory of rel_path is structurally excluded
    (config.EXCLUDED_DIRS, or a dotfile dir), or the filename itself is."""
    if rel_path.name in EXCLUDE_FILES:
        return True
    return any(
        part in EXCLUDED_DIRS or part.startswith(".")
        for part in rel_path.parts[:-1]
    )


def discover_out_of_policy_dirs(kb_root: Path) -> list[str]:
    """Live top-level dirs neither in INCLUDED_SECTIONS nor structurally
    excluded - present on disk but requiring an explicit policy decision
    before they are ever synced. Never auto-indexed; surfaced so a real gap
    (a genuinely new section) is never silent."""
    if not kb_root.is_dir():
        return []
    result = []
    for folder in sorted(kb_root.iterdir()):
        if not folder.is_dir() or folder.name in INCLUDED_SECTIONS:
            continue
        if is_excluded_path(Path(folder.name) / "_probe"):
            continue
        result.append(folder.name)
    return result


def compute_hash(content: str) -> str:
    """MD5 hash of file content for change detection."""
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact input bytes."""
    return hashlib.sha256(data).hexdigest()


def get_section(file_path: Path, kb_path: str) -> str:
    """Extract top-level section from file path relative to KB_PATH."""
    try:
        rel = file_path.relative_to(kb_path)
        return rel.parts[0] if rel.parts else "Unknown"
    except ValueError:
        return "Unknown"


def get_relative_path(file_path: Path, kb_path: str) -> str:
    """Return file path relative to KB_PATH, or absolute path as fallback."""
    try:
        return file_path.relative_to(kb_path).as_posix()
    except ValueError:
        return str(file_path)


def split_fixed_size_spans(
    text: str, max_chars: int, overlap_chars: int
) -> list[tuple[int, int]]:
    """Return lossless chunk spans with bounded late-boundary backoff."""
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must not be negative")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")
    if not text:
        return []

    spans: list[tuple[int, int]] = []
    start = 0
    text_len = len(text)
    minimum_advance = max(1, max_chars - (2 * overlap_chars))

    while start < text_len:
        end = min(start + max_chars, text_len)

        if end < text_len:
            boundary_floor = start + max_chars - overlap_chars
            split_pos = text.rfind("\n", boundary_floor, end)
            if split_pos < boundary_floor:
                split_pos = text.rfind(". ", boundary_floor, end)
            if split_pos >= boundary_floor:
                end = split_pos + 1

        spans.append((start, end))

        if end >= text_len:
            break

        next_start = end - overlap_chars
        if next_start - start < minimum_advance:
            next_start = start + minimum_advance
        start = next_start

    return spans


def split_fixed_size(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split text with overlap while preserving lossless source spans."""
    chunks: list[str] = []
    for start, end in split_fixed_size_spans(text, max_chars, overlap_chars):
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
    return chunks
