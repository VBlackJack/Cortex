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
indexer.py - Cortex incremental indexer
Usage:
  python indexer.py              # sync all sections
  python indexer.py Zabbix       # sync one section
  python indexer.py --search "query" [--section Zabbix] [--top-k 5]
"""

import argparse
import logging
import os
import sqlite3
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

log = logging.getLogger("cortex.indexer")

# Force CPU-only - avoid GPU driver crashes
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Suppress fastembed pooling migration notice (mean pooling is correct for this model)
warnings.filterwarnings("ignore", message=".*mean pooling.*", category=UserWarning)

from offline_models import activate_if_embedded  # noqa: E402

_MODEL_RUNTIME = activate_if_embedded()

import chromadb  # noqa: E402
from chromadb import EmbeddingFunction, Embeddings  # noqa: E402
from fastembed import TextEmbedding  # noqa: E402

from chroma_client import create_persistent_client  # noqa: E402
from chunker_utils import (  # noqa: E402
    SOURCE_KINDS,
    discover_out_of_policy_dirs,
    normalize_rfc3339,
    timestamp_epoch_ms,
)
from config import (  # noqa: E402
    CHROMA_PATH,
    EMBEDDING_MODEL,
    FRESHNESS_CONTRACT_ID,
    FRESHNESS_CONTRACT_VERSION,
    INCLUDED_SECTIONS,
    INDEX_WHOLE_FOLDER,
    INGESTION_DOCUMENT_SECTION,
    KB_PATH,
    LEGACY_CHROMA_PATH,
    ROOT_SECTION,
    SEARCH_HYBRID_CANDIDATES,
    SEARCH_RRF_K,
    SEARCH_TOP_K_MAX,
    SEARCH_TOP_K_MIN,
    require_kb_path,
)
from data_home import ensure_index_location  # noqa: E402
from embedding_fingerprint import get_validated_collection  # noqa: E402
from ingestion.config import (  # noqa: E402
    IngestionConfigError,
    load_ingestion_settings,
)
from lexical_index import LexicalIndex, prepare_lexical_index  # noqa: E402
from reranker import rerank_fused_hits, warmup_reranker  # noqa: E402
from sync_hash_aware import (  # noqa: E402
    empty_sync_stats,
    merge_sync_stats,
    sync_ingestion_documents,
    sync_section,
)
from write_lock import chroma_write_lock  # noqa: E402

# -- Embedding function --------------------------------------------------------


class FastEmbedFunction(EmbeddingFunction):
    """
    ChromaDB-compatible wrapper around fastembed.TextEmbedding.
    Uses a module-level singleton to avoid reloading the model on every call.
    """

    _instance: ClassVar["FastEmbedFunction | None"] = None
    _initialized: bool = False

    def __new__(cls, model_name: str) -> "FastEmbedFunction":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str) -> None:
        if self._initialized:
            return
        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(_MODEL_RUNTIME.cache_dir),
            local_files_only=_MODEL_RUNTIME.local_files_only,
        )
        self._model_name = model_name
        FastEmbedFunction._initialized = True

    def __call__(self, input: list[str]) -> Embeddings:
        embeddings = list(self._model.embed(input))
        return [e.tolist() for e in embeddings]

    @staticmethod
    def name() -> str:
        """Return the stable Chroma identifier for Cortex's embedding adapter."""
        return "cortex-fastembed"

    def get_config(self) -> dict[str, str]:
        """Return the serializable configuration associated with name()."""
        return {"model_name": self._model_name}

    @staticmethod
    def build_from_config(config: dict[str, str]) -> "FastEmbedFunction":
        """Reconstruct the adapter from a persisted Chroma configuration."""
        return FastEmbedFunction(model_name=config["model_name"])


def get_embedding_function() -> FastEmbedFunction:
    return FastEmbedFunction(model_name=EMBEDDING_MODEL)


# -- ChromaDB helpers ----------------------------------------------------------


def get_client() -> chromadb.PersistentClient:
    ensure_index_location(Path(LEGACY_CHROMA_PATH), Path(CHROMA_PATH))
    return create_persistent_client(CHROMA_PATH)


def get_collection(client: Any | None = None) -> Any:
    if client is None:
        client = get_client()
    return get_validated_collection(client, get_embedding_function())


def discover_sections() -> list[str]:
    """
    Return the sections eligible for sync/search/list, per the single
    section policy (config.INCLUDED_SECTIONS). Warns, never silently
    drops, if a configured section is missing on disk - unlike the old
    KNOWN_SECTIONS list, whose staleness went unnoticed for months.
    """
    kb_root = Path(require_kb_path(KB_PATH))
    if INDEX_WHOLE_FOLDER:
        if kb_root.is_dir():
            return [ROOT_SECTION]
        log.warning("Knowledge base folder not found on disk at %s", kb_root)
        return []
    sections = []
    for name in sorted(INCLUDED_SECTIONS):
        if (kb_root / name).is_dir():
            sections.append(name)
        else:
            log.warning("Included section '%s' not found on disk at %s", name, kb_root / name)
    return sections


def discover_out_of_policy_sections() -> list[str]:
    """Live top-level dirs present but outside the section policy (neither
    included nor structurally excluded) - never auto-indexed, surfaced so
    a genuinely new section is never a silent gap."""
    if INDEX_WHOLE_FOLDER:
        return []
    return discover_out_of_policy_dirs(Path(require_kb_path(KB_PATH)))


# -- Sync ----------------------------------------------------------------------


def sync(section: str | None = None, verbose: bool = True) -> dict[str, int]:
    """
    Incremental sync. If section is given, only process that section's folder.
    Returns file/chunk publication, removal, skip and error counters.
    Acquires the exclusive Chroma write lock for the whole call - see
    write_lock.chroma_write_lock(). Raises CortexWriteLockedError, without
    writing anything, if another writer already holds it.
    """
    ensure_index_location(Path(LEGACY_CHROMA_PATH), Path(CHROMA_PATH))
    with chroma_write_lock():
        return _sync_locked(section, verbose)


def _sync_locked(section: str | None = None, verbose: bool = True) -> dict[str, int]:
    kb_root = Path(require_kb_path(KB_PATH))
    stats = empty_sync_stats()

    if not kb_root.is_dir():
        log.error("KB_PATH is not a directory: %s", kb_root)
        stats["errors"] += 1
        return stats

    client = get_client()
    collection = get_collection(client)
    lexical_index = None
    try:
        lexical_index = prepare_lexical_index(
            collection,
            Path(CHROMA_PATH).parent / "lexical.db",
        )
    except Exception as exc:  # noqa: BLE001 -- vector index remains authoritative.
        stats["errors"] += 1
        log.exception("lexical_prepare_error reason=%s", exc)

    if INDEX_WHOLE_FOLDER:
        if section not in {None, ROOT_SECTION}:
            log.error("Unknown section in whole-folder mode: %s", section)
            stats["errors"] += 1
            return stats
        section_names = [ROOT_SECTION]
    else:
        if section == ROOT_SECTION:
            log.error("Reserved root section is unavailable in sections mode")
            stats["errors"] += 1
            return stats
        section_names = [section] if section else sorted(INCLUDED_SECTIONS)

    for sec_name in section_names:
        if verbose:
            label = "whole knowledge base" if sec_name == ROOT_SECTION else sec_name
            log.info("--- Section: %s ---", label)

        section_stats = sync_section(
            collection,
            kb_root,
            sec_name,
            checkpoint=None,
            verbose=verbose,
            lexical_index=lexical_index,
        )
        merge_sync_stats(stats, section_stats)

    should_sync_documents = section is None or section == INGESTION_DOCUMENT_SECTION
    if INDEX_WHOLE_FOLDER:
        should_sync_documents = section in {None, ROOT_SECTION}
    if should_sync_documents:
        try:
            ingestion_settings = load_ingestion_settings()
        except IngestionConfigError as exc:
            stats["errors"] += 1
            log.error("ingestion_config_error reason=%s", exc)
        else:
            document_stats = sync_ingestion_documents(
                collection,
                ingestion_settings.data_root,
                retention_generations=ingestion_settings.retention_generations,
                checkpoint=None,
                verbose=verbose,
                lexical_index=lexical_index,
            )
            merge_sync_stats(stats, document_stats)

    if verbose:
        log.info(
            "Sync complete: PublishedFiles=%d AddedChunks=%d DeletedChunks=%d "
            "RemovedFiles=%d SkippedFiles=%d Errors=%d",
            stats["published_files"],
            stats["added_chunks"],
            stats["deleted_chunks"],
            stats["removed_files"],
            stats["skipped_files"],
            stats["errors"],
        )
    return stats


# -- Search --------------------------------------------------------------------


class CortexSearchError(RuntimeError):
    """Raised when Chroma cannot execute a semantic query."""


class SearchResults(list[dict[str, Any]]):
    """Backward-compatible hit list carrying retrieval-mode diagnostics."""

    def __init__(
        self,
        hits: list[dict[str, Any]],
        *,
        mode: str,
        fallback_reason: str | None = None,
    ) -> None:
        super().__init__(hits)
        self.mode = mode
        self.fallback_reason = fallback_reason


def _filter_values(values: Sequence[str] | None, *, field: str) -> tuple[str, ...]:
    if values is None:
        return ()
    normalized = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    if field == "source_kinds":
        invalid = sorted(set(normalized) - SOURCE_KINDS)
        if invalid:
            raise CortexSearchError(f"Invalid source kind filter: {', '.join(invalid)}")
    return normalized


def _filter_timestamp(value: str | None, *, field: str) -> int | None:
    if value is None:
        return None
    normalized = normalize_rfc3339(value)
    if normalized is None:
        raise CortexSearchError(f"Invalid RFC 3339 timestamp for {field}: {value}")
    return timestamp_epoch_ms(normalized)


def build_chroma_where(
    *,
    section: str | None,
    source_kinds: Sequence[str] | None,
    authors: Sequence[str] | None,
    occurred_at_from: str | None,
    occurred_at_to: str | None,
    updated_at_from: str | None,
    updated_at_to: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build one equivalent filter plan for Chroma and the lexical branch."""
    kinds = _filter_values(source_kinds, field="source_kinds")
    author_values = _filter_values(authors, field="authors")
    epoch_filters = {
        "occurred_at_from_ms": _filter_timestamp(
            occurred_at_from, field="occurred_at_from"
        ),
        "occurred_at_to_ms": _filter_timestamp(occurred_at_to, field="occurred_at_to"),
        "updated_at_from_ms": _filter_timestamp(updated_at_from, field="updated_at_from"),
        "updated_at_to_ms": _filter_timestamp(updated_at_to, field="updated_at_to"),
    }
    conditions: list[dict[str, Any]] = []
    if section is not None:
        conditions.append({"section": section})
    if kinds:
        conditions.append({"source_kind": {"$in": list(kinds)}})
    if author_values:
        conditions.append({"author": {"$in": list(author_values)}})
    for field, operator, value in (
        ("occurred_at_epoch_ms", "$gte", epoch_filters["occurred_at_from_ms"]),
        ("occurred_at_epoch_ms", "$lte", epoch_filters["occurred_at_to_ms"]),
        ("updated_at_epoch_ms", "$gte", epoch_filters["updated_at_from_ms"]),
        ("updated_at_epoch_ms", "$lte", epoch_filters["updated_at_to_ms"]),
    ):
        if value is not None:
            conditions.append({field: {operator: value}})
    has_v2_filter = bool(
        kinds
        or author_values
        or any(value is not None for value in epoch_filters.values())
    )
    if has_v2_filter:
        conditions.append({"schema_version": 2})
    where = None
    if len(conditions) == 1:
        where = conditions[0]
    elif conditions:
        where = {"$and": conditions}
    return where, {
        "source_kinds": kinds,
        "authors": author_values,
        **epoch_filters,
    }


def reciprocal_rank_fusion(
    vector_hits: list[dict[str, Any]],
    lexical_hits: list[dict[str, Any]],
    *,
    rrf_k: int = SEARCH_RRF_K,
) -> list[dict[str, Any]]:
    """Fuse ranked branches by complete chunk ID with deterministic ties."""
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    hits_by_id: dict[str, dict[str, Any]] = {}
    for branch_name, branch in (("vector", vector_hits), ("lexical", lexical_hits)):
        for rank, hit in enumerate(branch, start=1):
            chunk_id = str(hit["id"])
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            best_rank[chunk_id] = min(best_rank.get(chunk_id, rank), rank)
            if branch_name == "vector" or chunk_id not in hits_by_id:
                normalized = dict(hit)
                if branch_name == "lexical":
                    metadata = {
                        "path": hit.get("path", ""),
                        "section": hit.get("section", ""),
                    }
                    id_parts = chunk_id.rsplit("::", 3)
                    if len(id_parts) == 4 and len(id_parts[1]) == 64:
                        metadata.update(
                            {
                                "content_hash": id_parts[1],
                                "chunking_contract_version": id_parts[2],
                                "contract_id": FRESHNESS_CONTRACT_ID,
                                "content_hash_contract_version": (
                                    FRESHNESS_CONTRACT_VERSION
                                ),
                            }
                        )
                    normalized.setdefault(
                        "metadata",
                        metadata,
                    )
                hits_by_id[chunk_id] = normalized
    ordered_ids = sorted(
        scores,
        key=lambda chunk_id: (-scores[chunk_id], best_rank[chunk_id], chunk_id),
    )
    fused: list[dict[str, Any]] = []
    for chunk_id in ordered_ids:
        hit = hits_by_id[chunk_id]
        hit["rrf_score"] = scores[chunk_id]
        if "distance" not in hit:
            hit["lexical_only"] = True
        fused.append(hit)
    return fused


def _hydrate_lexical_metadata(collection: Any, hits: list[dict[str, Any]]) -> None:
    """Attach authoritative Chroma metadata to lexical-only candidates."""
    get_method = getattr(collection, "get", None)
    if not hits or not callable(get_method):
        return
    try:
        result = get_method(ids=[str(hit["id"]) for hit in hits], include=["metadatas"])
    except Exception as exc:  # noqa: BLE001 -- search remains available with null reconstruction.
        log.warning("lexical_metadata_hydration_failed reason=%s", exc)
        return
    metadata_by_id = {
        str(chunk_id): metadata
        for chunk_id, metadata in zip(
            result.get("ids") or [], result.get("metadatas") or [], strict=True
        )
        if isinstance(metadata, dict)
    }
    for hit in hits:
        metadata = metadata_by_id.get(str(hit["id"]))
        if metadata is not None:
            hit["metadata"] = dict(metadata)


def _vector_search(
    collection: Any,
    query: str,
    where: dict[str, Any] | None,
    candidate_count: int,
) -> list[dict[str, Any]]:
    try:
        results = collection.query(
            query_texts=[query],
            n_results=candidate_count,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        log.error("search_query_error where=%s reason=%s", where, exc)
        raise CortexSearchError(f"Cortex search failed: {exc}") from exc
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    return [
        {"id": chunk_id, "text": doc, "metadata": meta or {}, "distance": dist}
        for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists, strict=True)
    ]


def search(
    query: str,
    section: str | None = None,
    top_k: int = 5,
    *,
    source_kinds: Sequence[str] | None = None,
    authors: Sequence[str] | None = None,
    occurred_at_from: str | None = None,
    occurred_at_to: str | None = None,
    updated_at_from: str | None = None,
    updated_at_to: str | None = None,
) -> SearchResults:
    """Return hybrid results, explicitly degrading to vector-only when needed."""
    collection = get_collection()
    where, lexical_filters = build_chroma_where(
        section=section,
        source_kinds=source_kinds,
        authors=authors,
        occurred_at_from=occurred_at_from,
        occurred_at_to=occurred_at_to,
        updated_at_from=updated_at_from,
        updated_at_to=updated_at_to,
    )
    bounded_top_k = max(SEARCH_TOP_K_MIN, min(top_k, SEARCH_TOP_K_MAX))
    lexical = LexicalIndex()
    fallback_reason: str | None = None
    lexical_hits: list[dict[str, Any]] = []
    if not lexical.path.is_file():
        fallback_reason = "lexical index absent; run cortex sync"
    elif not lexical.is_compatible():
        fallback_reason = "lexical index version is incompatible; run cortex sync"
    else:
        try:
            lexical_hits = lexical.search(
                query,
                section=section,
                **lexical_filters,
                limit=SEARCH_HYBRID_CANDIDATES,
            )
            _hydrate_lexical_metadata(collection, lexical_hits)
        except (OSError, sqlite3.Error) as exc:
            fallback_reason = f"lexical query failed: {exc}"
    if fallback_reason is not None:
        log.warning("search_mode_vector_only reason=%s", fallback_reason)
        vector_hits = _vector_search(collection, query, where, bounded_top_k)
        return SearchResults(
            vector_hits,
            mode="vector-only",
            fallback_reason=fallback_reason,
        )

    vector_hits = _vector_search(
        collection,
        query,
        where,
        SEARCH_HYBRID_CANDIDATES,
    )
    fused = reciprocal_rank_fusion(vector_hits, lexical_hits)
    reranked, rerank_failure = rerank_fused_hits(query, fused)
    if rerank_failure is not None:
        log.warning("search_mode_hybrid reason=%s", rerank_failure)
        return SearchResults(
            fused[:bounded_top_k],
            mode="hybrid",
            fallback_reason=rerank_failure,
        )
    return SearchResults(reranked[:bounded_top_k], mode="hybrid+rerank")


def main(argv: Sequence[str] | None = None) -> int:
    """Run sync or search from the clone-compatible command line."""
    from cortex_logging import configure_logging

    configure_logging()

    parser = argparse.ArgumentParser(description="Cortex indexer")
    parser.add_argument(
        "section", nargs="?", default=None, help="Section to sync (default: all)"
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        default=None,
        help="Run a search instead of syncing",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)

    if args.search:
        warmup_reranker()
        hits = search(args.search, section=args.section, top_k=args.top_k)
        for i, h in enumerate(hits, 1):
            meta = h["metadata"]
            distance = h.get("distance")
            distance_label = f"{distance:.3f}" if distance is not None else "lexical-only"
            print(
                f"\n[{i}] {meta.get('title', meta.get('path', '?'))} "
                f"(dist={distance_label})"
            )
            print(f"    Section: {meta.get('section')} | {meta.get('header', '')}")
            print(f"    {h['text'][:300]}...")
    else:
        sync(section=args.section, verbose=True)
    return 0


# -- CLI entry point -----------------------------------------------------------

if __name__ == "__main__":
    raise SystemExit(main())
