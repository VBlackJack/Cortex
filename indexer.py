"""
indexer.py - Cortex incremental indexer
Usage:
  python indexer.py              # sync all sections
  python indexer.py Zabbix       # sync one section
  python indexer.py --search "query" [--section Zabbix] [--top-k 5]
"""

import os
import sys
import gc
import warnings
import argparse
from pathlib import Path

# Force CPU-only - avoid GPU driver crashes
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Suppress fastembed pooling migration notice (mean pooling is correct for this model)
warnings.filterwarnings("ignore", category=UserWarning, module="fastembed")

import chromadb
from chromadb import EmbeddingFunction, Embeddings
from fastembed import TextEmbedding

from config import (
    KB_PATH, CHROMA_PATH, COLLECTION_NAME, EMBEDDING_MODEL,
    EXCLUDE_DIRS, EXCLUDE_FILES, KNOWN_SECTIONS
)
from chunker import chunk_markdown_file as chunk_file

# ── Embedding function ────────────────────────────────────────────────────────

class FastEmbedFunction(EmbeddingFunction):
    """
    ChromaDB-compatible wrapper around fastembed.TextEmbedding.
    Uses a module-level singleton to avoid reloading the model on every call.
    """

    _instance = None

    def __new__(cls, model_name: str):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = TextEmbedding(model_name=model_name)
            cls._instance._model_name = model_name
        return cls._instance

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


PAGE_SIZE = 5000  # ChromaDB SQLite backend hits "too many SQL variables"
                  # on unbounded .get() once a section grows beyond ~10k chunks.


def get_section_index(collection, section: str = None) -> dict:
    """
    Fetch the section's index, paginating to stay under SQLite parameter limits.
    Returns {"hash_by_path": {path: file_hash},
             "ids_by_path":  {path: [chunk_id, ...]}}
    Scoped to section to avoid cross-section contamination.
    """
    where = {"section": section} if section else None
    hash_by_path: dict[str, str] = {}
    ids_by_path: dict[str, list[str]] = {}

    offset = 0
    while True:
        try:
            result = collection.get(
                where=where,
                include=["metadatas"],
                limit=PAGE_SIZE,
                offset=offset,
            )
        except Exception:
            # If even a paginated read fails, fall back to whatever we already have.
            break

        ids = result.get("ids") or []
        metas = result.get("metadatas") or []
        if not ids:
            break

        for chunk_id, meta in zip(ids, metas):
            if not meta or "path" not in meta:
                continue
            path = meta["path"]
            ids_by_path.setdefault(path, []).append(chunk_id)
            if "file_hash" in meta and path not in hash_by_path:
                hash_by_path[path] = meta["file_hash"]

        if len(ids) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return {"hash_by_path": hash_by_path, "ids_by_path": ids_by_path}


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync(section: str = None, verbose: bool = True) -> dict:
    """
    Incremental sync. If section is given, only process that section's folder.
    Returns stats dict: {added, deleted, skipped, errors}.

    Requires CORTEX_KB_PATH to be set in the environment.
    """
    if not KB_PATH:
        raise RuntimeError(
            "CORTEX_KB_PATH environment variable is not set.\n"
            "Set it once with:\n"
            "    setx CORTEX_KB_PATH \"<path to your knowledge base>\"\n"
            "Then open a new terminal and try again."
        )

    kb_root = Path(KB_PATH)
    if not kb_root.is_dir():
        raise RuntimeError(
            f"CORTEX_KB_PATH points to a non-existent directory: {KB_PATH}"
        )

    stats = {"added": 0, "deleted": 0, "skipped": 0, "errors": 0}

    client = get_client()
    collection = get_collection(client)

    folders = [kb_root / section] if section else [kb_root / s for s in KNOWN_SECTIONS]

    for folder in folders:
        sec_name = folder.name
        if not folder.is_dir():
            if verbose:
                print(f"[WARN] Section folder not found: {folder}")
            continue

        if verbose:
            print(f"\n--- Section: {sec_name} ---")

        # Single ChromaDB read per section: hashes + chunk IDs in one shot.
        index = get_section_index(collection, section=sec_name)
        hash_by_path = index["hash_by_path"]
        ids_by_path = index["ids_by_path"]

        current_paths: set[str] = set()
        files_to_index: list = []

        for md_file in sorted(folder.rglob("*.md")):
            if any(part in EXCLUDE_DIRS for part in md_file.parts):
                continue
            if md_file.name in EXCLUDE_FILES:
                continue

            chunks = chunk_file(md_file)
            if not chunks:
                stats["skipped"] += 1
                continue

            # Use the same key the chunker stores in metadata (relative to KB_PATH).
            # Otherwise hash_by_path lookups never hit and the sync is not incremental.
            path_key = chunks[0]["metadata"]["path"]
            current_paths.add(path_key)

            file_hash = chunks[0]["metadata"]["file_hash"]
            if hash_by_path.get(path_key) == file_hash:
                stats["skipped"] += 1
                continue

            files_to_index.append((md_file, chunks, path_key))

        # Delete chunks for files removed from the section
        stale_paths = set(hash_by_path.keys()) - current_paths
        if stale_paths:
            stale_ids: list[str] = []
            for p in stale_paths:
                stale_ids.extend(ids_by_path.get(p, []))
            if stale_ids:
                collection.delete(ids=stale_ids)
                stats["deleted"] += len(stale_ids)
                if verbose:
                    print(f"  Deleted {len(stale_ids)} chunks from {len(stale_paths)} removed files")

        # Delete old chunks for changed files before re-adding
        changed_paths = {pk for _, _, pk in files_to_index if hash_by_path.get(pk)}
        if changed_paths:
            changed_ids: list[str] = []
            for p in changed_paths:
                changed_ids.extend(ids_by_path.get(p, []))
            if changed_ids:
                collection.delete(ids=changed_ids)

        # Index new / changed files in batches
        batch_ids, batch_texts, batch_metas = [], [], []

        for md_file, chunks, _ in files_to_index:
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
                            print(f"  [ERROR] Batch upsert: {e}")
                        stats["errors"] += len(batch_ids)
                    batch_ids, batch_texts, batch_metas = [], [], []
                    gc.collect()

            if verbose:
                print(f"  + {md_file.name} ({len(chunks)} chunks)")
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
                    print(f"  [ERROR] Final batch: {e}")
                stats["errors"] += len(batch_ids)
            gc.collect()

    if verbose:
        print(f"\nSync complete: Added={stats['added']} Deleted={stats['deleted']} "
              f"Skipped={stats['skipped']} Errors={stats['errors']}")
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
    parser = argparse.ArgumentParser(description="Cortex indexer")
    parser.add_argument("section", nargs="?", default=None,
                        help="Section to sync (default: all)")
    parser.add_argument("--search", metavar="QUERY", default=None,
                        help="Run a search instead of syncing")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    if args.search:
        hits = search(args.search, section=args.section, top_k=args.top_k)
        for i, h in enumerate(hits, 1):
            meta = h["metadata"]
            print(f"\n[{i}] {meta.get('title', meta.get('path', '?'))} "
                  f"(dist={h['distance']:.3f})")
            print(f"    Section: {meta.get('section')} | Header: {meta.get('header')}")
            print(f"    {h['text'][:300]}...")
    else:
        sync(section=args.section, verbose=True)
