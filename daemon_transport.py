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
"""Per-user local endpoint of the shared daemon: never a TCP socket.

Windows: a named pipe created through pywin32 with an explicit DACL that grants access
to the current user's SID only, the first instance created with
FILE_FLAG_FIRST_PIPE_INSTANCE and every instance with PIPE_REJECT_REMOTE_CLIENTS. The
pipe handles are driven by the asyncio proactor, the same machinery as
`loop.start_serving_pipe`, which cannot take a security descriptor itself.

Elsewhere: a Unix domain socket in a 0700 directory owned by the current user, the
socket itself 0600, with the peer's uid checked on every connection where the platform
exposes it.

Both sides check the peer: the daemon refuses a client process of another user, and a
client refuses an endpoint served by another user's process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import struct
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daemon_contract import (
    PIPE_BUFFER_BYTES,
    PIPE_NAME_TEMPLATE,
    PROTOCOL_VERSION,
    SOCKET_DIRECTORY_MODE,
    SOCKET_FALLBACK_DIRECTORY_NAME,
    SOCKET_FILE_MODE,
    SOCKET_FILE_TEMPLATE,
    SOCKET_RUNTIME_DIRECTORY_NAME,
    SOCKET_UMASK,
    STREAM_READ_LIMIT_BYTES,
    UNIX_SOCKET_PATH_MAX_BYTES,
    endpoint_suffix,
)

_LOG = logging.getLogger("cortex.daemon.transport")

# Win32 error codes this module distinguishes.
_ERROR_ACCESS_DENIED = 5
_ERROR_PIPE_BUSY = 231
# Linux SO_PEERCRED and macOS LOCAL_PEERCRED layouts.
_LINUX_PEERCRED_FORMAT = "3i"
_MACOS_SOL_LOCAL = 0
_MACOS_LOCAL_PEERCRED = 1
_MACOS_XUCRED_FORMAT = "IIh16I"


class EndpointUnavailableError(OSError):
    """Nothing is listening on the endpoint (no daemon, or one that is exiting)."""


class EndpointForeignError(RuntimeError):
    """The endpoint is held by a process that is not this user's Cortex daemon."""


class FrameTooLargeError(ValueError):
    """A line exceeded its size bound; the connection must be closed."""


@dataclass
class Connection:
    """One accepted or opened stream pair, with the peer process id when known."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    peer_pid: int | None

    async def close(self) -> None:
        """Close the stream without raising on an already broken connection."""
        self.writer.close()
        with contextlib.suppress(OSError, ConnectionError, asyncio.CancelledError):
            await self.writer.wait_closed()


ConnectionHandler = Callable[[Connection], Awaitable[None]]


async def read_line(reader: asyncio.StreamReader, limit: int) -> bytes | None:
    """Read one newline-terminated line of at most `limit` bytes; None at end of stream.

    A line longer than the bound raises FrameTooLargeError. Bytes left without a final
    newline at end of stream are dropped as an incomplete message.
    """
    try:
        line = await reader.readline()
    except ValueError as exc:  # asyncio's buffer limit was overrun.
        raise FrameTooLargeError("line exceeds the stream buffer limit") from exc
    if not line or not line.endswith(b"\n"):
        return None
    if len(line) > limit:
        raise FrameTooLargeError("line exceeds its size bound")
    return line


# -- Identity --------------------------------------------------------------------


def _windows_process_sid(process_id: int | None = None) -> str:
    import win32api
    import win32con
    import win32security

    if process_id is None:
        process = win32api.GetCurrentProcess()
    else:
        process = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id
        )
    token = win32security.OpenProcessToken(process, win32security.TOKEN_QUERY)
    sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    return str(win32security.ConvertSidToStringSid(sid))


def current_user_sid() -> str:
    """Return the string SID of the user running this process (Windows only)."""
    return _windows_process_sid()


def _same_windows_user(process_id: int) -> bool:
    try:
        return _windows_process_sid(process_id) == current_user_sid()
    except Exception:  # noqa: BLE001 -- an unreadable peer is a refused peer.
        _LOG.warning("daemon_peer_identity_unreadable pid=%s", process_id)
        return False


def _unix_peer(sock: socket.socket) -> tuple[int | None, int | None]:
    """Return (pid, uid) of the socket peer where the platform exposes them."""
    if sys.platform == "win32":
        return None, None
    if sys.platform.startswith("linux"):
        size = struct.calcsize(_LINUX_PEERCRED_FORMAT)
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
        pid, uid, _gid = struct.unpack(_LINUX_PEERCRED_FORMAT, raw)
        return int(pid), int(uid)
    if sys.platform == "darwin":
        size = struct.calcsize(_MACOS_XUCRED_FORMAT)
        raw = sock.getsockopt(_MACOS_SOL_LOCAL, _MACOS_LOCAL_PEERCRED, size)
        fields = struct.unpack(_MACOS_XUCRED_FORMAT, raw)
        return None, int(fields[1])
    return None, None


def _unix_peer_allowed(writer: asyncio.StreamWriter) -> tuple[bool, int | None]:
    if sys.platform == "win32":
        return False, None
    sock = writer.get_extra_info("socket")
    if sock is None:
        return False, None
    try:
        pid, uid = _unix_peer(sock)
    except OSError:
        _LOG.warning("daemon_peer_identity_unreadable")
        return False, None
    # Without peer credentials, the 0700 directory is the access control.
    return uid is None or uid == os.getuid(), pid


# -- Addresses -------------------------------------------------------------------


def _socket_directory(environ: Mapping[str, str], data_home: Path) -> Path:
    runtime = environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime:
        return Path(runtime) / SOCKET_RUNTIME_DIRECTORY_NAME
    return data_home / SOCKET_FALLBACK_DIRECTORY_NAME


def endpoint_address(environ: Mapping[str, str], data_home: Path) -> str:
    """Return the endpoint name for this user: a pipe name or a socket path."""
    suffix = endpoint_suffix(environ)
    if sys.platform == "win32":
        return PIPE_NAME_TEMPLATE.format(
            sid=current_user_sid(), protocol=PROTOCOL_VERSION, suffix=suffix
        )
    path = _socket_directory(environ, data_home) / SOCKET_FILE_TEMPLATE.format(
        protocol=PROTOCOL_VERSION, suffix=suffix
    )
    if len(os.fsencode(path)) > UNIX_SOCKET_PATH_MAX_BYTES:
        raise ValueError(f"socket path is too long for the platform: {path}")
    return str(path)


# -- Windows server ----------------------------------------------------------------


def _windows_security_attributes() -> Any:
    import ntsecuritycon
    import win32security

    sid = win32security.ConvertStringSidToSid(current_user_sid())
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, sid)
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(sid, False)
    descriptor.SetSecurityDescriptorDacl(True, dacl, False)
    attributes = win32security.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    attributes.bInheritHandle = False
    return attributes


def _create_pipe_instance(address: str, attributes: Any, *, first: bool) -> Any:
    if sys.platform != "win32":
        raise OSError("named pipes exist only on Windows")
    from asyncio import windows_utils

    import pywintypes
    import win32file
    import win32pipe

    open_mode = win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED
    if first:
        open_mode |= win32pipe.FILE_FLAG_FIRST_PIPE_INSTANCE
    pipe_mode = (
        win32pipe.PIPE_TYPE_BYTE
        | win32pipe.PIPE_READMODE_BYTE
        | win32pipe.PIPE_WAIT
        | win32pipe.PIPE_REJECT_REMOTE_CLIENTS
    )
    try:
        handle = win32pipe.CreateNamedPipe(
            address,
            open_mode,
            pipe_mode,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            PIPE_BUFFER_BYTES,
            PIPE_BUFFER_BYTES,
            0,
            attributes,
        )
    except pywintypes.error as exc:
        if exc.winerror in {_ERROR_ACCESS_DENIED, _ERROR_PIPE_BUSY}:
            raise EndpointForeignError(f"pipe name already held: {address}") from exc
        raise
    return windows_utils.PipeHandle(handle.Detach())


class Listener:
    """Accepts connections on the endpoint until closed."""

    def __init__(self, address: str, handler: ConnectionHandler) -> None:
        self.address = address
        self._handler = handler
        self._closed = False
        self._task: asyncio.Task[None] | None = None
        self._pending: Any = None
        self._attributes: Any = None
        self._unix_server: asyncio.AbstractServer | None = None
        self.connections: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Take the endpoint; raises EndpointForeignError when another process holds it."""
        if sys.platform == "win32":
            self._attributes = _windows_security_attributes()
            self._pending = _create_pipe_instance(self.address, self._attributes, first=True)
            self._task = asyncio.create_task(self._accept_pipes())
        else:
            await self._start_unix()

    def _spawn(self, connection: Connection) -> None:
        task = asyncio.create_task(self._run_handler(connection))
        self.connections.add(task)
        task.add_done_callback(self.connections.discard)

    async def _run_handler(self, connection: Connection) -> None:
        try:
            await self._handler(connection)
        finally:
            await connection.close()

    async def _accept_pipes(self) -> None:
        import win32pipe

        loop = asyncio.get_running_loop()
        proactor = getattr(loop, "_proactor")  # noqa: B009 -- the proactor drives pipes.
        while not self._closed:
            pipe = self._pending
            try:
                await proactor.accept_pipe(pipe)
            except (OSError, asyncio.CancelledError):
                if self._closed:
                    return
                _LOG.warning("daemon_pipe_accept_failed")
                pipe.close()
                self._pending = _create_pipe_instance(
                    self.address, self._attributes, first=False
                )
                continue
            # A new listening instance before anything else keeps the name owned.
            self._pending = _create_pipe_instance(self.address, self._attributes, first=False)
            try:
                peer_pid = int(win32pipe.GetNamedPipeClientProcessId(pipe.handle))
            except Exception:  # noqa: BLE001 -- an unidentifiable client is refused.
                peer_pid = -1
            if peer_pid < 0 or not _same_windows_user(peer_pid):
                _LOG.warning("daemon_peer_refused pid=%s", peer_pid)
                pipe.close()
                continue
            reader = asyncio.StreamReader(limit=STREAM_READ_LIMIT_BYTES, loop=loop)
            protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
            make_transport = getattr(loop, "_make_duplex_pipe_transport")  # noqa: B009
            transport = make_transport(pipe, protocol)
            writer = asyncio.StreamWriter(transport, protocol, reader, loop)
            self._spawn(Connection(reader, writer, peer_pid))

    async def _start_unix(self) -> None:
        if sys.platform == "win32":
            return
        path = Path(self.address)
        directory = path.parent
        directory.mkdir(mode=SOCKET_DIRECTORY_MODE, parents=True, exist_ok=True)
        status = directory.stat()
        if status.st_uid != os.getuid():
            raise EndpointForeignError(f"socket directory owned by another user: {directory}")
        os.chmod(directory, SOCKET_DIRECTORY_MODE)
        if path.exists():
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(str(path))
            except OSError:
                path.unlink()  # A stale socket from a daemon that died.
            else:
                raise EndpointForeignError(f"socket already served: {path}")
            finally:
                probe.close()

        async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            allowed, pid = _unix_peer_allowed(writer)
            connection = Connection(reader, writer, pid)
            if not allowed:
                _LOG.warning("daemon_peer_refused pid=%s", pid)
                await connection.close()
                return
            task = asyncio.current_task()
            if task is not None:
                self.connections.add(task)
            try:
                await self._handler(connection)
            finally:
                if task is not None:
                    self.connections.discard(task)
                await connection.close()

        previous = os.umask(SOCKET_UMASK)
        try:
            self._unix_server = await asyncio.start_unix_server(
                accept, path=str(path), limit=STREAM_READ_LIMIT_BYTES
            )
        finally:
            os.umask(previous)
        os.chmod(path, SOCKET_FILE_MODE)

    def _close_pending(self) -> None:
        pending, self._pending = self._pending, None
        if pending is not None:
            pending.close()

    async def aclose(self) -> None:
        """Stop accepting and wait until the listening instance is released."""
        self.close()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._close_pending()

    def close(self) -> None:
        """Stop accepting; connections already accepted keep running."""
        self._closed = True
        if self._task is not None and not self._task.done():
            # Cancel the pending accept first, so the proactor cancels its overlapped
            # operation on a live handle; the handle is closed once that is done.
            self._task.cancel()
            self._task.add_done_callback(lambda _task: self._close_pending())
        else:
            self._close_pending()
        if self._unix_server is not None:
            self._unix_server.close()
            with contextlib.suppress(OSError):
                Path(self.address).unlink()


# -- Client ----------------------------------------------------------------------


async def connect(address: str) -> Connection:
    """Open the endpoint and check that the serving process belongs to this user."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=STREAM_READ_LIMIT_BYTES, loop=loop)
    if sys.platform == "win32":
        import win32pipe

        try:
            transport, _protocol = await loop.create_pipe_connection(  # type: ignore[attr-defined]
                lambda: asyncio.StreamReaderProtocol(reader, loop=loop), address
            )
        except FileNotFoundError as exc:
            raise EndpointUnavailableError(str(exc)) from exc
        except PermissionError as exc:
            raise EndpointForeignError(f"pipe refused this user: {address}") from exc
        protocol = transport.get_protocol()
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        pipe = transport.get_extra_info("pipe")
        try:
            server_pid = int(win32pipe.GetNamedPipeServerProcessId(pipe.handle))
        except Exception as exc:  # noqa: BLE001 -- an unidentifiable server is foreign.
            writer.close()
            raise EndpointForeignError("pipe server is unidentifiable") from exc
        if not _same_windows_user(server_pid):
            writer.close()
            raise EndpointForeignError(f"pipe served by another user, pid={server_pid}")
        return Connection(reader, writer, server_pid)
    path = Path(address)
    if path.parent.exists() and path.parent.stat().st_uid != os.getuid():
        raise EndpointForeignError(f"socket directory owned by another user: {path.parent}")
    try:
        reader, writer = await asyncio.open_unix_connection(
            str(path), limit=STREAM_READ_LIMIT_BYTES
        )
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        raise EndpointUnavailableError(str(exc)) from exc
    except PermissionError as exc:
        raise EndpointForeignError(f"socket refused this user: {path}") from exc
    allowed, pid = _unix_peer_allowed(writer)
    if not allowed:
        writer.close()
        raise EndpointForeignError("socket served by another user")
    return Connection(reader, writer, pid)


__all__ = [
    "Connection",
    "ConnectionHandler",
    "EndpointForeignError",
    "EndpointUnavailableError",
    "FrameTooLargeError",
    "Listener",
    "connect",
    "current_user_sid",
    "endpoint_address",
    "read_line",
]
