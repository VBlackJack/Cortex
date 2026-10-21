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
"""Client side of the daemon protocol, shared by the relay and `cortex daemon`.

Nothing here imports the server, the indexer or the resolved configuration: the relay
must stay a light process.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import filelock

from _version import __version__
from daemon_contract import (
    DAEMON_DIRECTORY_NAME,
    DAEMON_EXIT_POLL_SECONDS,
    DAEMON_LOCK_FILE_NAME,
    FRAME_ACCEPTED,
    HANDSHAKE_TIMEOUT_SECONDS,
    OPENING_FRAME_MAX_BYTES,
    PROTOCOL_VERSION,
    SOCKET_FILE_MODE,
    TOKEN_BYTES,
    TOKEN_FILE_NAME,
    DaemonFrameError,
    FrameKind,
    decode_frame,
    encode_frame,
    environment_fingerprint,
)
from daemon_transport import (
    Connection,
    EndpointUnavailableError,
    FrameTooLargeError,
    connect,
    endpoint_address,
    read_line,
)
from user_config import local_data_home

# Windows process creation flags for a daemon that must outlive the MCP client that
# started its relay: no console, its own process group, and out of the client's job.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


class DaemonRejectedError(RuntimeError):
    """The daemon answered the opening frame with a rejection."""

    def __init__(self, reason: str, reply: Mapping[str, Any]) -> None:
        super().__init__(f"daemon rejected the connection: {reason}")
        self.reason = reason
        self.reply = dict(reply)


@dataclass(frozen=True)
class DaemonPaths:
    """Files of the daemon inside the data home."""

    directory: Path
    lock: Path
    token: Path

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> DaemonPaths:
        directory = local_data_home(environ) / DAEMON_DIRECTORY_NAME
        return cls(
            directory=directory,
            lock=directory / DAEMON_LOCK_FILE_NAME,
            token=directory / TOKEN_FILE_NAME,
        )


def daemon_address(environ: Mapping[str, str]) -> str:
    """Return the endpoint of this user's daemon for the given environment."""
    return endpoint_address(environ, local_data_home(environ))


def write_token(paths: DaemonPaths) -> str:
    """Write a fresh random session token atomically and return it."""
    token = secrets.token_hex(TOKEN_BYTES)
    paths.directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".token.", dir=paths.directory)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(token)
        if os.name != "nt":
            os.chmod(temporary, SOCKET_FILE_MODE)
        os.replace(temporary, paths.token)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return token


def read_token(paths: DaemonPaths) -> str | None:
    """Return the current session token, or None when no daemon wrote one."""
    try:
        return paths.token.read_text(encoding="ascii").strip() or None
    except OSError:
        return None


def daemon_lock_held(paths: DaemonPaths) -> bool:
    """Return whether a daemon holds the single-instance lock right now."""
    if not paths.lock.exists():
        return False
    probe = filelock.FileLock(paths.lock, timeout=0)
    try:
        probe.acquire(timeout=0)
    except filelock.Timeout:
        return True
    probe.release()
    return False


def opening_frame(kind: FrameKind, token: str, environ: Mapping[str, str]) -> dict[str, Any]:
    """Build the client opening frame."""
    return {
        "protocol": PROTOCOL_VERSION,
        "product_version": __version__,
        "kind": kind,
        "token": token,
        "environment": environment_fingerprint(environ),
    }


async def exchange_opening(connection: Connection, frame: Mapping[str, Any]) -> dict[str, Any]:
    """Send the opening frame and return the daemon's accepted reply."""
    connection.writer.write(encode_frame(frame))
    await connection.writer.drain()
    try:
        line = await asyncio.wait_for(
            read_line(connection.reader, OPENING_FRAME_MAX_BYTES),
            HANDSHAKE_TIMEOUT_SECONDS,
        )
    except (TimeoutError, FrameTooLargeError) as exc:
        raise DaemonFrameError("daemon reply missing or too large") from exc
    if line is None:
        raise EndpointUnavailableError("daemon closed the connection during the handshake")
    reply = decode_frame(line)
    if reply.get("status") != FRAME_ACCEPTED:
        raise DaemonRejectedError(str(reply.get("reason")), reply)
    return reply


async def open_daemon(
    kind: FrameKind,
    environ: Mapping[str, str],
    *,
    connect_timeout: float = HANDSHAKE_TIMEOUT_SECONDS,
) -> tuple[Connection, dict[str, Any]]:
    """Connect to the daemon and complete the opening exchange for `kind`.

    Raises EndpointUnavailableError when no daemon answers, EndpointForeignError when
    another process holds the endpoint, DaemonRejectedError on a rejection, and
    DaemonFrameError on a reply that is not protocol version 1.
    """
    paths = DaemonPaths.from_environ(environ)
    token = read_token(paths)
    if token is None:
        raise EndpointUnavailableError("no daemon token")
    try:
        connection = await asyncio.wait_for(connect(daemon_address(environ)), connect_timeout)
    except TimeoutError as exc:
        raise EndpointUnavailableError("daemon endpoint busy") from exc
    try:
        reply = await exchange_opening(connection, opening_frame(kind, token, environ))
    except BaseException:
        await connection.close()
        raise
    return connection, reply


def daemon_command_line() -> list[str]:
    """Return the command that runs the daemon with this very installation."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "daemon", "run"]
    return [sys.executable, str(Path(__file__).resolve().with_name("cli.py")), "daemon", "run"]


def spawn_detached_daemon(environ: Mapping[str, str]) -> None:
    """Start `cortex daemon run` outside the caller's console, process group and job."""
    arguments: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": dict(environ),
        "cwd": str(Path(daemon_command_line()[0]).parent),
    }
    command = daemon_command_line()
    if sys.platform == "win32":
        flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(  # noqa: S603 -- our own executable, fixed arguments.
                command, creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB, **arguments
            )
        except OSError:
            # The client's job forbids breakaway: the daemon then shares its fate.
            subprocess.Popen(command, creationflags=flags, **arguments)  # noqa: S603
        return
    subprocess.Popen(command, start_new_session=True, **arguments)  # noqa: S603


def wait_for_daemon_exit(paths: DaemonPaths, timeout: float) -> bool:
    """Wait until no daemon holds the single-instance lock; False on timeout."""
    deadline = time.monotonic() + timeout
    while daemon_lock_held(paths):
        if time.monotonic() >= deadline:
            return False
        time.sleep(DAEMON_EXIT_POLL_SECONDS)
    return True


__all__ = [
    "DaemonPaths",
    "DaemonRejectedError",
    "daemon_address",
    "daemon_command_line",
    "daemon_lock_held",
    "exchange_opening",
    "open_daemon",
    "opening_frame",
    "read_token",
    "spawn_detached_daemon",
    "wait_for_daemon_exit",
    "write_token",
]
