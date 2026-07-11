# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Single-writer guarantee for the Chroma index.

Every Chroma write entry point acquires chroma_write_lock() before touching
the DB. The lock is an OS-level advisory file lock (filelock), auto-released
by the OS if the holding process dies - no manual staleness cleanup, no
permanent deadlock. On contention, acquisition fails closed after a bounded
timeout: CortexWriteLockedError is raised, no write is attempted. Read paths
(cortex_search, cortex_freshness) never call this - Chroma reads are safe
under concurrent access.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import filelock

from config import CORTEX_WRITE_LOCK_PATH, CORTEX_WRITE_LOCK_TIMEOUT_SECONDS

_LOG = logging.getLogger("cortex.write_lock")

# One instance for the whole process: filelock.FileLock is reentrant on the
# same instance (nested "with" blocks in one process stack a counter and
# only release the OS lock when the outermost exits), which is what lets a
# multi-step driver (e.g. scripts/b2_sync_vault.py looping over sections)
# wrap its whole run while each inner write function's own lock nests inside
# it without deadlocking. A module-level singleton is required for this -
# two separate FileLock objects on the same path do not share the counter.
_LOCK = filelock.FileLock(CORTEX_WRITE_LOCK_PATH, timeout=CORTEX_WRITE_LOCK_TIMEOUT_SECONDS)


class CortexWriteLockedError(RuntimeError):
    """Raised when the Chroma write lock could not be acquired in time.

    Another process is presumed to be writing to the index. The caller must
    not proceed to write - this exception means no write was attempted.
    """


@contextmanager
def chroma_write_lock() -> Iterator[None]:
    """Acquire the exclusive Chroma write lock for the duration of the block.

    Fails closed: raises CortexWriteLockedError immediately if the lock is
    not acquired within CORTEX_WRITE_LOCK_TIMEOUT_SECONDS. Never waits
    unbounded.
    """
    try:
        with _LOCK.acquire(timeout=CORTEX_WRITE_LOCK_TIMEOUT_SECONDS):
            yield
    except filelock.Timeout as exc:
        _LOG.warning(
            "chroma_write_lock_timeout path=%s timeout_s=%s - another writer "
            "is presumed active; refusing to write",
            CORTEX_WRITE_LOCK_PATH,
            CORTEX_WRITE_LOCK_TIMEOUT_SECONDS,
        )
        raise CortexWriteLockedError(
            f"Cortex write lock held by another process (timeout after "
            f"{CORTEX_WRITE_LOCK_TIMEOUT_SECONDS}s). Refusing to write - "
            "try again once the other writer finishes."
        ) from exc
