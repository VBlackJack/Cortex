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
"""Source-specific OS lock that prevents overlapping ingestion attempts."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import filelock

from ingestion.storage import IngestionStorage

_LOG = logging.getLogger("cortex.ingestion.locking")


class IngestionLockedError(RuntimeError):
    """Raised before execution when another source attempt owns the lock."""


@contextmanager
def source_sync_lock(
    storage: IngestionStorage,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    """Acquire one OS-released lock for a complete source attempt."""
    storage.lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = filelock.FileLock(storage.lock_path, timeout=timeout_seconds)
    try:
        with lock.acquire(timeout=timeout_seconds):
            _LOG.info("ingestion_lock_acquired source_kind=%s", storage.source_kind)
            yield
    except filelock.Timeout as exc:
        _LOG.warning(
            "ingestion_lock_timeout source_kind=%s timeout_s=%s",
            storage.source_kind,
            timeout_seconds,
        )
        raise IngestionLockedError(
            "Another ingestion attempt is already running for this source kind."
        ) from exc


__all__ = ["IngestionLockedError", "source_sync_lock"]
