# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
chunker_utils.py - Shared utilities for markdown and PDF chunkers.
"""

import hashlib
from pathlib import Path


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


def split_fixed_size(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """
    Split text into fixed-size chunks with overlap.
    Tries to break on natural boundaries (newline > sentence > hard cut).
    Guarantees termination: start always advances by at least 1 char.
    """
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + max_chars, text_len)

        # Try to break on a natural boundary near the end of the window
        if end < text_len:
            split_pos = text.rfind("\n", start, end)
            if split_pos == -1 or split_pos <= start:
                split_pos = text.rfind(". ", start, end)
            if split_pos != -1 and split_pos > start:
                end = split_pos + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # If we've reached the end, stop
        if end >= text_len:
            break

        # Advance start — guarantee progress even if overlap is large
        next_start = end - overlap_chars
        if next_start <= start:
            next_start = start + 1  # always move forward
        start = next_start

    return chunks
