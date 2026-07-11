# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Concurrency proof for the Chroma single-writer lock - the load-bearing
test gate for the design lot. Every test here spawns REAL, separate OS
processes against a REAL, isolated (never the production vault) Chroma
collection - proving inter-process behavior, not simulating it with threads
or mocks. The write lock path is isolated per test via the
CORTEX_WRITE_LOCK_PATH env var, read by config.py at import time.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

WORKER = Path(__file__).parent / "fixtures" / "write_lock_worker.py"


def _run_worker(
    db_path: Path, lock_path: Path, tag: str, doc_count: int, hold_seconds: float,
    timeout_seconds: float = 5, extra_delay_before: float = 0,
) -> subprocess.CompletedProcess[str]:
    import os

    env = dict(os.environ)
    env["CORTEX_WRITE_LOCK_PATH"] = str(lock_path)
    env["CORTEX_WRITE_LOCK_TIMEOUT_SECONDS"] = str(timeout_seconds)
    return subprocess.run(
        [
            sys.executable, str(WORKER),
            str(db_path), tag, str(doc_count), str(hold_seconds), str(extra_delay_before),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_concurrent_writers_exactly_one_succeeds(tmp_path: Path) -> None:
    """Two writers launched at the same time against the same DB: exactly
    one proceeds to completion, the other fails closed. DB integrity holds
    after both return.

    Timing: A holds the lock for ~1.5s (sleep + upsert). B's acquire
    timeout is deliberately set shorter (0.5s) than A's hold, so B's
    bounded wait genuinely expires while A is still writing - this is what
    makes the test observe a real fail-closed rejection rather than B just
    waiting its turn and succeeding after A releases (which would also be
    safe, but proves sequencing, not the fail-closed contract)."""
    db_path = tmp_path / "chroma_db"
    lock_path = tmp_path / "write.lock"

    proc_a = subprocess.Popen(
        [sys.executable, str(WORKER), str(db_path), "A", "5", "1.5", "0"],
        env={**__import__("os").environ, "CORTEX_WRITE_LOCK_PATH": str(lock_path),
             "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "5"},
        stdout=subprocess.PIPE, text=True,
    )
    time.sleep(0.3)  # let A acquire first, widen the contention window
    proc_b = subprocess.Popen(
        [sys.executable, str(WORKER), str(db_path), "B", "5", "0", "0"],
        env={**__import__("os").environ, "CORTEX_WRITE_LOCK_PATH": str(lock_path),
             "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "0.5"},
        stdout=subprocess.PIPE, text=True,
    )

    out_a, _ = proc_a.communicate(timeout=15)
    out_b, _ = proc_b.communicate(timeout=15)

    outcomes = {out_a.strip().splitlines()[-1], out_b.strip().splitlines()[-1]}
    assert "OK" in {o.split(":")[0] for o in outcomes}
    assert "LOCKED" in {o.split(":")[0] for o in outcomes}
    # exactly one OK, one LOCKED - never both OK, never both LOCKED
    ok_count = sum(1 for o in outcomes if o.startswith("OK"))
    locked_count = sum(1 for o in outcomes if o.startswith("LOCKED"))
    assert ok_count == 1
    assert locked_count == 1

    import chromadb
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(name="test")
    # exactly one writer's docs landed - never a partial mix from both
    assert collection.count() == 5


def test_respawn_simulation(tmp_path: Path) -> None:
    """The exact scenario this lot exists for: writer A is actively holding
    the lock mid-write when writer B (the 'respawned server') attempts to
    write. B must fail closed, never touch the DB."""
    db_path = tmp_path / "chroma_db"
    lock_path = tmp_path / "write.lock"

    proc_a = subprocess.Popen(
        [sys.executable, str(WORKER), str(db_path), "A", "5", "2.0", "0"],
        env={**__import__("os").environ, "CORTEX_WRITE_LOCK_PATH": str(lock_path),
             "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "1"},
        stdout=subprocess.PIPE, text=True,
    )
    time.sleep(0.5)  # A is confirmed mid-write (holding the lock, sleeping) by now

    result_b = _run_worker(db_path, lock_path, "B", 5, 0, timeout_seconds=1)
    out_a, _ = proc_a.communicate(timeout=15)

    assert out_a.strip().splitlines()[-1].startswith("OK")
    assert result_b.stdout.strip().splitlines()[-1].startswith("LOCKED")

    import chromadb
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(name="test")
    assert collection.count() == 5  # only A's docs, B never wrote


def test_reads_during_write_not_blocked(tmp_path: Path) -> None:
    """A read (collection.get/count) must complete fast while a writer
    holds the lock - reads never touch chroma_write_lock()."""
    db_path = tmp_path / "chroma_db"
    lock_path = tmp_path / "write.lock"

    # Seed the DB first (unlocked, sequential) so there's something to read.
    seed = _run_worker(db_path, lock_path, "seed", 3, 0)
    assert seed.stdout.strip().splitlines()[-1].startswith("OK")

    proc_writer = subprocess.Popen(
        [sys.executable, str(WORKER), str(db_path), "W", "2", "2.0", "0"],
        env={**__import__("os").environ, "CORTEX_WRITE_LOCK_PATH": str(lock_path),
             "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "5"},
        stdout=subprocess.PIPE, text=True,
    )
    time.sleep(0.5)  # writer is confirmed holding the lock by now

    import chromadb
    t0 = time.perf_counter()
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(name="test")
    count = collection.count()
    elapsed = time.perf_counter() - t0

    proc_writer.communicate(timeout=15)

    assert count == 3  # the seeded docs, read while W held the write lock
    assert elapsed < 2.0  # nowhere near W's 2s hold - proves reads are not blocked


def test_crash_staleness_auto_release(tmp_path: Path) -> None:
    """A writer is killed abruptly while holding the lock (no clean
    shutdown). The next writer must acquire promptly - no permanent
    deadlock, no manual staleness cleanup needed."""
    db_path = tmp_path / "chroma_db"
    lock_path = tmp_path / "write.lock"

    proc_victim = subprocess.Popen(
        [sys.executable, str(WORKER), str(db_path), "victim", "1", "30", "0"],
        env={**__import__("os").environ, "CORTEX_WRITE_LOCK_PATH": str(lock_path),
             "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "3"},
        stdout=subprocess.PIPE, text=True,
    )
    time.sleep(0.6)  # confirmed holding the lock (hold_seconds=30, still sleeping)
    proc_victim.kill()  # hard kill, no finally/cleanup runs - simulates a crash
    proc_victim.wait(timeout=5)

    t0 = time.perf_counter()
    result = _run_worker(db_path, lock_path, "next", 4, 0, timeout_seconds=3)
    elapsed = time.perf_counter() - t0

    assert result.stdout.strip().splitlines()[-1].startswith("OK")
    assert elapsed < 2.0  # acquired promptly, did not wait out the 3s timeout

    import chromadb
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(name="test")
    assert collection.count() == 4  # victim never wrote anything (killed before its upsert)
