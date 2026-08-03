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

"""
chunker_utils.py - Shared utilities for markdown and PDF chunkers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from config import EXCLUDE_FILES, EXCLUDED_DIRS, INCLUDED_SECTIONS, METADATA_SCHEMA_VERSION

METADATA_CONTRACT_FIELDS = (
    "schema_version",
    "source_kind",
    "source_system",
    "source_uid",
    "container_uid",
    "title",
    "author",
    "occurred_at",
    "updated_at",
    "canonical_uri",
    "path",
    "section",
    "captured_at",
    "content_hash",
    "chunk_index",
)
SOURCE_KINDS = frozenset({"note", "doc", "message"})

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


def is_excluded_path(
    rel_path: Path,
    *,
    excluded_dirs: frozenset[str] = EXCLUDED_DIRS,
    exclude_files: frozenset[str] = EXCLUDE_FILES,
) -> bool:
    """True if any parent directory of rel_path is structurally excluded
    (excluded_dirs, or a dotfile dir), or the filename itself is.

    The policy defaults to the config-derived module constants; callers that
    must run against a different configuration (for example cortex doctor)
    pass the policy explicitly instead of mutating these globals."""
    if rel_path.name in exclude_files:
        return True
    return any(
        part in excluded_dirs or part.startswith(".")
        for part in rel_path.parts[:-1]
    )


def discover_out_of_policy_dirs(
    kb_root: Path,
    *,
    included_sections: frozenset[str] = INCLUDED_SECTIONS,
    excluded_dirs: frozenset[str] = EXCLUDED_DIRS,
    exclude_files: frozenset[str] = EXCLUDE_FILES,
) -> list[str]:
    """Live top-level dirs neither in included_sections nor structurally
    excluded - present on disk but requiring an explicit policy decision
    before they are ever synced. Never auto-indexed; surfaced so a real gap
    (a genuinely new section) is never silent.

    The policy defaults to the config-derived module constants; callers pass
    it explicitly to run against a different configuration."""
    if not kb_root.is_dir():
        return []
    result = []
    for folder in sorted(kb_root.iterdir()):
        if not folder.is_dir() or folder.name in included_sections:
            continue
        if is_excluded_path(
            Path(folder.name) / "_probe",
            excluded_dirs=excluded_dirs,
            exclude_files=exclude_files,
        ):
            continue
        result.append(folder.name)
    return result


def compute_hash(content: str) -> str:
    """MD5 hash of file content for change detection."""
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact input bytes."""
    return hashlib.sha256(data).hexdigest()


def normalize_rfc3339(value: Any) -> str | None:
    """Normalize an offset timestamp or ISO date to RFC 3339 UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            if len(candidate) == 10:
                parsed_date = date.fromisoformat(candidate)
                parsed = datetime(
                    parsed_date.year,
                    parsed_date.month,
                    parsed_date.day,
                    tzinfo=timezone.utc,
                )
            else:
                parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp_epoch_ms(value: str | None) -> int | None:
    """Convert one normalized RFC 3339 timestamp to Unix epoch milliseconds."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1_000)


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _first_timestamp(frontmatter: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        normalized = normalize_rfc3339(frontmatter.get(key))
        if normalized is not None:
            return normalized
    return None


def build_contract_metadata(
    frontmatter: dict[str, Any],
    *,
    default_source_kind: str,
    rel_path: str,
    section: str,
    fallback_title: str,
    content_hash: str,
    captured_at: datetime,
) -> dict[str, Any]:
    """Build the complete metadata v2 contract before storage normalization."""
    explicit_kind = _string_value(frontmatter.get("source_kind"))
    source_kind = explicit_kind if explicit_kind in SOURCE_KINDS else default_source_kind
    return {
        "schema_version": METADATA_SCHEMA_VERSION,
        "source_kind": source_kind,
        "source_system": _string_value(frontmatter.get("source_system")) or "vault",
        "source_uid": _string_value(frontmatter.get("source_uid")) or rel_path,
        "container_uid": _string_value(frontmatter.get("container_uid")) or section,
        "title": _string_value(frontmatter.get("title")) or fallback_title,
        "author": _string_value(frontmatter.get("author")),
        "occurred_at": _first_timestamp(frontmatter, "occurred_at", "date", "created"),
        "updated_at": _first_timestamp(frontmatter, "updated_at", "updated"),
        "canonical_uri": (
            _string_value(frontmatter.get("canonical_uri"))
            or _string_value(frontmatter.get("url"))
        ),
        "path": rel_path,
        "section": section,
        "captured_at": (
            normalize_rfc3339(frontmatter.get("captured_at"))
            or normalize_rfc3339(captured_at)
        ),
        "content_hash": content_hash,
        "chunk_index": None,
    }


def storage_metadata(
    contract: dict[str, Any],
    *,
    chunk_index: int,
    extras: dict[str, Any],
) -> dict[str, Any]:
    """Omit contract nulls for Chroma and add numeric filter projections."""
    metadata = {
        key: value
        for key, value in contract.items()
        if key in METADATA_CONTRACT_FIELDS and value is not None
    }
    metadata["chunk_index"] = chunk_index
    for timestamp_field in ("occurred_at", "updated_at"):
        epoch_ms = timestamp_epoch_ms(metadata.get(timestamp_field))
        if epoch_ms is not None:
            metadata[f"{timestamp_field}_epoch_ms"] = epoch_ms
    metadata.update({key: value for key, value in extras.items() if value is not None})
    return metadata


def reconstruct_contract_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct all public v2 keys from null-omitting storage metadata."""
    return {field: metadata.get(field) for field in METADATA_CONTRACT_FIELDS}


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
    text: str,
    max_chars: int,
    overlap_chars: int,
    min_tail_chars: int = 0,
) -> list[tuple[int, int]]:
    """Return lossless chunk spans with bounded late-boundary backoff."""
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must not be negative")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")
    if min_tail_chars < 0:
        raise ValueError("min_tail_chars must not be negative")
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

    if len(spans) >= 2 and spans[-1][1] - spans[-1][0] < min_tail_chars:
        prev_start = spans[-2][0]
        total_end = spans[-1][1]
        window = total_end - prev_start
        mid = prev_start + (window + overlap_chars + 1) // 2

        boundary_floor = mid - overlap_chars
        split_pos = text.rfind("\n", boundary_floor, mid)
        if split_pos < boundary_floor:
            split_pos = text.rfind(". ", boundary_floor, mid)
        if split_pos >= boundary_floor:
            mid = split_pos + 1

        spans[-2] = (prev_start, mid)
        spans[-1] = (mid - overlap_chars, total_end)

    return spans


def split_fixed_size(
    text: str,
    max_chars: int,
    overlap_chars: int,
    min_tail_chars: int = 0,
) -> list[str]:
    """Split text with overlap while preserving lossless source spans."""
    chunks: list[str] = []
    for start, end in split_fixed_size_spans(
        text,
        max_chars,
        overlap_chars,
        min_tail_chars,
    ):
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
    return chunks
