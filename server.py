# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
server.py — Cortex MCP server
Exposes four tools to MCP clients:
  - cortex_search         : semantic search in the knowledge base
  - cortex_sync           : incremental sync of the knowledge base
  - cortex_list_sections  : list available sections
  - cortex_freshness      : read-only index freshness summary/details
"""

import logging
import os

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # force CPU, avoid GPU driver issues

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from config import CortexConfigError
from data_home import CortexDataHomeError
from embedding_fingerprint import EmbeddingFingerprintMismatchError
from freshness import annotate_search_hits, cortex_freshness_report
from indexer import (
    CortexSearchError,
    discover_out_of_policy_sections,
    discover_sections,
    get_collection,
    search,
    sync,
)
from write_lock import CortexWriteLockedError

_LOG = logging.getLogger("cortex.server")


# ── Lifespan: warm up the model at startup ────────────────────────────────────


@asynccontextmanager
async def app_lifespan(app: Any) -> AsyncIterator[dict[str, Any]]:
    """Load the collection and warm up the embedding model before first request."""
    if os.environ.get("CORTEX_DOCTOR_READ_ONLY") == "1":
        # PersistentClient mutates SQLite even when only opened. Doctor checks
        # index health separately through immutable read-only SQLite, so this
        # real MCP initialize path must not open Chroma.
        yield {"doctor_read_only": True}
        return
    try:
        collection = get_collection()
    except (EmbeddingFingerprintMismatchError, CortexDataHomeError):
        _LOG.critical("server_start_refused_index_unavailable", exc_info=True)
        raise
    try:
        collection.query(query_texts=["warmup"], n_results=1)
    except Exception as exc:  # noqa: BLE001 -- warmup failure must not prevent startup.
        _LOG.warning("embedding_warmup_failed error=%s", exc)
    yield {"collection": collection}


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("cortex_mcp", lifespan=app_lifespan)


# ── Section validation helper ────────────────────────────────────────────────


def _resolve_section(section: str | None) -> tuple[str | None, str | None]:
    """
    Validate and normalize a section name (case-insensitive).
    Returns (resolved_name, error_message). error_message is None on success.
    """
    if section is None:
        return None, None
    available = discover_sections()
    matching = [s for s in available if s.lower() == section.lower()]
    if matching:
        return matching[0], None
    return None, (
        f"Unknown section: '{section}'\n\n"
        f"Available sections: {', '.join(sorted(available))}"
    )


# ── Tool: cortex_search ───────────────────────────────────────────────────────


@mcp.tool()
def cortex_search(query: str, section: str | None = None, top_k: int = 5) -> str:
    """
    Search the internal knowledge base using semantic similarity.
    Use this tool whenever the user asks about anything that may be documented
    in their local knowledge base. Supports French and English queries.
    """
    try:
        section, err = _resolve_section(section)
    except CortexConfigError as exc:
        return f"## Cortex search configuration error\n\n{exc}"
    if err:
        return err

    try:
        hits = search(query=query, section=section, top_k=top_k)
    except EmbeddingFingerprintMismatchError as exc:
        return f"## Cortex search refused\n\n{exc}"
    except CortexDataHomeError as exc:
        return f"## Cortex data migration required\n\n{exc}"
    except CortexSearchError as exc:
        return f"## Cortex search error\n\n{exc}"

    if not hits:
        mode = getattr(hits, "mode", "vector-only")
        reason = getattr(hits, "fallback_reason", None)
        suffix = f" ({reason})" if reason else ""
        return f"No results found.\n\nMode: {mode}{suffix}"

    annotate_search_hits(hits)

    mode = getattr(hits, "mode", "vector-only")
    fallback_reason = getattr(hits, "fallback_reason", None)
    lines = [f"## Cortex search: `{query}`\n", f"**Mode:** {mode}"]
    if fallback_reason:
        lines.append(f"**Fallback reason:** {fallback_reason}")
    lines.append("")
    for i, hit in enumerate(hits, 1):
        meta = hit.get("metadata", {})
        title = meta.get("title") or meta.get("path", "Unknown")
        header = meta.get("header", "")
        sec = meta.get("section", "")
        dist = hit.get("distance")
        text = hit.get("text", "")
        freshness = hit.get("freshness", "unknown")

        lines.append(f"### [{i}] {title}")
        if header:
            lines.append(f"**Section:** {sec} › {header}")
        else:
            lines.append(f"**Section:** {sec}")
        if dist is not None:
            lines.append(f"**Relevance:** {1 - dist:.0%}")
        elif hit.get("lexical_only"):
            lines.append("**Relevance:** lexical-only")
        lines.append(f"**Freshness:** {freshness}")
        lines.append("")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


# ── Tool: cortex_sync ─────────────────────────────────────────────────────────


@mcp.tool()
def cortex_sync(section: str | None = None) -> str:
    """
    Trigger an incremental sync of the knowledge base index.
    If section is provided, only that section is synced.
    Sections are selected by the configured allowlist — use
    cortex_list_sections to see included and out-of-policy directories.
    Returns file/chunk publication, removal, skip and error counters.
    """
    try:
        section, err = _resolve_section(section)
    except CortexConfigError as exc:
        return f"## Cortex sync configuration error\n\n{exc}"
    if err:
        return err

    try:
        stats = sync(section=section, verbose=False)
    except CortexConfigError as exc:
        return f"## Cortex sync configuration error\n\n{exc}"
    except EmbeddingFingerprintMismatchError as exc:
        return f"## Cortex sync refused\n\n{exc}"
    except CortexDataHomeError as exc:
        return f"## Cortex data migration required\n\n{exc}"
    except CortexWriteLockedError:
        return (
            "## Cortex sync locked\n\n"
            "Another sync is already in progress. Refusing to write "
            "concurrently - try again once it finishes."
        )
    sec_label = section or "all sections"
    return (
        f"## Cortex sync complete — {sec_label}\n\n"
        f"- **Published files:** {stats['published_files']}\n"
        f"- **Added chunks:** {stats['added_chunks']}\n"
        f"- **Deleted chunks:** {stats['deleted_chunks']}\n"
        f"- **Removed files:** {stats['removed_files']}\n"
        f"- **Skipped files:** {stats['skipped_files']}\n"
        f"- **Errors:** {stats['errors']}\n"
    )


# ── Tool: cortex_list_sections ────────────────────────────────────────────────


@mcp.tool()
def cortex_list_sections() -> str:
    """
    List included sections and first-level directories requiring policy opt-in.
    Use this when the user asks what sections exist, or before calling
    cortex_search/cortex_sync with a section filter.
    """
    try:
        sections = discover_sections()
        out_of_policy = discover_out_of_policy_sections()
    except CortexConfigError as exc:
        return f"## Cortex configuration error\n\n{exc}"
    if not sections and not out_of_policy:
        return (
            "No sections found. Check kb_path and included_sections in the "
            "Cortex user configuration."
        )
    lines = ["## Cortex sections\n"]
    for s in sections:
        lines.append(f"- `{s}`")
    if out_of_policy:
        lines.append("\n## Present but out of policy (opt-in required, not indexed)\n")
        for d in out_of_policy:
            lines.append(f"- `{d}`")
    return "\n".join(lines)


@mcp.tool()
def cortex_freshness(
    section: str | None = None,
    include_entries: bool = False,
) -> dict[str, Any]:
    """Report freshness read-only; include per-file entries only on request."""
    try:
        section, err = _resolve_section(section)
    except CortexConfigError as exc:
        return {"error": str(exc)}
    if err:
        return {"error": err}
    try:
        collection = get_collection()
    except (EmbeddingFingerprintMismatchError, CortexDataHomeError) as exc:
        return {"error": str(exc)}
    try:
        return cortex_freshness_report(
            collection,
            section=section,
            include_entries=include_entries,
        )
    except CortexConfigError as exc:
        return {"error": str(exc)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if os.environ.get("CORTEX_DOCTOR_READ_ONLY") != "1":
        from cortex_logging import configure_logging

        configure_logging()
    mcp.run()
