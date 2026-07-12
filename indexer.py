# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
indexer.py - Cortex incremental indexer
Usage:
  python indexer.py              # sync all sections
  python indexer.py Zabbix       # sync one section
  python indexer.py --search "query" [--section Zabbix] [--top-k 5]
"""

import os
import logging
import warnings
import argparse
from pathlib import Path

log = logging.getLogger("cortex")

# Force CPU-only - avoid GPU driver crashes
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Suppress fastembed pooling migration notice (mean pooling is correct for this model)
warnings.filterwarnings("ignore", message=".*mean pooling.*", category=UserWarning)

import chromadb  # noqa: E402
from chromadb import EmbeddingFunction, Embeddings  # noqa: E402
from fastembed import TextEmbedding  # noqa: E402

from config import (  # noqa: E402
    KB_PATH,
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    INCLUDED_SECTIONS,
)
from chunker_utils import (  # noqa: E402
    discover_out_of_policy_dirs,
)
from sync_hash_aware import empty_sync_stats, merge_sync_stats, sync_section  # noqa: E402
from write_lock import chroma_write_lock  # noqa: E402


# ── Embedding function ────────────────────────────────────────────────────────


class FastEmbedFunction(EmbeddingFunction):
    """
    ChromaDB-compatible wrapper around fastembed.TextEmbedding.
    Uses a module-level singleton to avoid reloading the model on every call.
    """

    _instance = None
    _initialized = False

    def __new__(cls, model_name: str):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str):
        if self._initialized:
            return
        self._model = TextEmbedding(model_name=model_name)
        self._model_name = model_name
        FastEmbedFunction._initialized = True

    def __call__(self, input: list[str]) -> Embeddings:
        embeddings = list(self._model.embed(input))
        return [e.tolist() for e in embeddings]


def get_embedding_function() -> FastEmbedFunction:
    return FastEmbedFunction(model_name=EMBEDDING_MODEL)


# ── ChromaDB helpers ──────────────────────────────────────────────────────────


def get_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=CHROMA_PATH)


def get_collection(client=None):
    if client is None:
        client = get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def discover_sections() -> list[str]:
    """
    Return the sections eligible for sync/search/list, per the single
    section policy (config.INCLUDED_SECTIONS). Warns, never silently
    drops, if a configured section is missing on disk - unlike the old
    KNOWN_SECTIONS list, whose staleness went unnoticed for months.
    """
    kb_root = Path(KB_PATH)
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
    return discover_out_of_policy_dirs(Path(KB_PATH))


# ── Sync ──────────────────────────────────────────────────────────────────────


def sync(section: str = None, verbose: bool = True) -> dict:
    """
    Incremental sync. If section is given, only process that section's folder.
    Returns file/chunk publication, removal, skip and error counters.
    Acquires the exclusive Chroma write lock for the whole call - see
    write_lock.chroma_write_lock(). Raises CortexWriteLockedError, without
    writing anything, if another writer already holds it.
    """
    with chroma_write_lock():
        return _sync_locked(section, verbose)


def _sync_locked(section: str | None = None, verbose: bool = True) -> dict[str, int]:
    kb_root = Path(KB_PATH)
    stats = empty_sync_stats()

    if not kb_root.is_dir():
        log.error("KB_PATH is not a directory: %s", kb_root)
        stats["errors"] += 1
        return stats

    client = get_client()
    collection = get_collection(client)

    section_names = [section] if section else sorted(INCLUDED_SECTIONS)
    folders = [kb_root / name for name in section_names]

    for folder in folders:
        sec_name = folder.name
        if verbose:
            log.info("--- Section: %s ---", sec_name)

        section_stats = sync_section(
            collection,
            kb_root,
            sec_name,
            checkpoint=None,
            verbose=verbose,
        )
        merge_sync_stats(stats, section_stats)

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


# ── Search ────────────────────────────────────────────────────────────────────


def search(query: str, section: str = None, top_k: int = 5) -> list[dict]:
    """Return top_k results as list of {text, metadata, distance}."""
    collection = get_collection()
    where = {"section": section} if section else None
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        return [{"text": f"Search error: {e}", "metadata": {}, "distance": 1.0}]

    hits = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append({"text": doc, "metadata": meta or {}, "distance": dist})
    return hits


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

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
    args = parser.parse_args()

    if args.search:
        hits = search(args.search, section=args.section, top_k=args.top_k)
        for i, h in enumerate(hits, 1):
            meta = h["metadata"]
            print(
                f"\n[{i}] {meta.get('title', meta.get('path', '?'))} "
                f"(dist={h['distance']:.3f})"
            )
            print(f"    Section: {meta.get('section')} | {meta.get('header', '')}")
            print(f"    {h['text'][:300]}...")
    else:
        sync(section=args.section, verbose=True)
