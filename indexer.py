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
import gc
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
    EXCLUDE_DIRS,
    EXCLUDE_FILES,
    KNOWN_SECTIONS,
)
from chunker import chunk_markdown_file  # noqa: E402
from chunker_pdf import chunk_pdf_file  # noqa: E402
from chunker_utils import get_relative_path  # noqa: E402
from write_lock import chroma_write_lock  # noqa: E402

# ── Format routing ────────────────────────────────────────────────────────────

CHUNKERS = {
    ".md": chunk_markdown_file,
    ".pdf": chunk_pdf_file,
}

SUPPORTED_EXTENSIONS = set(CHUNKERS.keys())


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

BATCH_SIZE = 10


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
    Return the list of known sections from config.
    Also includes any extra folders found in KB_PATH that are not in KNOWN_SECTIONS.
    """
    kb_root = Path(KB_PATH)
    sections = list(KNOWN_SECTIONS)
    if kb_root.is_dir():
        for folder in sorted(kb_root.iterdir()):
            if folder.is_dir() and folder.name not in sections:
                sections.append(folder.name)
    return sections


def get_indexed_hashes(collection, section: str = None) -> dict[str, str]:
    """
    Return {file_path: file_hash} for already-indexed documents.
    Scoped to section to avoid cross-section contamination.
    Uses batched queries to handle large sections (ChromaDB SQL variable limit).
    """
    where = {"section": section} if section else None
    hashes: dict[str, str] = {}
    offset = 0
    page_size = 5_000

    while True:
        try:
            result = collection.get(
                where=where,
                include=["metadatas"],
                limit=page_size,
                offset=offset,
            )
        except Exception as e:
            log.warning("get_indexed_hashes failed at offset %d: %s", offset, e)
            break

        metadatas = result.get("metadatas") or []
        if not metadatas:
            break

        for meta in metadatas:
            if meta and "path" in meta and "file_hash" in meta:
                hashes[meta["path"]] = meta["file_hash"]

        if len(metadatas) < page_size:
            break
        offset += page_size

    return hashes


# ── Sync ──────────────────────────────────────────────────────────────────────


def sync(section: str = None, verbose: bool = True) -> dict:
    """
    Incremental sync. If section is given, only process that section's folder.
    Returns stats dict: {added, deleted, skipped, errors}.
    Acquires the exclusive Chroma write lock for the whole call - see
    write_lock.chroma_write_lock(). Raises CortexWriteLockedError, without
    writing anything, if another writer already holds it.
    """
    with chroma_write_lock():
        return _sync_locked(section, verbose)


def _sync_locked(section: str | None = None, verbose: bool = True) -> dict[str, int]:
    kb_root = Path(KB_PATH)
    stats = {"added": 0, "deleted": 0, "skipped": 0, "errors": 0}

    client = get_client()
    collection = get_collection(client)

    folders = (
        [kb_root / section] if section else [kb_root / s for s in discover_sections()]
    )

    for folder in folders:
        sec_name = folder.name
        if not folder.is_dir():
            if verbose:
                log.warning("Section folder not found: %s", folder)
            continue

        if verbose:
            log.info("--- Section: %s ---", sec_name)

        indexed = get_indexed_hashes(collection, section=sec_name)

        current_paths: set[str] = set()
        files_to_index: list = []

        for ext in SUPPORTED_EXTENSIONS:
            for file_path in sorted(folder.rglob(f"*{ext}")):
                if any(part in EXCLUDE_DIRS for part in file_path.parts):
                    continue
                if file_path.name in EXCLUDE_FILES:
                    continue

                path_str = get_relative_path(file_path, KB_PATH)
                current_paths.add(path_str)

                # One read produces the hash and the text that would be embedded.
                chunker = CHUNKERS[ext]
                chunks = chunker(file_path)
                if not chunks:
                    stats["skipped"] += 1
                    continue

                file_hash = chunks[0]["metadata"]["file_hash"]
                if indexed.get(path_str) == file_hash:
                    stats["skipped"] += 1
                    continue

                files_to_index.append((file_path, chunks))

        # Determine which paths need their chunks deleted
        stale_paths = set(indexed.keys()) - current_paths
        changed_paths = {
            get_relative_path(f, KB_PATH)
            for f, _ in files_to_index
            if indexed.get(get_relative_path(f, KB_PATH))
        }
        paths_to_delete = stale_paths | changed_paths

        if paths_to_delete:
            # Batched collection.get() for both stale and changed files
            ids_to_delete = []
            stale_chunk_count = 0
            offset = 0
            page_size = 5_000

            while True:
                try:
                    page = collection.get(
                        where={"section": sec_name},
                        include=["metadatas"],
                        limit=page_size,
                        offset=offset,
                    )
                except Exception:
                    break

                page_ids = page.get("ids", [])
                page_metas = page.get("metadatas") or []
                if not page_ids:
                    break

                for chunk_id, meta in zip(page_ids, page_metas):
                    if meta and meta.get("path") in paths_to_delete:
                        ids_to_delete.append(chunk_id)
                        if meta.get("path") in stale_paths:
                            stale_chunk_count += 1

                if len(page_ids) < page_size:
                    break
                offset += page_size

            if ids_to_delete:
                # ChromaDB delete also has limits, batch the deletes
                for i in range(0, len(ids_to_delete), page_size):
                    collection.delete(ids=ids_to_delete[i : i + page_size])
                stats["deleted"] += stale_chunk_count
                if verbose and stale_paths:
                    log.info(
                        "  Deleted %d chunks from %d removed files",
                        stale_chunk_count,
                        len(stale_paths),
                    )

        # Index new / changed files in batches
        batch_ids, batch_texts, batch_metas = [], [], []

        for file_path, chunks in files_to_index:
            for chunk in chunks:
                batch_ids.append(chunk["id"])
                batch_texts.append(chunk["text"])
                batch_metas.append(chunk["metadata"])

                if len(batch_ids) >= BATCH_SIZE:
                    try:
                        collection.upsert(
                            ids=batch_ids,
                            documents=batch_texts,
                            metadatas=batch_metas,
                        )
                        stats["added"] += len(batch_ids)
                    except Exception as e:
                        if verbose:
                            log.error("  Batch upsert failed: %s", e)
                        stats["errors"] += len(batch_ids)
                    batch_ids, batch_texts, batch_metas = [], [], []
                    gc.collect()

            if verbose:
                log.info("  + %s (%d chunks)", file_path.name, len(chunks))
            gc.collect()

        # Flush remaining batch
        if batch_ids:
            try:
                collection.upsert(
                    ids=batch_ids,
                    documents=batch_texts,
                    metadatas=batch_metas,
                )
                stats["added"] += len(batch_ids)
            except Exception as e:
                if verbose:
                    log.error("  Final batch failed: %s", e)
                stats["errors"] += len(batch_ids)
            gc.collect()

    if verbose:
        log.info(
            "Sync complete: Added=%d Deleted=%d Skipped=%d Errors=%d",
            stats["added"],
            stats["deleted"],
            stats["skipped"],
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
