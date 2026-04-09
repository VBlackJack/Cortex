"""
server.py — Cortex MCP server
Exposes two tools to Claude:
  - cortex_search : semantic search in the knowledge base
  - cortex_sync   : incremental sync of the knowledge base
"""

import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # force CPU, avoid GPU driver issues

from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from indexer import discover_sections, get_collection, search, sync


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


# ── Tool: cortex_search ───────────────────────────────────────────────────────

class SearchInput(BaseModel):
    query: str = Field(description="Search query (French or English)")
    section: Optional[str] = Field(
        default=None,
        description=(
            "Limit search to a specific section. A section is a first-level "
            "directory under the knowledge base root (CORTEX_KB_PATH). "
            "Use cortex_list_sections to see what is available. "
            "Leave empty to search all sections."
        ),
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of results to return (1-10)",
    )


@mcp.tool()
def cortex_search(query: str, section: Optional[str] = None, top_k: int = 5) -> str:
    """
    Search the internal knowledge base using semantic similarity.
    Use this tool whenever the user asks about anything that may be documented
    in their local knowledge base. Supports French and English queries.
    """
    hits = search(query=query, section=section, top_k=top_k)

    if not hits:
        return "No results found."

    lines = [f"## Cortex search: `{query}`\n"]
    for i, hit in enumerate(hits, 1):
        meta = hit.get("metadata", {})
        title = meta.get("title") or meta.get("path", "Unknown")
        header = meta.get("header", "")
        sec = meta.get("section", "")
        dist = hit.get("distance", 1.0)
        text = hit.get("text", "")

        lines.append(f"### [{i}] {title}")
        if header:
            lines.append(f"**Section:** {sec} › {header}")
        else:
            lines.append(f"**Section:** {sec}")
        lines.append(f"**Relevance:** {1 - dist:.0%}")
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
    stats = sync(section=section, verbose=False)
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
    if not sections:
        return (
            "No sections found. Either CORTEX_KB_PATH is not set, "
            "the directory does not exist, or it contains no subdirectories."
        )
    lines = ["## Cortex sections\n"]
    for s in sections:
        lines.append(f"- `{s}`")
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
