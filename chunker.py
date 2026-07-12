# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Cortex — Markdown Chunker
Splits .md files into semantically meaningful chunks with metadata.
"""

import re
from pathlib import Path

from chunker_utils import (
    ChunkResult,
    compute_hash,
    get_relative_path,
    get_section,
    sha256_bytes,
    split_fixed_size,
)
from config import (
    CHUNK_MIN_CHARS,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CHUNKING_CONTRACT_VERSION,
    FRESHNESS_CONTRACT_ID,
    FRESHNESS_CONTRACT_VERSION,
    KB_PATH,
    MAX_MARKDOWN_FILE_SIZE_BYTES,
    require_kb_path,
)

MAX_CHARS = CHUNK_SIZE
OVERLAP_CHARS = CHUNK_OVERLAP

# Skip files larger than this (bytes) — avoids loading huge index pages
MAX_FILE_SIZE_BYTES = MAX_MARKDOWN_FILE_SIZE_BYTES


# Keep private aliases so existing tests can import them
_compute_hash = compute_hash
_split_fixed_size = split_fixed_size


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """
    Extract YAML frontmatter from markdown content.
    Returns (metadata_dict, remaining_content).
    """
    metadata: dict[str, str] = {}
    if not content.startswith("---"):
        return metadata, content

    end = content.find("\n---", 3)
    if end == -1:
        return metadata, content

    frontmatter = content[3:end].strip()
    body = content[end + 4 :].lstrip("\n")

    for line in frontmatter.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip().strip("'\"")

    return metadata, body


def _split_by_headers(content: str) -> list[tuple[str, str]]:
    """
    Partition Markdown at H1-H3 while preserving every source character.

    Returns (header metadata, exact source span) tuples. The header remains in
    the exact span so joining the second tuple items reconstructs ``content``.
    """
    pattern = re.compile(r"^(#{1,3} .+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return [("", content)]

    parts: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        parts.append(("", content[: matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        parts.append((match.group(1).strip(), content[match.start() : end]))
    return parts


def _merged_header(sections: list[tuple[str, str]]) -> str:
    """Join distinct non-empty headers in source order, within metadata limits."""
    headers: list[str] = []
    seen: set[str] = set()
    for header, _span in sections:
        if header and header not in seen:
            headers.append(header)
            seen.add(header)
    return " | ".join(headers)[:300]


def _merge_small_header_sections(
    sections: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Greedily merge adjacent exact spans under the minimum chunk size."""
    groups: list[list[tuple[str, str]]] = []
    pending: list[tuple[str, str]] = []
    pending_chars = 0

    for section in sections:
        pending.append(section)
        pending_chars += len(section[1])
        if pending_chars >= CHUNK_MIN_CHARS:
            groups.append(pending)
            pending = []
            pending_chars = 0

    if pending:
        if groups:
            groups[-1].extend(pending)
        else:
            groups.append(pending)

    return [
        (_merged_header(group), "".join(span for _header, span in group))
        for group in groups
    ]


def chunk_markdown_file(file_path: Path) -> ChunkResult:
    """
    Chunk a single markdown file into searchable pieces with metadata.

    Returns a typed result containing chunk dicts on success:
    {
            "id": str,           # "relative/path.md::<hash>::v3::0"
        "text": str,         # chunk content
        "metadata": {
            "path": str,
            "section": str,
            "title": str,
            "header": str,
            "chunk_index": int,
            "file_hash": str,
        }
    }
    """
    # Skip files that are too large
    try:
        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return ChunkResult(status="too_large")
    except OSError as exc:
        return ChunkResult(status="read_error", error=str(exc))

    try:
        raw_bytes = file_path.read_bytes()
        raw_content = raw_bytes.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        return ChunkResult(status="read_error", error=str(exc))

    # Preserve the legacy MD5 domain solely to skip unchanged legacy rows in B1.
    file_hash = compute_hash(raw_content.replace("\r\n", "\n").replace("\r", "\n"))
    content_hash = sha256_bytes(raw_bytes)
    frontmatter, body = _parse_frontmatter(raw_content)
    kb_path = require_kb_path(KB_PATH)
    section = get_section(file_path, kb_path)
    rel_path = get_relative_path(file_path, kb_path)

    title = frontmatter.get("title") or file_path.stem

    if len(body.strip()) < 20:
        return ChunkResult(status="empty")

    header_sections = _merge_small_header_sections(_split_by_headers(body))
    chunks = []
    chunk_index = 0

    for header, exact_section in header_sections:
        sub_chunks = split_fixed_size(
            exact_section,
            MAX_CHARS,
            OVERLAP_CHARS,
            CHUNK_MIN_CHARS,
        )

        for sub_chunk in sub_chunks:
            if not sub_chunk.strip():
                continue
            chunks.append(
                {
                    "id": (
                        f"{rel_path}::{content_hash}::"
                        f"{CHUNKING_CONTRACT_VERSION}::{chunk_index}"
                    ),
                    "text": sub_chunk,
                    "metadata": {
                        "path": rel_path,
                        "section": section,
                        "title": title,
                        "header": header,
                        "chunk_index": chunk_index,
                        "file_hash": file_hash,
                        "content_hash": content_hash,
                        "contract_id": FRESHNESS_CONTRACT_ID,
                        "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
                        "chunking_contract_version": CHUNKING_CONTRACT_VERSION,
                    },
                }
            )
            chunk_index += 1

    if not chunks:
        return ChunkResult(status="empty")
    expected_chunk_count = len(chunks)
    for chunk in chunks:
        metadata = chunk["metadata"]
        if isinstance(metadata, dict):
            metadata["expected_chunk_count"] = expected_chunk_count
    return ChunkResult(status="ok", chunks=chunks)
