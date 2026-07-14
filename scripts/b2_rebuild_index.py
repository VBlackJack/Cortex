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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chroma_client import create_persistent_client
from config import CHROMA_PATH, LEGACY_CHROMA_PATH
from cortex_logging import configure_logging
from data_home import ensure_index_location
from indexer import get_collection
from write_lock import chroma_write_lock

BATCH_SIZE = 100


def _load_rows(sqlite_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(str(sqlite_path), timeout=5)
    cur = con.cursor()
    cur.execute(
        "select id, embedding_id from embeddings where segment_id = "
        "(select id from segments where scope = 'METADATA')"
    )
    rows_by_id: dict[int, dict[str, Any]] = {
        row_id: {"embedding_id": embedding_id, "document": None, "metadata": {}}
        for row_id, embedding_id in cur.fetchall()
    }

    cur.execute(
        "select id, key, string_value, int_value, float_value, bool_value "
        "from embedding_metadata"
    )
    for row_id, key, str_v, int_v, float_v, bool_v in cur.fetchall():
        entry = rows_by_id.get(row_id)
        if entry is None:
            continue
        value = next(
            (value for value in (str_v, int_v, float_v, bool_v) if value is not None),
            None,
        )
        if key == "chroma:document":
            entry["document"] = value
        else:
            entry["metadata"][key] = value

    con.close()
    return list(rows_by_id.values())


def main() -> None:
    configure_logging()
    source_sqlite = Path(CHROMA_PATH) / "chroma.sqlite3"
    rebuild_path = Path(CHROMA_PATH).parent / "chroma_db_rebuild"
    ensure_index_location(Path(LEGACY_CHROMA_PATH), Path(CHROMA_PATH))

    # Chroma write lock covers the raw sqlite3 read of the LIVE db through
    # the upsert into the rebuild target: a concurrent live writer could
    # otherwise change the source mid-snapshot, the same class of race that
    # caused the desync this script exists to recover from.
    with chroma_write_lock():
        print(f"[load] reading rows from {source_sqlite} ...", flush=True)
        rows = _load_rows(source_sqlite)
        print(f"[load] {len(rows)} chunks found", flush=True)

        missing_doc = [r["embedding_id"] for r in rows if not r["document"]]
        if missing_doc:
            raise RuntimeError(
                f"{len(missing_doc)} rows have no document text, e.g. {missing_doc[:5]}"
            )

        client = create_persistent_client(rebuild_path)
        collection = get_collection(client)

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
        print(
            f"[done] rebuilt collection count={final_count} (source rows={len(rows)})",
            flush=True,
        )
        if final_count != len(rows):
            raise RuntimeError(f"count mismatch: rebuilt={final_count} source={len(rows)}")


if __name__ == "__main__":
    main()
