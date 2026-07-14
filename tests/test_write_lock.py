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
"""Concurrency proof for the Chroma single-writer lock - the load-bearing
test gate for the design lot. Every test here spawns REAL, separate OS
processes against a REAL, isolated (never the production vault) Chroma
collection - proving inter-process behavior, not simulating it with threads
or mocks. The write lock path is isolated per test via the
CORTEX_WRITE_LOCK_PATH env var, read by config.py at import time.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from chroma_client import create_persistent_client

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
    """Two writers contend for the same DB: exactly one proceeds to
    completion, the other fails closed. DB integrity holds after both return.

    Contention is made deterministic with a two-way file handshake, so the
    outcome never depends on process start-up or import timing (which varies
    wildly on cold CI runners): writer A signals once it holds the lock, B is
    launched only then, and A keeps holding until B has finished its attempt.
    B therefore provably tries to acquire while A holds the lock - a real
    fail-closed rejection, not B merely waiting its turn."""
    db_path = tmp_path / "chroma_db"
    lock_path = tmp_path / "write.lock"
    ready_file = tmp_path / "a.acquired"
    release_file = tmp_path / "a.may_release"

    proc_a = subprocess.Popen(
        [sys.executable, str(WORKER), str(db_path), "A", "5", "0", "0"],
        env={**os.environ, "CORTEX_WRITE_LOCK_PATH": str(lock_path),
             "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "5",
             "CORTEX_TEST_READY_FILE": str(ready_file),
             "CORTEX_TEST_RELEASE_FILE": str(release_file)},
        stdout=subprocess.PIPE, text=True,
    )

    # Wait until A provably holds the lock (covers slow cold-start imports).
    deadline = time.perf_counter() + 25
    while not ready_file.exists() and time.perf_counter() < deadline:
        if proc_a.poll() is not None:
            break
        time.sleep(0.05)
    assert ready_file.exists(), "writer A never acquired the lock"

    proc_b = subprocess.Popen(
        [sys.executable, str(WORKER), str(db_path), "B", "5", "0", "0"],
        env={**os.environ, "CORTEX_WRITE_LOCK_PATH": str(lock_path),
             "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "0.5"},
        stdout=subprocess.PIPE, text=True,
    )
    out_b, _ = proc_b.communicate(timeout=30)

    # B has finished its attempt (fail-closed); let A release and complete.
    release_file.write_text("go", encoding="utf-8")
    out_a, _ = proc_a.communicate(timeout=30)

    outcomes = {out_a.strip().splitlines()[-1], out_b.strip().splitlines()[-1]}
    assert "OK" in {o.split(":")[0] for o in outcomes}, outcomes
    assert "LOCKED" in {o.split(":")[0] for o in outcomes}, outcomes
    # exactly one OK, one LOCKED - never both OK, never both LOCKED
    ok_count = sum(1 for o in outcomes if o.startswith("OK"))
    locked_count = sum(1 for o in outcomes if o.startswith("LOCKED"))
    assert ok_count == 1, outcomes
    assert locked_count == 1, outcomes

    client = create_persistent_client(db_path)
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

    client = create_persistent_client(db_path)
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

    t0 = time.perf_counter()
    client = create_persistent_client(db_path)
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

    result = _run_worker(db_path, lock_path, "next", 4, 0, timeout_seconds=3)

    outcome = result.stdout.strip().splitlines()[-1]
    assert outcome.startswith("OK")
    lock_wait_seconds = float(outcome.split(":")[2])
    assert lock_wait_seconds < 0.5  # OS lock released promptly after hard kill

    client = create_persistent_client(db_path)
    collection = client.get_or_create_collection(name="test")
    assert collection.count() == 4  # victim never wrote anything (killed before its upsert)
