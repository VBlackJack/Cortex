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
"""Deterministic UTF-8 frontmatter v2 rendering and incremental reads."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from confluence_writer.constants import FRONTMATTER_SCHEMA_VERSION, SOURCE_KIND, SOURCE_SYSTEM
from confluence_writer.models import RemotePage

_FIELDS = (
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


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("frontmatter timestamps must include a UTC offset")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def render_document(page: RemotePage, *, path: str, body: str, captured_at: datetime) -> bytes:
    """Add the complete v2 contract above normalized converter Markdown."""
    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n").strip("\n") + "\n"
    body_bytes = normalized_body.encode("utf-8", errors="strict")
    values: dict[str, object] = {
        "schema_version": FRONTMATTER_SCHEMA_VERSION,
        "source_kind": SOURCE_KIND,
        "source_system": SOURCE_SYSTEM,
        "source_uid": page.page_id,
        "container_uid": page.space_key,
        "title": page.title,
        "author": page.author,
        "occurred_at": _timestamp(page.occurred_at),
        "updated_at": _timestamp(page.updated_at),
        "canonical_uri": page.canonical_uri,
        "path": path,
        "section": None,
        "captured_at": _timestamp(captured_at),
        "content_hash": hashlib.sha256(body_bytes).hexdigest(),
        "chunk_index": None,
    }
    lines = ["---"]
    lines.extend(
        f"{field}: {json.dumps(values[field], ensure_ascii=False, separators=(',', ':'))}"
        for field in _FIELDS
    )
    lines.extend(("---", normalized_body))
    return ("\n".join(lines)).encode("utf-8", errors="strict")


def parse_frontmatter(content: bytes) -> dict[str, Any]:
    """Parse the deterministic JSON-scalar YAML subset emitted by this writer."""
    text = content.decode("utf-8", errors="strict")
    lines = text.splitlines()
    if len(lines) < 3 or lines[0] != "---":
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}
    values: dict[str, Any] = {}
    for line in lines[1:end]:
        key, separator, raw = line.partition(": ")
        if not separator:
            return {}
        try:
            values[key] = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return values


def previous_updated_at(content: bytes) -> datetime | None:
    """Read the prior source marker without accepting unrelated frontmatter."""
    values = parse_frontmatter(content)
    if values.get("source_system") != SOURCE_SYSTEM:
        return None
    raw = values.get("updated_at")
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None and value.utcoffset() is not None else None


__all__ = ["parse_frontmatter", "previous_updated_at", "render_document"]
