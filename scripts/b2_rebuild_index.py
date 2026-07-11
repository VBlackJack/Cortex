# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Rebuild the Chroma collection from the SQLite metadata segment.

The metadata (SQLite) segment and the vector (HNSW) segment of a Chroma
collection can desync after an interrupted concurrent write: SQLite stays
consistent (its own integrity check passes) while the HNSW index falls behind
or corrupts, causing later count()/get() calls through the Rust bindings to
hang. SQLite is the trustworthy source here; this script re-derives every
chunk's id/text/metadata from it and re-embeds into a fresh collection,
sidestepping the suspect HNSW segment entirely.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chromadb

from config import CHROMA_PATH, COLLECTION_NAME
from indexer import get_embedding_function

BATCH_SIZE = 100


def _load_rows(sqlite_path: Path) -> list[dict]:
    con = sqlite3.connect(str(sqlite_path), timeout=5)
    cur = con.cursor()
    cur.execute(
        "select id, embedding_id from embeddings where segment_id = "
        "(select id from segments where scope = 'METADATA')"
    )
    rows_by_id: dict[int, dict] = {
        row_id: {"embedding_id": embedding_id, "document": None, "metadata": {}}
        for row_id, embedding_id in cur.fetchall()
    }

    cur.execute("select id, key, string_value, int_value, float_value, bool_value from embedding_metadata")
    for row_id, key, str_v, int_v, float_v, bool_v in cur.fetchall():
        entry = rows_by_id.get(row_id)
        if entry is None:
            continue
        value = str_v if str_v is not None else int_v if int_v is not None else float_v if float_v is not None else bool_v
        if key == "chroma:document":
            entry["document"] = value
        else:
            entry["metadata"][key] = value

    con.close()
    return list(rows_by_id.values())


def main() -> None:
    source_sqlite = Path(CHROMA_PATH) / "chroma.sqlite3"
    rebuild_path = Path(CHROMA_PATH).parent / "chroma_db_rebuild"

    print(f"[load] reading rows from {source_sqlite} ...", flush=True)
    rows = _load_rows(source_sqlite)
    print(f"[load] {len(rows)} chunks found", flush=True)

    missing_doc = [r["embedding_id"] for r in rows if not r["document"]]
    if missing_doc:
        raise RuntimeError(f"{len(missing_doc)} rows have no document text, e.g. {missing_doc[:5]}")

    client = chromadb.PersistentClient(path=str(rebuild_path))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )

    print("[upsert] publishing into fresh collection ...", flush=True)
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        collection.upsert(
            ids=[r["embedding_id"] for r in batch],
            documents=[r["document"] for r in batch],
            metadatas=[r["metadata"] for r in batch],
        )
        if start % 2000 == 0:
            print(f"[upsert] {start}/{len(rows)}", flush=True)

    final_count = collection.count()
    print(f"[done] rebuilt collection count={final_count} (source rows={len(rows)})", flush=True)
    if final_count != len(rows):
        raise RuntimeError(f"count mismatch: rebuilt={final_count} source={len(rows)}")


if __name__ == "__main__":
    main()
