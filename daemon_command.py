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
"""`cortex daemon run|status|stop`: run or control the shared per-user daemon."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from confluence_writer.constants import EXIT_ERROR, EXIT_OK
from daemon_client import (
    DaemonPaths,
    DaemonRejectedError,
    daemon_address,
    open_daemon,
    wait_for_daemon_exit,
)
from daemon_contract import (
    FRAME_KIND_STATUS,
    FRAME_KIND_STOP,
    PROTOCOL_VERSION,
    STOP_WAIT_TIMEOUT_SECONDS,
    DaemonFrameError,
    ServerMode,
)
from daemon_transport import EndpointForeignError, EndpointUnavailableError
from user_config import CortexConfigError, load_user_config

DaemonState = Literal["running", "stopped", "unavailable"]


class DaemonStatusReport(BaseModel):  # type: ignore[misc]
    """`cortex daemon status --json`, contract version 1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal[1] = 1
    operation: Literal["daemon_status"] = "daemon_status"
    state: DaemonState
    reason: str | None
    endpoint: str
    configured_mode: ServerMode | None
    protocol_version: int = PROTOCOL_VERSION
    pid: int | None
    product_version: str | None
    started_at: str | None
    uptime_seconds: float | None
    sessions: int | None
    in_flight: int | None
    sync_running: bool | None
    draining: bool | None
    idle_timeout_seconds: int | None


_EMPTY_STATUS: dict[str, Any] = {
    "pid": None,
    "product_version": None,
    "started_at": None,
    "uptime_seconds": None,
    "sessions": None,
    "in_flight": None,
    "sync_running": None,
    "draining": None,
    "idle_timeout_seconds": None,
}


def _configured_mode(environ: Mapping[str, str]) -> ServerMode | None:
    try:
        return load_user_config(environ=environ).server_mode
    except CortexConfigError:
        return None


async def _query_status(
    environ: Mapping[str, str],
) -> tuple[DaemonState, str | None, dict[str, Any]]:
    try:
        connection, reply = await open_daemon(FRAME_KIND_STATUS, environ)
    except EndpointUnavailableError:
        return "stopped", None, {}
    except EndpointForeignError:
        return "unavailable", "endpoint_foreign", {}
    except DaemonRejectedError as exc:
        return "unavailable", exc.reason, {}
    except DaemonFrameError:
        return "unavailable", "malformed_reply", {}
    await connection.close()
    daemon = reply.get("daemon")
    return "running", None, dict(daemon) if isinstance(daemon, dict) else {}


def status_report(environ: Mapping[str, str]) -> DaemonStatusReport:
    """Ask the daemon for its counters; a missing daemon is a valid `stopped` state."""
    state, reason, live = asyncio.run(_query_status(environ))
    fields = {**_EMPTY_STATUS, **{key: live.get(key) for key in _EMPTY_STATUS if key in live}}
    return DaemonStatusReport(
        state=state,
        reason=reason,
        endpoint=daemon_address(environ),
        configured_mode=_configured_mode(environ),
        **fields,
    )


def _status(namespace: argparse.Namespace, environ: Mapping[str, str]) -> int:
    report = status_report(environ)
    if namespace.json:
        sys.stdout.write(report.model_dump_json(indent=2) + "\n")
        return EXIT_OK
    if report.state == "running":
        sys.stdout.write(
            f"Cortex daemon: running (pid {report.pid}, version {report.product_version}, "
            f"{report.sessions} session(s), endpoint {report.endpoint})\n"
        )
    elif report.state == "stopped":
        sys.stdout.write(f"Cortex daemon: stopped (endpoint {report.endpoint})\n")
    else:
        sys.stdout.write(f"Cortex daemon: unavailable ({report.reason})\n")
    sys.stdout.write(f"Configured server mode: {report.configured_mode or 'unknown'}\n")
    return EXIT_OK


async def _request_stop(environ: Mapping[str, str]) -> str:
    try:
        connection, _reply = await open_daemon(FRAME_KIND_STOP, environ)
    except EndpointUnavailableError:
        return "not_running"
    except (EndpointForeignError, DaemonRejectedError, DaemonFrameError):
        return "unavailable"
    await connection.close()
    return "stopping"


def _stop(namespace: argparse.Namespace, environ: Mapping[str, str]) -> int:
    outcome = asyncio.run(_request_stop(environ))
    if outcome == "unavailable":
        sys.stderr.write("Cortex daemon: the endpoint did not accept the stop request.\n")
        return EXIT_ERROR
    if outcome == "not_running":
        sys.stdout.write("Cortex daemon: not running.\n")
        return EXIT_OK
    if namespace.wait and not wait_for_daemon_exit(
        DaemonPaths.from_environ(environ), STOP_WAIT_TIMEOUT_SECONDS
    ):
        sys.stderr.write("Cortex daemon: still draining after the wait timeout.\n")
        return EXIT_ERROR
    sys.stdout.write(
        "Cortex daemon: stopped.\n" if namespace.wait else "Cortex daemon: stop requested.\n"
    )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Build the daemon command line."""
    parser = argparse.ArgumentParser(
        prog="cortex daemon",
        description="Run or control the shared per-user server used when "
        "[server] mode = \"shared\".",
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("run", help="Run the daemon in the foreground (relays start it)")
    status_parser = subparsers.add_parser("status", help="Report whether the daemon runs")
    status_parser.add_argument(
        "--json", action="store_true", help="Emit the machine-readable JSON contract"
    )
    stop_parser = subparsers.add_parser("stop", help="Ask the daemon to drain and exit")
    stop_parser.add_argument(
        "--wait", action="store_true", help="Wait until the daemon has exited"
    )
    return parser


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    """Run one daemon operation."""
    namespace = build_parser().parse_args(argv)
    values = dict(os.environ if environ is None else environ)
    if namespace.operation == "run":
        from daemon_server import run_daemon

        return run_daemon(values)
    if namespace.operation == "status":
        return _status(namespace, values)
    return _stop(namespace, values)


__all__ = ["DaemonStatusReport", "build_parser", "main", "status_report"]
