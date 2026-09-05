# Copyright 2026 Julien Bombled
# Licensed under the Apache License, Version 2.0.
"""Bounded JSON search contract for desktop clients."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CONTRACT_VERSION = 1
EXCERPT_LIMIT = 1200
QUERY_LIMIT = 2000
DOCUMENT_EXTENSIONS = frozenset({".md", ".pdf", ".txt"})


def safe_document_path(root: Path | None, relative: str) -> str | None:
    """Resolve only existing documents contained in a configured source root."""
    if root is None or not relative:
        return None
    base = root.resolve()
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base) or candidate.suffix.lower() not in DOCUMENT_EXTENSIONS:
        return None
    return str(candidate) if candidate.is_file() else None


def present_hit(hit: dict[str, Any], root: Path | None) -> dict[str, Any]:
    """Expose display fields without allowing arbitrary launch targets."""
    meta = hit.get("metadata") or {}
    path = str(meta.get("path", ""))
    url = str(meta.get("canonical_uri") or meta.get("source_url") or meta.get("url") or "")
    parsed = urlsplit(url)
    safe_url = (
        url if parsed.scheme == "https" and parsed.hostname and not parsed.username else None
    )
    return {
        "id": str(hit["id"]),
        "title": str(meta.get("title") or path),
        "excerpt": str(hit.get("text", ""))[:EXCERPT_LIMIT],
        "path": path,
        "section": str(meta.get("section", "")),
        "source_kind": str(meta.get("source_kind", "note")),
        "updated_at": str(meta.get("updated_at") or ""),
        "open_target": safe_url or safe_document_path(root, path),
    }


def emit_search(query: str, section: str | None, top_k: int, source_kind: str | None) -> int:
    """Write one versioned response; failures never resemble an empty successful search."""
    from config import KB_PATH
    from indexer import search
    from reranker import warmup_reranker

    try:
        warmup_reranker()
        hits = search(
            query,
            section=section,
            top_k=top_k,
            source_kinds=[source_kind] if source_kind else None,
        )
        results = [
            present_hit(
                hit,
                Path(KB_PATH)
                if KB_PATH and hit.get("metadata", {}).get("source_kind", "note") == "note"
                else None,
            )
            for hit in hits
        ]
        payload = {
            "contract_version": CONTRACT_VERSION,
            "operation": "search",
            "status": "succeeded",
            "mode": hits.mode,
            "degraded": hits.fallback_reason is not None,
            "results": results,
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        sys.stderr.write(f"Cortex search failed ({type(exc).__name__}).\n")
        return 1
