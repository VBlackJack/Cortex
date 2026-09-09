# Copyright 2026 Julien Bombled
# Licensed under the Apache License, Version 2.0.
"""Bounded JSON search contract for desktop clients."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from index_contract import DEFAULT_RETRIEVAL_MODE, RETRIEVAL_MODES, SOURCE_KINDS, RetrievalMode

CONTRACT_VERSION = 1
EXCERPT_LIMIT = 1200
QUERY_LIMIT = 2000
DEFAULT_TOP_K = 5
DOCUMENT_EXTENSIONS = frozenset({".md", ".pdf", ".txt"})


def build_parser(prog: str = "cortex search") -> argparse.ArgumentParser:
    """Build the search command line without loading the index or the configuration.

    The desktop client builds this exact line; keeping the parser importable on
    its own lets the interoperability proof parse what the client builds.
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Search the Cortex index from the console.",
    )
    parser.add_argument("query", help="Natural-language query, French or English")
    parser.add_argument(
        "--section",
        default=None,
        help="Restrict the search to one section (default: all)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Number of results (default: {DEFAULT_TOP_K})",
    )
    parser.add_argument(
        "--json", action="store_true", help="Return the desktop search JSON contract"
    )
    parser.add_argument("--source-kind", choices=sorted(SOURCE_KINDS), help="Restrict source kind")
    parser.add_argument(
        "--retrieval-mode", choices=RETRIEVAL_MODES, default=DEFAULT_RETRIEVAL_MODE,
        help="Search strategy: vector (default), hybrid, or rerank",
    )
    return parser


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


def emit_search(
    query: str, section: str | None, top_k: int, source_kind: str | None,
    *, retrieval_mode: RetrievalMode = DEFAULT_RETRIEVAL_MODE,
) -> int:
    """Write one versioned response; failures never resemble an empty successful search."""
    from config import KB_PATH
    from indexer import search

    try:
        hits = search(
            query,
            section=section,
            top_k=top_k,
            source_kinds=[source_kind] if source_kind else None,
            retrieval_mode=retrieval_mode,
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
