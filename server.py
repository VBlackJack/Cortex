# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
server.py — Cortex MCP server
Exposes three tools to Claude:
  - cortex_search         : semantic search in the knowledge base
  - cortex_sync           : incremental sync of the knowledge base
  - cortex_list_sections  : list available sections
"""

import os

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # force CPU, avoid GPU driver issues

from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP

from freshness import annotate_search_hits, cortex_freshness_report
from indexer import discover_out_of_policy_sections, discover_sections, get_collection, search, sync
from write_lock import CortexWriteLockedError


# ── Lifespan: warm up the model at startup ────────────────────────────────────


@asynccontextmanager
async def app_lifespan(app):
    """Load the collection and warm up the embedding model before first request."""
    collection = get_collection()
    try:
        collection.query(query_texts=["warmup"], n_results=1)
    except Exception:
        pass
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
def cortex_search(query: str, section: Optional[str] = None, top_k: int = 5) -> str:
    """
    Search the internal knowledge base using semantic similarity.
    Use this tool whenever the user asks about anything that may be documented
    in their local knowledge base. Supports French and English queries.
    """
    section, err = _resolve_section(section)
    if err:
        return err

    hits = search(query=query, section=section, top_k=top_k)

    if not hits:
        return "No results found."

    hits = annotate_search_hits(hits)

    lines = [f"## Cortex search: `{query}`\n"]
    for i, hit in enumerate(hits, 1):
        meta = hit.get("metadata", {})
        title = meta.get("title") or meta.get("path", "Unknown")
        header = meta.get("header", "")
        sec = meta.get("section", "")
        dist = hit.get("distance", 1.0)
        text = hit.get("text", "")
        freshness = hit.get("freshness", "unknown")

        lines.append(f"### [{i}] {title}")
        if header:
            lines.append(f"**Section:** {sec} › {header}")
        else:
            lines.append(f"**Section:** {sec}")
        lines.append(f"**Relevance:** {1 - dist:.0%}")
        lines.append(f"**Freshness:** {freshness}")
        lines.append("")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


# ── Tool: cortex_sync ─────────────────────────────────────────────────────────


@mcp.tool()
def cortex_sync(section: Optional[str] = None) -> str:
    """
    Trigger an incremental sync of the knowledge base index.
    If section is provided, only that section is synced.
    Sections are auto-discovered from the knowledge base root — use
    cortex_list_sections to see what is available.
    Returns a summary of what was added, deleted, and skipped.
    """
    section, err = _resolve_section(section)
    if err:
        return err

    try:
        stats = sync(section=section, verbose=False)
    except CortexWriteLockedError:
        return (
            "## Cortex sync locked\n\n"
            "Another sync is already in progress. Refusing to write "
            "concurrently - try again once it finishes."
        )
    sec_label = section or "all sections"
    return (
        f"## Cortex sync complete — {sec_label}\n\n"
        f"- **Added:** {stats['added']} chunks\n"
        f"- **Deleted:** {stats['deleted']} chunks\n"
        f"- **Skipped:** {stats['skipped']} files (unchanged)\n"
        f"- **Errors:** {stats['errors']}\n"
    )


# ── Tool: cortex_list_sections ────────────────────────────────────────────────


@mcp.tool()
def cortex_list_sections() -> str:
    """
    List all sections currently available in the knowledge base.
    A section is a first-level directory under the knowledge base root.
    Use this when the user asks what sections exist, or before calling
    cortex_search/cortex_sync with a section filter.
    """
    sections = discover_sections()
    out_of_policy = discover_out_of_policy_sections()
    if not sections and not out_of_policy:
        return (
            "No sections found. Either CORTEX_KB_PATH is not set, "
            "the directory does not exist, or it contains no subdirectories."
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
def cortex_freshness(section: Optional[str] = None) -> dict:
    """Report source freshness without changing the ChromaDB index."""
    section, err = _resolve_section(section)
    if err:
        return {"error": err}
    return cortex_freshness_report(get_collection(), section=section)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
