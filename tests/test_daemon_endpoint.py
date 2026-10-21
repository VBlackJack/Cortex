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
"""Cross-process proofs of the daemon endpoint on every platform, without a model.

The daemon runs in its own process with a fake MCP server (tests/fixtures/
fake_daemon.py), so these tests need no embedding model and run on a fresh CI
runner: a named pipe on Windows, a Unix domain socket on Linux and macOS. They
prove the opening exchange, the peer identity read from the endpoint (SO_PEERCRED
on Linux), the socket and directory permissions, the stop and idle exits, and a
real `cortex serve` relay copying a request through the endpoint.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from daemon_client import (
    DaemonPaths,
    DaemonRejectedError,
    daemon_address,
    daemon_lock_held,
    exchange_opening,
    open_daemon,
    opening_frame,
)
from daemon_contract import ENDPOINT_SUFFIX_ENV
from daemon_transport import EndpointUnavailableError, connect

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not hasattr(socket, "AF_UNIX"),
    reason="the platform has neither named pipes nor Unix domain sockets",
)

_REPOSITORY = Path(__file__).resolve().parents[1]
_FAKE_DAEMON = Path(__file__).parent / "fixtures" / "fake_daemon.py"
_WAIT_SECONDS = 30.0
_POLL_SECONDS = 0.05
_SOCKET_MODE = 0o600
_DIRECTORY_MODE = 0o700


@dataclass
class FakeDaemon:
    """A daemon process with a fake server, in a throwaway data home."""

    environ: dict[str, str]
    process: subprocess.Popen[bytes]


def _environment(root: Path, idle_timeout_seconds: int) -> dict[str, str]:
    kb = root / "kb"
    kb.mkdir()
    config = root / "appdata" / "Cortex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        f"schema_version = 1\nkb_path = {json.dumps(str(kb))}\n"
        f'\n[server]\nmode = "shared"\nidle_timeout_seconds = {idle_timeout_seconds}\n',
        encoding="utf-8",
    )
    environ = {key: value for key, value in os.environ.items() if not key.startswith("CORTEX_")}
    environ.update(
        APPDATA=str(root / "appdata"),
        LOCALAPPDATA=str(root / "local"),
        **{ENDPOINT_SUFFIX_ENV: uuid.uuid4().hex[:12]},
    )
    if sys.platform != "win32":
        # A Unix socket path is limited to about 100 bytes: a short runtime
        # directory keeps it well inside, whatever the test temporary path is.
        environ["XDG_RUNTIME_DIR"] = str(root / "run")
    return environ


def _short_root() -> Path:
    base = None if sys.platform == "win32" else "/tmp"
    return Path(tempfile.mkdtemp(prefix="cx", dir=base))


async def _wait_running(environ: dict[str, str]) -> dict[str, Any]:
    deadline = time.monotonic() + _WAIT_SECONDS
    while True:
        try:
            connection, reply = await open_daemon("status", environ)
        except EndpointUnavailableError:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(_POLL_SECONDS)
            continue
        await connection.close()
        return reply


def _start(root: Path, idle_timeout_seconds: int = 0) -> FakeDaemon:
    environ = _environment(root, idle_timeout_seconds)
    options: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    process = subprocess.Popen(
        [sys.executable, str(_FAKE_DAEMON)],
        cwd=_REPOSITORY,
        env=environ,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **options,
    )
    return FakeDaemon(environ=environ, process=process)


def _stop(daemon: FakeDaemon) -> None:
    if daemon.process.poll() is None:
        with suppress(OSError):
            os.kill(daemon.process.pid, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        daemon.process.wait(_WAIT_SECONDS)
    if daemon.process.poll() is None:
        daemon.process.kill()
        daemon.process.wait(_WAIT_SECONDS)


@pytest.fixture
def fake_daemon() -> Iterator[FakeDaemon]:
    root = _short_root()
    daemon = _start(root)
    try:
        asyncio.run(_wait_running(daemon.environ))
        yield daemon
    finally:
        _stop(daemon)
        shutil.rmtree(root, ignore_errors=True)


async def test_session_and_status_cross_the_process_boundary(fake_daemon: FakeDaemon) -> None:
    status = await _wait_running(fake_daemon.environ)
    assert status["daemon"]["sessions"] == 0
    connection, reply = await open_daemon("session", fake_daemon.environ)
    try:
        if sys.platform != "darwin":
            # Windows reads the pipe server pid, Linux SO_PEERCRED; macOS
            # LOCAL_PEERCRED carries the uid only.
            assert connection.peer_pid == reply["pid"]
        connection.writer.write(b'{"jsonrpc":"2.0","id":3,"method":"tools/list"}\n')
        await connection.writer.drain()
        answer = json.loads(await asyncio.wait_for(connection.reader.readline(), _WAIT_SECONDS))
        assert answer == {"jsonrpc": "2.0", "id": 3, "result": {"method": "tools/list"}}
    finally:
        await connection.close()


async def test_wrong_token_is_rejected(fake_daemon: FakeDaemon) -> None:
    connection = await connect(daemon_address(fake_daemon.environ))
    try:
        with pytest.raises(DaemonRejectedError) as rejected:
            await exchange_opening(
                connection, opening_frame("session", "00" * 32, fake_daemon.environ)
            )
        assert rejected.value.reason == "bad_token"
    finally:
        await connection.close()


@pytest.mark.skipif(sys.platform == "win32", reason="the named pipe carries a DACL instead")
def test_socket_and_directory_are_private(fake_daemon: FakeDaemon) -> None:
    path = Path(daemon_address(fake_daemon.environ))
    assert stat.S_ISSOCK(path.stat().st_mode)
    assert stat.S_IMODE(path.stat().st_mode) == _SOCKET_MODE
    assert stat.S_IMODE(path.parent.stat().st_mode) == _DIRECTORY_MODE
    assert path.parent.stat().st_uid == os.getuid()
    token = DaemonPaths.from_environ(fake_daemon.environ).token
    assert stat.S_IMODE(token.stat().st_mode) == _SOCKET_MODE


async def test_stop_request_ends_the_process_and_frees_the_endpoint(
    fake_daemon: FakeDaemon,
) -> None:
    connection, _reply = await open_daemon("stop", fake_daemon.environ)
    await connection.close()
    assert await asyncio.to_thread(fake_daemon.process.wait, _WAIT_SECONDS) == 0
    assert not daemon_lock_held(DaemonPaths.from_environ(fake_daemon.environ))
    if sys.platform != "win32":
        assert not Path(daemon_address(fake_daemon.environ)).exists()
    with pytest.raises(EndpointUnavailableError):
        await open_daemon("status", fake_daemon.environ)


def test_idle_daemon_exits_cleanly_after_its_delay() -> None:
    root = _short_root()
    daemon = _start(root, idle_timeout_seconds=1)
    try:
        asyncio.run(_wait_running(daemon.environ))
        assert daemon.process.wait(_WAIT_SECONDS) == 0
    finally:
        _stop(daemon)
        shutil.rmtree(root, ignore_errors=True)


def test_relay_copies_a_request_through_the_endpoint(fake_daemon: FakeDaemon) -> None:
    relay = subprocess.Popen(
        [sys.executable, str(_REPOSITORY / "cli.py"), "serve"],
        cwd=_REPOSITORY,
        env=fake_daemon.environ,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    watchdog = threading.Timer(_WAIT_SECONDS, relay.kill)
    watchdog.start()
    try:
        assert relay.stdin is not None and relay.stdout is not None
        relay.stdin.write(b'{"jsonrpc":"2.0","id":"r1","method":"initialize","params":{}}\n')
        relay.stdin.flush()
        answer = json.loads(relay.stdout.readline())
        assert answer == {"jsonrpc": "2.0", "id": "r1", "result": {"method": "initialize"}}
        relay.stdin.close()
        assert relay.wait(_WAIT_SECONDS) == 0
    finally:
        watchdog.cancel()
        if relay.poll() is None:
            relay.kill()
            relay.wait(_WAIT_SECONDS)
