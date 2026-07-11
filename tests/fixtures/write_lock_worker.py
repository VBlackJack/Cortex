# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Standalone worker process for test_write_lock.py's concurrency proofs.

Acquires the REAL chroma_write_lock() (path/timeout taken from the
CORTEX_WRITE_LOCK_PATH / CORTEX_WRITE_LOCK_TIMEOUT_SECONDS env vars, set by
the parent test per-test for isolation) and, if successful, writes
doc_count dummy chunks with a fixed, explicit embedding vector (no
fastembed model load - keeps this test fast and independent of the real
embedding pipeline, which is not what is under test here). Prints
"OK:<tag>" or "LOCKED:<tag>" as the last stdout line so the parent test can
assert on the outcome without parsing process internals.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import chromadb  # noqa: E402

from write_lock import CortexWriteLockedError, chroma_write_lock  # noqa: E402


def main() -> None:
    db_path, tag, doc_count_s, hold_seconds_s, extra_delay_s = sys.argv[1:6]
    doc_count = int(doc_count_s)
    hold_seconds = float(hold_seconds_s)
    extra_delay = float(extra_delay_s)

    if extra_delay:
        time.sleep(extra_delay)

    try:
        with chroma_write_lock():
            if hold_seconds:
                time.sleep(hold_seconds)
            client = chromadb.PersistentClient(path=db_path)
            collection = client.get_or_create_collection(name="test")
            collection.upsert(
                ids=[f"{tag}-{i}" for i in range(doc_count)],
                embeddings=[[0.1, 0.2, 0.3] for _ in range(doc_count)],  # type: ignore[arg-type]  # chromadb's stub overloads reject a plain list[list[float]] despite it being valid at runtime
                documents=[f"dummy doc {i} from {tag}" for i in range(doc_count)],
                metadatas=[{"tag": tag} for _ in range(doc_count)],
            )
        print(f"OK:{tag}")
    except CortexWriteLockedError:
        print(f"LOCKED:{tag}")


if __name__ == "__main__":
    main()
