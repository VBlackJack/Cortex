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
"""Process-wide index readers for the shared daemon.

A long-lived Chroma client does not see vectors written by another process: Chroma
keeps one cached system per path, and its vector segment stays as it was loaded, while
counts and metadata, read from SQLite, already show the new rows. Measured on chromadb
1.5.7: after an external upsert, a query through the old client, and through a new
client object on the same path, still missed the new chunks; a client opened after the
system cache was dropped found them. The daemon therefore reopens its client once it
observes that the index files changed and the write lock is free again.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import filelock

from lexical_index import DEFAULT_LEXICAL_PATH, LexicalIndex

_LOG = logging.getLogger("cortex.daemon.resources")

CHROMA_SQLITE_FILE_NAMES = ("chroma.sqlite3", "chroma.sqlite3-wal")
"""Files whose size and modification time change on every Chroma write."""

_Signature = tuple[tuple[int, int] | None, ...]


class SharedIndex:
    """One Chroma client for the whole daemon, reopened after an external write.

    Callers serialize reads (the daemon's compute limiter allows one at a time), so a
    reopen never closes a client that another read is still using. A write by the
    daemon itself is bracketed by begin_write() and end_write(): it goes through this
    very client and needs no reopen while it runs.
    """

    def __init__(
        self,
        *,
        chroma_path: Path,
        write_lock_path: str,
        factory: Callable[[], Any],
    ) -> None:
        self._chroma_path = chroma_path
        self._write_lock_path = write_lock_path
        self._factory = factory
        self._guard = threading.Lock()
        self._client: Any = None
        self._signature: _Signature | None = None
        self._writers = 0
        self.reopen_count = 0

    def _current_signature(self) -> _Signature:
        signature: list[tuple[int, int] | None] = []
        for name in CHROMA_SQLITE_FILE_NAMES:
            try:
                status = (self._chroma_path / name).stat()
            except OSError:
                signature.append(None)
            else:
                signature.append((status.st_mtime_ns, status.st_size))
        return tuple(signature)

    def _external_writer_active(self) -> bool:
        probe = filelock.FileLock(self._write_lock_path, timeout=0)
        try:
            probe.acquire(timeout=0)
        except filelock.Timeout:
            return True
        except OSError:
            return True
        probe.release()
        return False

    def _open(self) -> None:
        # The signature is taken before opening, so a write that lands while the
        # client loads is seen as a change at the next read.
        self._signature = self._current_signature()
        self._client = self._factory()

    def _close(self) -> None:
        from chromadb.api.shared_system_client import SharedSystemClient

        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
        # Drop every cached system so the next client loads the segments from disk.
        SharedSystemClient.clear_system_cache()

    def client(self) -> Any:
        """Return the shared client, reopened first when another process wrote."""
        with self._guard:
            if self._client is None:
                self._open()
            elif (
                self._writers == 0
                and self._current_signature() != self._signature
                and not self._external_writer_active()
            ):
                self._close()
                self._open()
                self.reopen_count += 1
                _LOG.info("daemon_index_reopened count=%s", self.reopen_count)
            return self._client

    def begin_write(self) -> None:
        """Mark a write by this process; no reopen happens until end_write()."""
        with self._guard:
            self._writers += 1

    def end_write(self) -> None:
        """End a write by this process."""
        with self._guard:
            self._writers -= 1


def _shared_read_only_connection(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
    connection.execute("PRAGMA query_only = ON")
    return connection


class HeldLexicalIndex(LexicalIndex):
    """A lexical index that keeps one read-only connection for the whole process.

    The connection is reopened when the database file is replaced, and after any
    SQLite error. A lock serializes its use across worker threads.
    """

    def __init__(self, path: str | Path = DEFAULT_LEXICAL_PATH) -> None:
        super().__init__(path)
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None
        self._identity: tuple[int, int] | None = None

    def _file_identity(self) -> tuple[int, int] | None:
        try:
            status = self.path.stat()
        except OSError:
            return None
        return status.st_dev, status.st_ino

    def _drop(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            with contextlib.suppress(sqlite3.Error):
                connection.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            identity = self._file_identity()
            if self._connection is None or identity != self._identity:
                self._drop()
                self._connection = _shared_read_only_connection(self.path)
                self._identity = identity
            try:
                yield self._connection
            except sqlite3.Error:
                self._drop()
                raise

    def close(self) -> None:
        """Close the held connection."""
        with self._lock:
            self._drop()


__all__ = ["CHROMA_SQLITE_FILE_NAMES", "HeldLexicalIndex", "SharedIndex"]
