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
"""Shared daemon in one process: frames, endpoint, opening exchange, tools and readers.

The runtime here never loads the real server: its preparation is replaced by a small
fake, so the FastMCP instance and the indexer globals of the test process stay as they
are. The cross-process proofs live in test_daemon_processes.py.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anyio
import pytest

import daemon_contract
from _version import __version__
from daemon_client import exchange_opening, opening_frame
from daemon_contract import (
    MESSAGE_MAX_BYTES,
    OPENING_FRAME_MAX_BYTES,
    DaemonFrameError,
    decode_frame,
    encode_frame,
    endpoint_suffix,
    environment_fingerprint,
    parse_product_version,
)
from daemon_resources import HeldLexicalIndex, SharedIndex
from daemon_server import DaemonRuntime
from daemon_transport import (
    Connection,
    EndpointForeignError,
    FrameTooLargeError,
    Listener,
    connect,
    endpoint_address,
    read_line,
)

_TOKEN = "ab" * 32


def _environ(tmp_path: Path) -> dict[str, str]:
    environ = {
        "APPDATA": str(tmp_path / "appdata"),
        "LOCALAPPDATA": str(tmp_path / "local"),
        daemon_contract.ENDPOINT_SUFFIX_ENV: uuid.uuid4().hex[:16],
    }
    if sys.platform != "win32":
        # A Unix socket path is limited to about 100 bytes, and pytest's temporary
        # paths are long: the socket goes to a short private runtime directory.
        environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="cx", dir="/tmp")
    return environ


# -- Contract ------------------------------------------------------------------------


def test_frames_are_bounded_and_versioned() -> None:
    frame = {"protocol": 1, "kind": "status"}
    assert decode_frame(encode_frame(frame)) == frame
    with pytest.raises(DaemonFrameError):
        encode_frame({"protocol": 1, "pad": "x" * OPENING_FRAME_MAX_BYTES})
    with pytest.raises(DaemonFrameError, match="protocol"):
        decode_frame(b'{"protocol": 2}\n')
    with pytest.raises(DaemonFrameError):
        decode_frame(b"[1]\n")
    with pytest.raises(DaemonFrameError):
        decode_frame(b'{"protocol": 1}')


def test_environment_fingerprint_reads_only_configuration_variables() -> None:
    base = {"CORTEX_KB_PATH": "G:/kb", "APPDATA": "A", "PATH": "x"}
    assert environment_fingerprint(base) == environment_fingerprint({**base, "PATH": "y"})
    assert environment_fingerprint(base) != environment_fingerprint(
        {**base, "CORTEX_KB_PATH": "G:/other"}
    )
    assert environment_fingerprint(base) != environment_fingerprint({**base, "APPDATA": "B"})


def test_endpoint_suffix_is_validated() -> None:
    key = daemon_contract.ENDPOINT_SUFFIX_ENV
    assert endpoint_suffix({}) == ""
    assert endpoint_suffix({key: "abc_1"}) == "-abc_1"
    with pytest.raises(ValueError):
        endpoint_suffix({key: "../x"})


def test_product_versions_compare_numerically() -> None:
    newer = parse_product_version("2026.1021.10")
    older = parse_product_version("2026.1021.02")
    assert newer is not None and older is not None and newer > older
    assert parse_product_version("dev") is None


@pytest.mark.skipif(sys.platform != "win32", reason="named pipe naming")
def test_pipe_name_carries_the_user_sid_and_protocol(tmp_path: Path) -> None:
    from daemon_transport import current_user_sid

    address = endpoint_address({daemon_contract.ENDPOINT_SUFFIX_ENV: "t1"}, tmp_path)
    assert address == f"\\\\.\\pipe\\cortex-{current_user_sid()}-v1-t1"


# -- Endpoint ------------------------------------------------------------------------


async def test_endpoint_round_trip_identifies_the_peer_and_is_exclusive(
    tmp_path: Path,
) -> None:
    address = endpoint_address(_environ(tmp_path), tmp_path / "home")

    async def echo(connection: Connection) -> None:
        line = await read_line(connection.reader, MESSAGE_MAX_BYTES)
        assert line is not None
        connection.writer.write(b"echo " + line)
        await connection.writer.drain()

    listener = Listener(address, echo)
    await listener.start()
    try:
        rival = Listener(address, echo)
        with pytest.raises(EndpointForeignError):
            await rival.start()
        client = await connect(address)
        # Windows reads the pipe server pid and Linux SO_PEERCRED; macOS
        # LOCAL_PEERCRED carries the uid only.
        assert client.peer_pid == (None if sys.platform == "darwin" else os.getpid())
        client.writer.write(b"hello\n")
        await client.writer.drain()
        assert await client.reader.readline() == b"echo hello\n"
        await client.close()
    finally:
        await listener.aclose()


async def test_line_over_its_bound_is_refused() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"x" * 20 + b"\n")
    reader.feed_eof()
    with pytest.raises(FrameTooLargeError):
        await read_line(reader, 10)
    tail = asyncio.StreamReader()
    tail.feed_data(b"incomplete")
    tail.feed_eof()
    assert await read_line(tail, 100) is None


# -- Runtime with a fake server ----------------------------------------------------


class _FakeServer:
    SYNC_LOCKED_MESSAGE = "locked"

    @staticmethod
    async def run_session(read_stream: Any, write_stream: Any) -> None:
        from mcp.shared.message import SessionMessage
        from mcp.types import JSONRPCMessage, JSONRPCResponse

        async with read_stream, write_stream:
            async for item in read_stream:
                request = item.message.root
                response = JSONRPCResponse(jsonrpc="2.0", id=request.id, result={"ok": True})
                await write_stream.send(SessionMessage(JSONRPCMessage(response)))


class _Runtime:
    def __init__(self, tmp_path: Path, *, idle: int = 0) -> None:
        self.environ = _environ(tmp_path)
        self.config = tmp_path / "config.toml"
        self.config.write_text("schema_version = 1\n", encoding="utf-8")
        self.runtime = DaemonRuntime(
            environ=self.environ,
            address=endpoint_address(self.environ, tmp_path / "home"),
            token=_TOKEN,
            idle_timeout_seconds=idle,
            config_path=self.config,
        )
        self.runtime._prepare = lambda: _FakeServer  # type: ignore[assignment,method-assign,return-value]
        self.task: asyncio.Task[int] | None = None

    async def __aenter__(self) -> _Runtime:
        self.task = asyncio.create_task(self.runtime.main())
        for _ in range(100):
            try:
                connection = await connect(self.runtime.address)
            except Exception:  # noqa: BLE001 -- not listening yet.
                await asyncio.sleep(0.02)
            else:
                await connection.close()
                return self
        raise AssertionError("runtime never listened")

    async def __aexit__(self, *exc: object) -> None:
        assert self.task is not None
        self.runtime.request_drain("test")
        await asyncio.wait_for(self.task, 10)

    async def open(self, kind: str, token: str = _TOKEN) -> tuple[Connection, dict[str, Any]]:
        connection = await connect(self.runtime.address)
        frame = opening_frame(kind, token, self.environ)  # type: ignore[arg-type]
        try:
            return connection, await exchange_opening(connection, frame)
        except BaseException:
            await connection.close()
            raise


async def test_wrong_token_and_malformed_frames_are_rejected(tmp_path: Path) -> None:
    from daemon_client import DaemonRejectedError

    async with _Runtime(tmp_path) as runtime:
        with pytest.raises(DaemonRejectedError) as rejected:
            await runtime.open("session", token="cd" * 32)
        assert rejected.value.reason == "bad_token"

        connection = await connect(runtime.runtime.address)
        connection.writer.write(b'{"protocol": 9}\n')
        reply = json.loads(await connection.reader.readline())
        assert (reply["status"], reply["reason"]) == ("rejected", "unsupported_protocol")
        await connection.close()

        connection = await connect(runtime.runtime.address)
        connection.writer.write(b"not json\n")
        reply = json.loads(await connection.reader.readline())
        assert reply["reason"] == "malformed_frame"
        await connection.close()


async def test_status_and_session_go_through_the_opening_exchange(tmp_path: Path) -> None:
    async with _Runtime(tmp_path) as runtime:
        connection, reply = await runtime.open("status")
        await connection.close()
        assert reply["status"] == "accepted"
        assert reply["product_version"] == __version__
        assert reply["daemon"]["sessions"] == 0
        assert reply["environment"] == environment_fingerprint(runtime.environ)

        connection, _reply = await runtime.open("session")
        connection.writer.write(b'{"jsonrpc":"2.0","id":7,"method":"ping"}\n')
        await connection.writer.drain()
        answer = json.loads(await asyncio.wait_for(connection.reader.readline(), 5))
        assert answer == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}
        assert runtime.runtime.sessions == 1
        await connection.close()


async def test_stop_request_drains_and_ends_the_runtime(tmp_path: Path) -> None:
    async with _Runtime(tmp_path) as runtime:
        connection, _reply = await runtime.open("stop")
        await connection.close()
        assert runtime.task is not None
        assert await asyncio.wait_for(runtime.task, 10) == 0
        assert runtime.runtime.stop_reason == "stop"


async def test_draining_runtime_refuses_new_sessions(tmp_path: Path) -> None:
    from daemon_client import DaemonRejectedError

    async with _Runtime(tmp_path) as runtime:
        runtime.runtime.draining = True
        with pytest.raises(DaemonRejectedError) as rejected:
            await runtime.open("session")
        assert rejected.value.reason == "draining"


async def test_config_change_drains_the_runtime(tmp_path: Path) -> None:
    async with _Runtime(tmp_path) as runtime:
        runtime.config.write_text("schema_version = 1\n# changed\n", encoding="utf-8")
        assert runtime.task is not None
        await asyncio.wait_for(asyncio.shield(runtime.task), 10)
        assert runtime.runtime.stop_reason == "config_changed"


async def test_idle_runtime_stops_after_its_delay(tmp_path: Path) -> None:
    async with _Runtime(tmp_path, idle=1) as runtime:
        assert runtime.task is not None
        started = time.monotonic()
        await asyncio.wait_for(asyncio.shield(runtime.task), 10)
        assert runtime.runtime.stop_reason == "idle"
        assert time.monotonic() - started < 5


# -- Tool wrappers ---------------------------------------------------------------------


class _Index:
    def __init__(self) -> None:
        self.writers = 0

    def begin_write(self) -> None:
        self.writers += 1

    def end_write(self) -> None:
        self.writers -= 1


def _bare_runtime(tmp_path: Path) -> DaemonRuntime:
    config = tmp_path / "config.toml"
    config.write_text("schema_version = 1\n", encoding="utf-8")
    runtime = DaemonRuntime(
        environ={},
        address="unused",
        token=_TOKEN,
        idle_timeout_seconds=0,
        config_path=config,
    )
    runtime._server = _FakeServer  # type: ignore[assignment]
    runtime._index = _Index()
    return runtime


async def test_second_concurrent_sync_is_refused_like_a_locked_index(tmp_path: Path) -> None:
    runtime = _bare_runtime(tmp_path)
    release = threading.Event()
    entered = threading.Event()

    def slow_sync(section: str | None = None) -> str:
        entered.set()
        release.wait(10)
        return "done"

    tool = runtime._sync_tool(slow_sync)
    first = asyncio.create_task(tool(section=None))
    await asyncio.to_thread(entered.wait, 5)
    assert await tool(section=None) == "locked"
    assert runtime.status()["sync_running"] is True
    release.set()
    assert await first == "done"
    assert runtime.status()["sync_running"] is False
    assert runtime._index.writers == 0


async def test_read_tools_run_off_the_event_loop(tmp_path: Path) -> None:
    runtime = _bare_runtime(tmp_path)
    ticks = 0

    def slow_search(query: str) -> str:
        time.sleep(0.5)
        return query

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    beating = asyncio.create_task(heartbeat())
    assert await runtime._read_tool(slow_search)(query="q") == "q"
    beating.cancel()
    # The loop kept turning while the tool slept in its thread (timer resolution
    # and machine load only lower the count, never to zero).
    assert ticks >= 3
    assert runtime.in_flight == 0


async def test_reads_share_one_compute_slot(tmp_path: Path) -> None:
    runtime = _bare_runtime(tmp_path)
    active = 0
    peak = 0
    lock = threading.Lock()

    def read(query: str) -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return query

    tool = runtime._read_tool(read)
    async with anyio.create_task_group() as group:
        for index in range(4):
            group.start_soon(functools.partial(tool, query=str(index)))
    assert peak == daemon_contract.COMPUTE_CONCURRENCY


# -- Shared readers ------------------------------------------------------------------


class _Client:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_shared_index_reopens_only_after_an_observed_external_write(tmp_path: Path) -> None:
    chroma = tmp_path / "chroma"
    chroma.mkdir()
    database = chroma / "chroma.sqlite3"
    database.write_bytes(b"a")
    lock_path = str(tmp_path / "write.lock")
    opened: list[_Client] = []

    def factory() -> _Client:
        opened.append(_Client())
        return opened[-1]

    index = SharedIndex(chroma_path=chroma, write_lock_path=lock_path, factory=factory)
    first = index.client()
    assert index.client() is first

    import filelock

    database.write_bytes(b"ab")
    with filelock.FileLock(lock_path):
        # Another writer still holds the lock: keep the consistent old view.
        holder = threading.Thread(target=lambda: results.append(index.client()))
        results: list[_Client] = []
        holder.start()
        holder.join()
        assert results == [first]
    second = index.client()
    assert second is not first and first.closed
    assert index.reopen_count == 1

    index.begin_write()
    database.write_bytes(b"abc")
    assert index.client() is second
    index.end_write()
    # The daemon's own write went through this very client: no reopen after it.
    assert index.client() is second
    assert index.reopen_count == 1


def test_held_lexical_index_keeps_one_connection_until_the_file_changes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lexical.db"
    with closing(sqlite3.connect(path)) as setup:
        setup.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    index = HeldLexicalIndex(path)
    with index._read() as first:
        pass
    with index._read() as again:
        assert again is first
    connections: list[Any] = []
    worker = threading.Thread(target=lambda: connections.append(index.metadata()))
    worker.start()
    worker.join()
    assert connections == [{}]
    index.close()
    replacement = tmp_path / "next.db"
    with closing(sqlite3.connect(replacement)) as setup:
        setup.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    os.replace(replacement, path)
    with index._read() as reopened:
        assert reopened is not first
    index.close()


def test_status_counters_are_complete(tmp_path: Path) -> None:
    status = _bare_runtime(tmp_path).status()
    assert set(status) == {
        "pid",
        "product_version",
        "started_at",
        "uptime_seconds",
        "sessions",
        "in_flight",
        "sync_running",
        "draining",
        "idle_timeout_seconds",
    }
    assert SimpleNamespace(**status).pid == os.getpid()
