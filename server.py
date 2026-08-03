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
server.py - Cortex MCP server
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

from chunker_utils import reconstruct_contract_metadata
from config import INDEX_WHOLE_FOLDER, ROOT_SECTION, CortexConfigError
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
from ingestion.config import IngestionConfigError, load_ingestion_settings
from ingestion.freshness import augment_freshness_report
from reranker import warmup_reranker
from write_lock import CortexWriteLockedError

_LOG = logging.getLogger("cortex.server")


class SearchResponse(dict[str, Any]):
    """Structured MCP payload with compatibility membership over Markdown."""

    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        return isinstance(key, str) and key in str(self.get("markdown", ""))


# -- Lifespan: warm up the model at startup ------------------------------------


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
    reranker_failure = warmup_reranker()
    if reranker_failure is not None:
        _LOG.warning("reranker_warmup_degraded reason=%s", reranker_failure)
    yield {"collection": collection}


# -- MCP server ----------------------------------------------------------------

mcp = FastMCP("cortex_mcp", lifespan=app_lifespan)


# -- Section validation helper ------------------------------------------------


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
    available_label = (
        "whole knowledge base (omit the section filter)"
        if available == [ROOT_SECTION]
        else ", ".join(sorted(available))
    )
    return None, (
        f"Unknown section: '{section}'\n\n"
        f"Available sections: {available_label}"
    )


# -- Tool: cortex_search -------------------------------------------------------


@mcp.tool()
def cortex_search(
    query: str,
    section: str | None = None,
    top_k: int = 5,
    source_kinds: list[str] | None = None,
    authors: list[str] | None = None,
    occurred_at_from: str | None = None,
    occurred_at_to: str | None = None,
    updated_at_from: str | None = None,
    updated_at_to: str | None = None,
) -> dict[str, Any] | str:
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
        hits = search(
            query=query,
            section=section,
            top_k=top_k,
            source_kinds=source_kinds,
            authors=authors,
            occurred_at_from=occurred_at_from,
            occurred_at_to=occurred_at_to,
            updated_at_from=updated_at_from,
            updated_at_to=updated_at_to,
        )
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
        markdown = f"No results found.\n\nMode: {mode}{suffix}"
        return SearchResponse(
            schema_version=2,
            query=query,
            mode=mode,
            fallback_reason=reason,
            filters={
                "section": section,
                "source_kinds": source_kinds,
                "authors": authors,
                "occurred_at_from": occurred_at_from,
                "occurred_at_to": occurred_at_to,
                "updated_at_from": updated_at_from,
                "updated_at_to": updated_at_to,
            },
            results=[],
            markdown=markdown,
        )

    annotate_search_hits(hits)

    mode = getattr(hits, "mode", "vector-only")
    fallback_reason = getattr(hits, "fallback_reason", None)
    lines = [f"## Cortex search: `{query}`\n", f"**Mode:** {mode}"]
    if fallback_reason:
        lines.append(f"**Fallback reason:** {fallback_reason}")
    lines.append("")
    structured_hits: list[dict[str, Any]] = []
    for i, hit in enumerate(hits, 1):
        meta = hit.get("metadata", {})
        contract = reconstruct_contract_metadata(meta)
        title = contract.get("title") or contract.get("path") or "Unknown"
        header = meta.get("header", "")
        sec = contract.get("section") or ""
        if sec == ROOT_SECTION:
            sec = "All documents"
        dist = hit.get("distance")
        text = hit.get("text", "")
        freshness = hit.get("freshness", "unknown")
        citation = contract.get("canonical_uri") or contract.get("path")
        relevance: float | str | None = None

        lines.append(f"### [{i}] {title}")
        if header:
            lines.append(f"**Section:** {sec} > {header}")
        else:
            lines.append(f"**Section:** {sec}")
        if dist is not None:
            relevance = 1 - dist
            lines.append(f"**Relevance:** {relevance:.0%}")
        elif hit.get("lexical_only"):
            relevance = "lexical-only"
            lines.append("**Relevance:** lexical-only")
        lines.append(
            "**Source:** "
            f"{contract.get('source_kind') or 'unknown'} / "
            f"{contract.get('source_system') or 'unknown'}"
        )
        lines.append(f"**Occurred:** {contract.get('occurred_at') or 'unknown'}")
        lines.append(f"**Updated:** {contract.get('updated_at') or 'unknown'}")
        if citation:
            if contract.get("canonical_uri"):
                lines.append(f"**Citation:** [{title}]({citation})")
            else:
                lines.append(f"**Citation:** `{citation}`")
        lines.append(f"**Freshness:** {freshness}")
        lines.append("")
        lines.append(text)
        lines.append("")
        structured_hits.append(
            {
                "id": hit.get("id"),
                "text": text,
                "metadata": contract,
                "citation": citation,
                "relevance": relevance,
                "freshness": freshness,
            }
        )

    return SearchResponse(
        schema_version=2,
        query=query,
        mode=mode,
        fallback_reason=fallback_reason,
        filters={
            "section": section,
            "source_kinds": source_kinds,
            "authors": authors,
            "occurred_at_from": occurred_at_from,
            "occurred_at_to": occurred_at_to,
            "updated_at_from": updated_at_from,
            "updated_at_to": updated_at_to,
        },
        results=structured_hits,
        markdown="\n".join(lines),
    )


# -- Tool: cortex_sync ---------------------------------------------------------


@mcp.tool()
def cortex_sync(section: str | None = None) -> str:
    """
    Trigger an incremental sync of the knowledge base index.
    If section is provided, only that section is synced.
    Sections are selected by the configured allowlist - use
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
    sec_label = (
        "whole knowledge base"
        if INDEX_WHOLE_FOLDER
        else section or "all sections"
    )
    return (
        f"## Cortex sync complete - {sec_label}\n\n"
        f"- **Published files:** {stats['published_files']}\n"
        f"- **Added chunks:** {stats['added_chunks']}\n"
        f"- **Deleted chunks:** {stats['deleted_chunks']}\n"
        f"- **Removed files:** {stats['removed_files']}\n"
        f"- **Skipped files:** {stats['skipped_files']}\n"
        f"- **Errors:** {stats['errors']}\n"
    )


# -- Tool: cortex_list_sections ------------------------------------------------


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
        if s == ROOT_SECTION:
            lines.append("- All documents (the whole knowledge base folder)")
        else:
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
        report = cortex_freshness_report(
            collection,
            section=section,
            include_entries=include_entries,
        )
        try:
            settings = load_ingestion_settings()
        except IngestionConfigError as exc:
            return {**report, "ingestion_error": str(exc)}
        return augment_freshness_report(
            report,
            ingestion_root=settings.data_root,
            include_entries=include_entries,
        )
    except CortexConfigError as exc:
        return {"error": str(exc)}


# -- Entry point ---------------------------------------------------------------


def run_stdio() -> None:
    """Run the MCP server over stdio with the standard Cortex logging policy."""
    if os.environ.get("CORTEX_DOCTOR_READ_ONLY") != "1":
        from cortex_logging import configure_logging

        configure_logging()
    mcp.run()


if __name__ == "__main__":
    run_stdio()
