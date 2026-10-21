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
"""`cortex serve` in shared mode: a light relay between stdio and the per-user daemon.

The relay reaches the daemon, starting it detached when it is absent, within
RELAY_START_BUDGET_SECONDS, then copies JSON-RPC lines both ways unchanged. It reads
copies of them only to remember the `initialize` exchange and the requests still
waiting for an answer.

When the daemon connection closes:
- each request still in flight gets a JSON-RPC error instead of being replayed (a
  `cortex_sync` is never replayed blindly);
- the relay reconnects, replays the opening frame, the remembered `initialize` request
  (its answer is dropped, the client already has one) and the `initialized`
  notification, then carries on;
- after RELAY_FAILURE_LIMIT losses within RELAY_FAILURE_WINDOW_SECONDS, or when the
  daemon cannot be reached again, it serves the rest of the session in its own process
  through the same replay.

Before anything was read from stdin, every refusal (no daemon within the budget, an
endpoint held by a foreign process, another configuration environment, a newer daemon)
returns control to the caller, which then runs today's per-client server untouched.
The relay never takes over an endpoint.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Mapping
from typing import Any, Protocol

from _version import __version__
from daemon_client import (
    DaemonPaths,
    DaemonRejectedError,
    daemon_lock_held,
    open_daemon,
    spawn_detached_daemon,
)
from daemon_contract import (
    FRAME_KIND_DRAIN,
    FRAME_KIND_SESSION,
    HANDSHAKE_TIMEOUT_SECONDS,
    JSONRPC_VERSION,
    MESSAGE_MAX_BYTES,
    REJECT_DRAINING,
    REJECT_TOKEN,
    RELAY_FAILURE_LIMIT,
    RELAY_FAILURE_WINDOW_SECONDS,
    RELAY_INTERRUPTED_ERROR_CODE,
    RELAY_INTERRUPTED_MESSAGE,
    RELAY_RETRY_INITIAL_DELAY_SECONDS,
    RELAY_RETRY_MAX_DELAY_SECONDS,
    RELAY_SPAWN_INTERVAL_SECONDS,
    RELAY_START_BUDGET_SECONDS,
    DaemonFrameError,
    environment_fingerprint,
    parse_product_version,
)
from daemon_transport import (
    Connection,
    EndpointForeignError,
    EndpointUnavailableError,
    FrameTooLargeError,
    read_line,
)

_LOG = logging.getLogger("cortex.relay")

_INITIALIZE_METHOD = "initialize"
_INITIALIZED_NOTIFICATION = "notifications/initialized"


class Backend(Protocol):
    """One side that serves the MCP session: the daemon or this very process."""

    async def send(self, line: bytes) -> bool: ...

    async def receive(self) -> bytes | None: ...

    async def close(self) -> None: ...


class PipeBackend:
    """The daemon, through an accepted session connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    async def send(self, line: bytes) -> bool:
        try:
            self._connection.writer.write(line)
            await self._connection.writer.drain()
        except (ConnectionError, OSError):
            return False
        return True

    async def receive(self) -> bytes | None:
        try:
            return await read_line(self._connection.reader, MESSAGE_MAX_BYTES)
        except FrameTooLargeError:
            _LOG.warning("relay_message_too_large limit=%s", MESSAGE_MAX_BYTES)
            return None
        except (ConnectionError, OSError):
            return None

    async def close(self) -> None:
        await self._connection.close()


class InProcessBackend:
    """The MCP server of this process, used once the daemon is given up."""

    def __init__(self) -> None:
        self._inbound: Any = None
        self._outbound: Any = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        def load() -> Any:
            from offline_models import activate_if_embedded

            activate_if_embedded()
            import server

            server.share_reopening_index()
            return server

        server = await asyncio.to_thread(load)
        import anyio
        from mcp.shared.message import SessionMessage

        self._inbound, read_stream = anyio.create_memory_object_stream[
            SessionMessage | Exception
        ](0)
        write_stream, self._outbound = anyio.create_memory_object_stream[SessionMessage](0)
        self._task = asyncio.create_task(server.run_session(read_stream, write_stream))

    async def send(self, line: bytes) -> bool:
        import anyio
        import mcp.types as types
        from mcp.shared.message import SessionMessage

        try:
            message = types.JSONRPCMessage.model_validate_json(line)
        except Exception as exc:  # noqa: BLE001 -- the session answers a malformed line.
            item: SessionMessage | Exception = exc
        else:
            item = SessionMessage(message)
        try:
            await self._inbound.send(item)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            return False
        return True

    async def receive(self) -> bytes | None:
        import anyio

        try:
            item = await self._outbound.receive()
        except (anyio.EndOfStream, anyio.ClosedResourceError):
            return None
        payload: str = item.message.model_dump_json(by_alias=True, exclude_none=True)
        return payload.encode("utf-8") + b"\n"

    async def close(self) -> None:
        if self._inbound is not None:
            await self._inbound.aclose()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task


def _request_key(message: Mapping[str, Any]) -> str | None:
    """Return a stable key for a request id, or None for a notification."""
    if "id" not in message or message.get("id") is None:
        return None
    return json.dumps(message["id"], sort_keys=True)


def _parse(line: bytes) -> dict[str, Any] | None:
    try:
        message = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return message if isinstance(message, dict) else None


class Relay:
    """Carry one MCP client's stdio session to the daemon, or to this process."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = dict(environ)
        self._paths = DaemonPaths.from_environ(self._environ)
        self._environment = environment_fingerprint(self._environ)
        self._initialize: bytes | None = None
        self._initialize_key: str | None = None
        self._initialized: bytes | None = None
        self._in_flight: dict[str, bytes] = {}
        self._failures: collections.deque[float] = collections.deque()
        self._lines: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.in_process = False

    # -- Reaching the daemon ---------------------------------------------------

    def _maybe_spawn(self, last_spawn: float) -> float:
        now = time.monotonic()
        if now - last_spawn < RELAY_SPAWN_INTERVAL_SECONDS or daemon_lock_held(self._paths):
            return last_spawn
        _LOG.info("relay_daemon_spawn")
        try:
            spawn_detached_daemon(self._environ)
        except OSError:
            _LOG.warning("relay_daemon_spawn_failed", exc_info=True)
        return now

    async def _ask_drain(self) -> None:
        try:
            connection, _reply = await open_daemon(FRAME_KIND_DRAIN, self._environ)
        except (EndpointUnavailableError, EndpointForeignError, DaemonRejectedError,
                DaemonFrameError):
            return
        await connection.close()

    async def connect(self) -> Connection | None:
        """Reach a daemon of this version and environment within the budget, or None."""
        deadline = time.monotonic() + RELAY_START_BUDGET_SECONDS
        last_spawn = float("-inf")
        delay = RELAY_RETRY_INITIAL_DELAY_SECONDS
        mine = parse_product_version(__version__)
        while time.monotonic() < deadline:
            remaining = max(deadline - time.monotonic(), RELAY_RETRY_INITIAL_DELAY_SECONDS)
            try:
                connection, reply = await open_daemon(
                    FRAME_KIND_SESSION,
                    self._environ,
                    connect_timeout=min(remaining, HANDSHAKE_TIMEOUT_SECONDS),
                )
            except EndpointUnavailableError:
                last_spawn = self._maybe_spawn(last_spawn)
            except EndpointForeignError:
                _LOG.warning("relay_endpoint_foreign fallback=per-client")
                return None
            except DaemonRejectedError as exc:
                if exc.reason not in {REJECT_DRAINING, REJECT_TOKEN}:
                    _LOG.warning("relay_rejected reason=%s fallback=per-client", exc.reason)
                    return None
            except DaemonFrameError:
                _LOG.warning("relay_protocol_mismatch fallback=per-client")
                return None
            except (ConnectionError, OSError):
                pass
            else:
                if reply.get("environment") != self._environment:
                    _LOG.warning("relay_environment_mismatch fallback=per-client")
                    await connection.close()
                    return None
                theirs = parse_product_version(str(reply.get("product_version")))
                if theirs == mine:
                    return connection
                await connection.close()
                if mine is None or (theirs is not None and theirs > mine):
                    _LOG.warning(
                        "relay_daemon_newer daemon=%s relay=%s fallback=per-client",
                        reply.get("product_version"),
                        __version__,
                    )
                    return None
                _LOG.info(
                    "relay_daemon_outdated daemon=%s relay=%s action=drain",
                    reply.get("product_version"),
                    __version__,
                )
                await self._ask_drain()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RELAY_RETRY_MAX_DELAY_SECONDS)
        _LOG.warning("relay_daemon_unreachable budget_s=%s", RELAY_START_BUDGET_SECONDS)
        return None

    # -- Session -----------------------------------------------------------------

    def _start_stdin_reader(self) -> None:
        loop = asyncio.get_running_loop()
        stream = sys.stdin.buffer

        def read() -> None:
            while True:
                line = stream.readline(MESSAGE_MAX_BYTES + 1)
                if not line:
                    break
                if len(line) > MESSAGE_MAX_BYTES:
                    _LOG.warning("relay_client_message_too_large limit=%s", MESSAGE_MAX_BYTES)
                    break
                if not line.endswith(b"\n"):
                    line += b"\n"
                loop.call_soon_threadsafe(self._lines.put_nowait, line)
            loop.call_soon_threadsafe(self._lines.put_nowait, None)

        threading.Thread(target=read, name="cortex-relay-stdin", daemon=True).start()

    async def _write_client(self, line: bytes) -> None:
        def write() -> None:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

        await asyncio.to_thread(write)

    def _track_client(self, line: bytes) -> None:
        message = _parse(line)
        if message is None:
            return
        method = message.get("method")
        key = _request_key(message)
        if method == _INITIALIZE_METHOD:
            self._initialize, self._initialize_key = line, key
        elif method == _INITIALIZED_NOTIFICATION:
            self._initialized = line
        if method is not None and key is not None:
            self._in_flight[key] = line

    def _track_backend(self, line: bytes) -> None:
        message = _parse(line)
        if message is None or "method" in message:
            return
        key = _request_key(message)
        if key is not None:
            self._in_flight.pop(key, None)

    async def _pump(self, backend: Backend) -> bool:
        """Carry lines until one side ends; True when the client closed its stdin."""

        async def client_to_backend() -> bool:
            while True:
                line = await self._lines.get()
                if line is None:
                    return True
                self._track_client(line)
                if not await backend.send(line):
                    return False

        async def backend_to_client() -> bool:
            while True:
                line = await backend.receive()
                if line is None:
                    return False
                self._track_backend(line)
                await self._write_client(line)

        tasks = [
            asyncio.create_task(client_to_backend()),
            asyncio.create_task(backend_to_client()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return any(task.result() for task in done)

    async def _fail_in_flight(self) -> None:
        for key in list(self._in_flight):
            error = {
                "jsonrpc": JSONRPC_VERSION,
                "id": json.loads(key),
                "error": {
                    "code": RELAY_INTERRUPTED_ERROR_CODE,
                    "message": RELAY_INTERRUPTED_MESSAGE,
                },
            }
            await self._write_client(json.dumps(error).encode("utf-8") + b"\n")
            _LOG.warning("relay_request_interrupted")
        self._in_flight.clear()

    async def _replay(self, backend: Backend) -> bool:
        """Replay the remembered initialization on a new backend; drop its answer."""
        if self._initialize is None:
            return True
        if not await backend.send(self._initialize):
            return False
        while True:
            line = await asyncio.wait_for(backend.receive(), RELAY_START_BUDGET_SECONDS)
            if line is None:
                return False
            message = _parse(line)
            if message is not None and "method" not in message and (
                _request_key(message) == self._initialize_key
            ):
                break
        if self._initialized is not None:
            return await backend.send(self._initialized)
        return True

    def _record_failure(self) -> bool:
        """Record a lost connection; True when the in-process fallback is due."""
        now = time.monotonic()
        self._failures.append(now)
        while self._failures and now - self._failures[0] > RELAY_FAILURE_WINDOW_SECONDS:
            self._failures.popleft()
        return len(self._failures) >= RELAY_FAILURE_LIMIT

    async def _next_backend(self) -> Backend:
        if not self.in_process and not self._record_failure():
            connection = await self.connect()
            if connection is not None:
                backend = PipeBackend(connection)
                with contextlib.suppress(TimeoutError):
                    if await self._replay(backend):
                        _LOG.info("relay_reconnected")
                        return backend
                await backend.close()
        if not self.in_process:
            _LOG.warning("relay_fallback_in_process failures=%s", len(self._failures))
        self.in_process = True
        local = InProcessBackend()
        await local.start()
        await self._replay(local)
        return local

    async def serve(self, connection: Connection) -> None:
        """Relay the whole stdio session, starting on an established daemon connection."""
        self._start_stdin_reader()
        backend: Backend = PipeBackend(connection)
        while True:
            client_closed = await self._pump(backend)
            await backend.close()
            if client_closed:
                return
            await self._fail_in_flight()
            backend = await self._next_backend()


async def _run(environ: Mapping[str, str]) -> bool:
    relay = Relay(environ)
    connection = await relay.connect()
    if connection is None:
        return False
    _LOG.info("relay_attached pid=%s", connection.peer_pid)
    await relay.serve(connection)
    return True


def run_relay(environ: Mapping[str, str] | None = None) -> bool:
    """Serve this stdio session through the daemon.

    Returns False, having read nothing from stdin, when the caller must serve the
    session itself in per-client mode.
    """
    values = dict(os.environ if environ is None else environ)
    try:
        from cortex_logging import configure_logging

        configure_logging()
    except Exception:  # noqa: BLE001 -- per-client mode reports configuration errors.
        return False
    return asyncio.run(_run(values))


__all__ = ["InProcessBackend", "PipeBackend", "Relay", "run_relay"]
