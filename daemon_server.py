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
"""The shared per-user daemon: one process hosting every MCP session of the user.

Lifecycle:
- one instance per user, through the dedicated `<data home>/daemon/daemon.lock`;
- a fresh random token in `<data home>/daemon/token` at each start;
- the endpoint is taken before the server modules load, so a relay connects within
  the interpreter start-up; sessions wait for the model warm-up, as a per-client
  server does in its lifespan;
- each accepted session runs on the single FastMCP instance, its synchronous tools
  executed in worker threads (read tools one at a time, a sync beside them under a
  process-level lock that fails immediately, like the cross-process write lock);
- it drains and exits after the idle delay without a session, when `config.toml`
  changes, on `cortex daemon stop`, or when a newer relay asks for it.

The token is never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hmac
import logging
import os
import sys
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import anyio
import filelock

from _version import __version__
from confluence_writer.constants import EXIT_INVALID_INPUT, EXIT_OK
from daemon_client import DaemonPaths, daemon_address, write_token
from daemon_contract import (
    COMPUTE_CONCURRENCY,
    CONFIG_POLL_INTERVAL_SECONDS,
    DAEMON_EXIT_ENDPOINT_FOREIGN,
    DRAIN_TIMEOUT_SECONDS,
    FRAME_ACCEPTED,
    FRAME_KIND_SESSION,
    FRAME_KIND_STATUS,
    FRAME_KINDS,
    FRAME_REJECTED,
    HANDSHAKE_TIMEOUT_SECONDS,
    MESSAGE_MAX_BYTES,
    MONITOR_INTERVAL_SECONDS,
    OPENING_FRAME_MAX_BYTES,
    PROTOCOL_VERSION,
    REJECT_DRAINING,
    REJECT_MALFORMED,
    REJECT_PROTOCOL,
    REJECT_TOKEN,
    DaemonFrameError,
    RejectReason,
    config_fingerprint,
    decode_frame,
    encode_frame,
    environment_fingerprint,
)
from daemon_transport import (
    Connection,
    EndpointForeignError,
    FrameTooLargeError,
    Listener,
    read_line,
)
from user_config import CortexConfigError, load_user_config, user_config_path

_LOG = logging.getLogger("cortex.daemon")

ToolFunction = Callable[..., Any]


class DaemonRuntime:
    """State and behaviour of one running daemon."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str],
        address: str,
        token: str,
        idle_timeout_seconds: int,
        config_path: Path,
    ) -> None:
        self._environ = dict(environ)
        self.address = address
        self._token = token
        self.idle_timeout_seconds = idle_timeout_seconds
        self._config_path = config_path
        self._config_fingerprint = config_fingerprint(config_path)
        self._config_checked = time.monotonic()
        self.environment = environment_fingerprint(environ)
        self.started_at = datetime.now(UTC)
        self._started = time.monotonic()
        self.last_activity = time.monotonic()
        self.sessions = 0
        self.in_flight = 0
        self.draining = False
        self.stop_reason: str | None = None
        self.sync_lock = threading.Lock()
        self._limiter = anyio.CapacityLimiter(COMPUTE_CONCURRENCY)
        self._session_scopes: set[anyio.CancelScope] = set()
        self._ready = asyncio.Event()
        self._server: ModuleType | None = None
        self._index: Any = None
        self._stop = asyncio.Event()

    # -- Status ----------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return the live counters reported by `cortex daemon status`."""
        return {
            "pid": os.getpid(),
            "product_version": __version__,
            "started_at": self.started_at.isoformat(),
            "uptime_seconds": round(time.monotonic() - self._started, 3),
            "sessions": self.sessions,
            "in_flight": self.in_flight,
            "sync_running": self.sync_lock.locked(),
            "draining": self.draining,
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }

    def request_drain(self, reason: str) -> None:
        """Stop taking sessions and exit once in-flight requests are done."""
        if not self.draining:
            _LOG.info("daemon_drain_requested reason=%s sessions=%s", reason, self.sessions)
        self.draining = True
        self.stop_reason = self.stop_reason or reason
        self._stop.set()

    def _check_config(self) -> None:
        fingerprint = config_fingerprint(self._config_path)
        self._config_checked = time.monotonic()
        if fingerprint != self._config_fingerprint:
            self.request_drain("config_changed")

    # -- Server preparation ----------------------------------------------------

    @asynccontextmanager
    async def _session_lifespan(self, _server: Any) -> AsyncIterator[dict[str, Any]]:
        # The index and the model are already open and warm for the whole process.
        yield {"shared_daemon": True}

    def _read_tool(self, original: ToolFunction) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(original)
        async def run(**arguments: Any) -> Any:
            self._check_config()
            self.in_flight += 1
            try:
                return await anyio.to_thread.run_sync(
                    functools.partial(original, **arguments), limiter=self._limiter
                )
            finally:
                self.in_flight -= 1
                self.last_activity = time.monotonic()

        return run

    def _sync_tool(self, original: ToolFunction) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(original)
        async def run(**arguments: Any) -> Any:
            self._check_config()
            server = self._server
            assert server is not None
            # The file lock is reentrant inside one process, so two sessions of the
            # daemon would not exclude each other through it: this lock does.
            if not self.sync_lock.acquire(blocking=False):
                _LOG.info("daemon_sync_refused reason=sync_running")
                return server.SYNC_LOCKED_MESSAGE
            self.in_flight += 1
            try:
                await anyio.to_thread.run_sync(self._index.begin_write)
                try:
                    return await anyio.to_thread.run_sync(
                        functools.partial(original, **arguments)
                    )
                finally:
                    self._index.end_write()
            finally:
                self.in_flight -= 1
                self.sync_lock.release()
                self.last_activity = time.monotonic()

        return run

    def _prepare(self) -> ModuleType:
        """Load the server, share the index readers, offload tools and warm the model."""
        from offline_models import activate_if_embedded

        activate_if_embedded()
        import indexer
        import server
        from chroma_client import create_persistent_client
        from config import CHROMA_PATH, CORTEX_WRITE_LOCK_PATH
        from daemon_resources import HeldLexicalIndex, SharedIndex

        index = SharedIndex(
            chroma_path=Path(CHROMA_PATH),
            write_lock_path=CORTEX_WRITE_LOCK_PATH,
            factory=lambda: create_persistent_client(CHROMA_PATH),
        )
        lexical = HeldLexicalIndex()
        indexer.install_shared_resources(index.client, lambda: lexical)
        self._index = index
        server.mcp._mcp_server.lifespan = self._session_lifespan
        for tool in server.mcp._tool_manager.list_tools():
            if tool.is_async:
                continue
            wrap = self._sync_tool if tool.name == "cortex_sync" else self._read_tool
            tool.fn = wrap(tool.fn)
            tool.is_async = True
        try:
            collection = indexer.get_collection()
            collection.query(query_texts=["warmup"], n_results=1)
        except Exception as exc:  # noqa: BLE001 -- tools report index errors per call.
            _LOG.warning("daemon_warmup_failed error=%s", type(exc).__name__)
        return server

    async def _prepare_in_background(self) -> None:
        try:
            self._server = await anyio.to_thread.run_sync(self._prepare)
        except CortexConfigError:
            _LOG.critical("daemon_start_refused reason=invalid_configuration")
            self.request_drain("startup_failed")
        except Exception:  # noqa: BLE001 -- logged, then the daemon exits cleanly.
            _LOG.critical("daemon_start_failed", exc_info=True)
            self.request_drain("startup_failed")
        else:
            _LOG.info("daemon_ready pid=%s", os.getpid())
        finally:
            self._ready.set()

    # -- Connections -----------------------------------------------------------

    def _reply(self, status: str, reason: RejectReason | None = None) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "product_version": __version__,
            "status": status,
            "reason": reason,
            "environment": self.environment,
            "pid": os.getpid(),
        }

    async def _send(self, connection: Connection, frame: Mapping[str, Any]) -> None:
        connection.writer.write(encode_frame(frame))
        await connection.writer.drain()

    async def handle(self, connection: Connection) -> None:
        """Run the opening exchange, then the requested kind of connection."""
        try:
            line = await asyncio.wait_for(
                read_line(connection.reader, OPENING_FRAME_MAX_BYTES),
                HANDSHAKE_TIMEOUT_SECONDS,
            )
        except (TimeoutError, FrameTooLargeError, ConnectionError, OSError):
            _LOG.warning("daemon_opening_frame_refused peer=%s", connection.peer_pid)
            return
        if line is None:
            return
        try:
            frame = decode_frame(line)
        except DaemonFrameError as exc:
            reason = REJECT_PROTOCOL if "protocol" in str(exc) else REJECT_MALFORMED
            _LOG.warning("daemon_connection_rejected reason=%s", reason)
            await self._send(connection, self._reply(FRAME_REJECTED, reason))
            return
        token = frame.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(
            token.encode("utf-8"), self._token.encode("utf-8")
        ):
            _LOG.warning("daemon_connection_rejected reason=%s", REJECT_TOKEN)
            await self._send(connection, self._reply(FRAME_REJECTED, REJECT_TOKEN))
            return
        kind = frame.get("kind")
        if kind not in FRAME_KINDS:
            await self._send(connection, self._reply(FRAME_REJECTED, REJECT_MALFORMED))
            return
        if kind == FRAME_KIND_STATUS:
            await self._send(connection, {**self._reply(FRAME_ACCEPTED), "daemon": self.status()})
            return
        if kind != FRAME_KIND_SESSION:
            await self._send(connection, self._reply(FRAME_ACCEPTED))
            self.request_drain(str(kind))
            return
        if self.draining:
            await self._send(connection, self._reply(FRAME_REJECTED, REJECT_DRAINING))
            return
        await self._send(connection, self._reply(FRAME_ACCEPTED))
        self.sessions += 1
        _LOG.info("daemon_session_opened sessions=%s peer=%s", self.sessions, connection.peer_pid)
        try:
            await self._serve_session(connection)
        finally:
            self.sessions -= 1
            self.last_activity = time.monotonic()
            _LOG.info("daemon_session_closed sessions=%s", self.sessions)

    async def _serve_session(self, connection: Connection) -> None:
        import mcp.types as types
        from mcp.shared.message import SessionMessage

        await self._ready.wait()
        server = self._server
        if server is None:
            return
        inbound_send, read_stream = anyio.create_memory_object_stream[
            SessionMessage | Exception
        ](0)
        write_stream, outbound_receive = anyio.create_memory_object_stream[SessionMessage](0)

        async def inbound() -> None:
            async with inbound_send:
                while True:
                    try:
                        line = await read_line(connection.reader, MESSAGE_MAX_BYTES)
                    except FrameTooLargeError:
                        _LOG.warning("daemon_message_too_large limit=%s", MESSAGE_MAX_BYTES)
                        return
                    except (ConnectionError, OSError):
                        return
                    if line is None:
                        return
                    try:
                        message = types.JSONRPCMessage.model_validate_json(line)
                    except Exception as exc:  # noqa: BLE001 -- the session answers it.
                        await inbound_send.send(exc)
                        continue
                    await inbound_send.send(SessionMessage(message))

        async def outbound() -> None:
            async with outbound_receive:
                async for item in outbound_receive:
                    payload = item.message.model_dump_json(by_alias=True, exclude_none=True)
                    connection.writer.write(payload.encode("utf-8") + b"\n")
                    await connection.writer.drain()

        with anyio.CancelScope() as scope:
            self._session_scopes.add(scope)
            try:
                async with anyio.create_task_group() as group:
                    group.start_soon(inbound)
                    group.start_soon(outbound)
                    await server.run_session(read_stream, write_stream)
                    group.cancel_scope.cancel()
            except* (ConnectionError, OSError, anyio.BrokenResourceError):
                _LOG.info("daemon_session_transport_closed")
            finally:
                self._session_scopes.discard(scope)

    # -- Main loop ---------------------------------------------------------------

    def _idle_expired(self) -> bool:
        return (
            self.idle_timeout_seconds > 0
            and self.sessions == 0
            and self.in_flight == 0
            and time.monotonic() - self.last_activity >= self.idle_timeout_seconds
        )

    async def _drain(self, listener: Listener) -> None:
        await listener.aclose()
        deadline = time.monotonic() + DRAIN_TIMEOUT_SECONDS
        while self.in_flight > 0 and (
            time.monotonic() < deadline or self.sync_lock.locked()
        ):
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
        for scope in list(self._session_scopes):
            scope.cancel()
        pending = list(listener.connections)
        if pending:
            await asyncio.wait(pending, timeout=HANDSHAKE_TIMEOUT_SECONDS)

    async def main(self) -> int:
        """Serve until a drain is requested; return the process exit code."""
        listener = Listener(self.address, self.handle)
        try:
            await listener.start()
        except EndpointForeignError:
            _LOG.error("daemon_endpoint_foreign endpoint=%s", self.address)
            return DAEMON_EXIT_ENDPOINT_FOREIGN
        _LOG.info(
            "daemon_started pid=%s version=%s endpoint=%s idle_timeout_s=%s",
            os.getpid(),
            __version__,
            self.address,
            self.idle_timeout_seconds,
        )
        preparation = asyncio.create_task(self._prepare_in_background())
        while not self._stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), MONITOR_INTERVAL_SECONDS)
            if self._idle_expired():
                self.request_drain("idle")
            elif time.monotonic() - self._config_checked >= CONFIG_POLL_INTERVAL_SECONDS:
                self._check_config()
        await self._drain(listener)
        if not preparation.done():
            # The interpreter cannot interrupt an import in a thread; let it end.
            with contextlib.suppress(Exception):
                await preparation
        _LOG.info("daemon_stopped reason=%s", self.stop_reason)
        return EXIT_OK


def run_daemon(environ: Mapping[str, str] | None = None) -> int:
    """Run the daemon in the foreground until it drains; the relay starts it detached."""
    values = dict(os.environ if environ is None else environ)
    try:
        from cortex_logging import configure_logging

        configure_logging()
        user_config = load_user_config(environ=values)
    except CortexConfigError as exc:
        _LOG.error("daemon_start_refused reason=invalid_configuration")
        sys.stderr.write(f"Cortex daemon error: {exc}\n")
        return EXIT_INVALID_INPUT
    paths = DaemonPaths.from_environ(values)
    paths.directory.mkdir(parents=True, exist_ok=True)
    lock = filelock.FileLock(paths.lock, timeout=0)
    try:
        lock.acquire(timeout=0)
    except filelock.Timeout:
        _LOG.info("daemon_already_running lock=%s", paths.lock)
        return EXIT_OK
    try:
        token = write_token(paths)
        runtime = DaemonRuntime(
            environ=values,
            address=daemon_address(values),
            token=token,
            idle_timeout_seconds=user_config.server_idle_timeout_seconds,
            config_path=user_config_path(values),
        )
        code = asyncio.run(runtime.main())
        with contextlib.suppress(OSError):
            if paths.token.read_text(encoding="ascii").strip() == token:
                paths.token.unlink()
        return code
    finally:
        lock.release()


__all__ = ["DaemonRuntime", "run_daemon"]
