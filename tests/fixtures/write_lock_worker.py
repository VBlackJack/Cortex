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

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chroma_client import create_persistent_client  # noqa: E402
from write_lock import CortexWriteLockedError, chroma_write_lock  # noqa: E402


def _wait_for_file(path: Path, timeout_seconds: float) -> None:
    """Poll until ``path`` exists or the timeout elapses (test handshake)."""
    deadline = time.perf_counter() + timeout_seconds
    while not path.exists() and time.perf_counter() < deadline:
        time.sleep(0.02)


def main() -> None:
    db_path, tag, doc_count_s, hold_seconds_s, extra_delay_s = sys.argv[1:6]
    doc_count = int(doc_count_s)
    hold_seconds = float(hold_seconds_s)
    extra_delay = float(extra_delay_s)

    if extra_delay:
        time.sleep(extra_delay)

    try:
        lock_started = time.perf_counter()
        with chroma_write_lock():
            lock_wait_seconds = time.perf_counter() - lock_started
            # Deterministic concurrency handshake (opt-in via env vars): signal
            # that the lock is held, then keep holding until released by the
            # parent, so a second writer provably contends while we hold it.
            ready_file = os.environ.get("CORTEX_TEST_READY_FILE")
            if ready_file:
                Path(ready_file).write_text("acquired", encoding="utf-8")
            release_file = os.environ.get("CORTEX_TEST_RELEASE_FILE")
            if release_file:
                _wait_for_file(Path(release_file), 30.0)
            if hold_seconds:
                time.sleep(hold_seconds)
            client = create_persistent_client(db_path)
            collection = client.get_or_create_collection(name="test")
            collection.upsert(
                ids=[f"{tag}-{i}" for i in range(doc_count)],
                embeddings=[[0.1, 0.2, 0.3] for _ in range(doc_count)],  # type: ignore[arg-type]  # chromadb's stub overloads reject a plain list[list[float]] despite it being valid at runtime
                documents=[f"dummy doc {i} from {tag}" for i in range(doc_count)],
                metadatas=[{"tag": tag} for _ in range(doc_count)],
            )
        print(f"OK:{tag}:{lock_wait_seconds:.6f}")
    except CortexWriteLockedError:
        print(f"LOCKED:{tag}")


if __name__ == "__main__":
    main()
