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
"""Constants and frames of the shared per-user server, importable without configuration.

The user configuration validates the `[server]` table against these values, and the
relay runs before any heavy module is loaded, so this module must never import
`config` or anything that resolves the configuration.

Wire protocol, version 1, over a local endpoint only (a Windows named pipe restricted to
the current user, or a Unix domain socket in a private directory):

1. The client sends one opening frame: a JSON object on one line, at most
   OPENING_FRAME_MAX_BYTES bytes including the newline, carrying the protocol version,
   its product version, the session token read from the data home, the kind of
   connection and the fingerprint of its configuration environment.
2. The daemon answers with one frame of the same shape and size bound: accepted or
   rejected with a reason, its own product version, environment fingerprint and pid,
   and for a status request the status document.
3. For a session connection, both sides then exchange JSON-RPC messages, one per line,
   each at most MESSAGE_MAX_BYTES bytes. A longer line closes the connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal

ServerMode = Literal["per-client", "shared"]

SERVER_MODE_PER_CLIENT: Final[ServerMode] = "per-client"
"""Every MCP client starts its own complete server process (the historical behaviour)."""

SERVER_MODE_SHARED: Final[ServerMode] = "shared"
"""`cortex serve` relays to one per-user daemon that hosts every session."""

SERVER_MODES: Final[tuple[ServerMode, ...]] = (SERVER_MODE_PER_CLIENT, SERVER_MODE_SHARED)
DEFAULT_SERVER_MODE: Final[ServerMode] = SERVER_MODE_PER_CLIENT

DEFAULT_IDLE_TIMEOUT_SECONDS: Final = 900
"""The daemon stops after this long without an open connection; zero disables it."""

# -- Endpoint ------------------------------------------------------------------

PROTOCOL_VERSION: Final = 1
"""Part of the endpoint name: two protocol generations never share an endpoint."""

PIPE_NAME_TEMPLATE: Final = "\\\\.\\pipe\\cortex-{sid}-v{protocol}{suffix}"
"""Windows named pipe; the user SID avoids collisions, the DACL does the access control."""

SOCKET_FILE_TEMPLATE: Final = "cortex-v{protocol}{suffix}.sock"
SOCKET_RUNTIME_DIRECTORY_NAME: Final = "cortex"
"""Directory created under XDG_RUNTIME_DIR for the socket, when that variable is set."""

SOCKET_FALLBACK_DIRECTORY_NAME: Final = "run"
"""Directory created under the data home for the socket otherwise."""

SOCKET_DIRECTORY_MODE: Final = 0o700
SOCKET_FILE_MODE: Final = 0o600
SOCKET_UMASK: Final = 0o177
UNIX_SOCKET_PATH_MAX_BYTES: Final = 100
"""Below the smallest sun_path limit of the supported platforms (104 bytes on macOS)."""

PIPE_BUFFER_BYTES: Final = 65_536

ENDPOINT_SUFFIX_ENV: Final = "CORTEX_DAEMON_ENDPOINT_SUFFIX"
"""Test isolation only: appends `-<suffix>` to the endpoint name."""

ENDPOINT_SUFFIX_PATTERN: Final = re.compile(r"^[A-Za-z0-9_]{1,32}$")

# -- Data home layout ----------------------------------------------------------

DAEMON_DIRECTORY_NAME: Final = "daemon"
DAEMON_LOCK_FILE_NAME: Final = "daemon.lock"
"""Single-instance lock, distinct from the Chroma write lock; released by the OS on exit."""

TOKEN_FILE_NAME: Final = "token"
TOKEN_BYTES: Final = 32

# -- Frames --------------------------------------------------------------------

OPENING_FRAME_MAX_BYTES: Final = 4096
MESSAGE_MAX_BYTES: Final = 8 * 1024 * 1024
STREAM_READ_LIMIT_BYTES: Final = MESSAGE_MAX_BYTES + 1

FrameKind = Literal["session", "status", "stop", "drain"]
FRAME_KINDS: Final[tuple[FrameKind, ...]] = ("session", "status", "stop", "drain")
FRAME_KIND_SESSION: Final[FrameKind] = "session"
FRAME_KIND_STATUS: Final[FrameKind] = "status"
FRAME_KIND_STOP: Final[FrameKind] = "stop"
FRAME_KIND_DRAIN: Final[FrameKind] = "drain"

FRAME_ACCEPTED: Final = "accepted"
FRAME_REJECTED: Final = "rejected"

RejectReason = Literal["malformed_frame", "unsupported_protocol", "bad_token", "draining"]
REJECT_MALFORMED: Final[RejectReason] = "malformed_frame"
REJECT_PROTOCOL: Final[RejectReason] = "unsupported_protocol"
REJECT_TOKEN: Final[RejectReason] = "bad_token"
REJECT_DRAINING: Final[RejectReason] = "draining"

# -- Timings and limits --------------------------------------------------------

HANDSHAKE_TIMEOUT_SECONDS: Final = 5.0
RELAY_START_BUDGET_SECONDS: Final = 10.0
"""Total time a relay spends reaching or starting the daemon, under the client's 20 s."""

RELAY_RETRY_INITIAL_DELAY_SECONDS: Final = 0.05
RELAY_RETRY_MAX_DELAY_SECONDS: Final = 0.5
RELAY_SPAWN_INTERVAL_SECONDS: Final = 2.0
"""A relay starts at most one daemon per interval while it waits for the endpoint."""

RELAY_FAILURE_LIMIT: Final = 3
RELAY_FAILURE_WINDOW_SECONDS: Final = 300.0
"""After this many lost connections within the window, the relay serves in-process."""

DRAIN_TIMEOUT_SECONDS: Final = 30.0
"""How long a draining daemon waits for in-flight read requests before closing sessions.

A running sync is always waited for: a write is never cut off mid-flight.
"""

CONFIG_POLL_INTERVAL_SECONDS: Final = 2.0
MONITOR_INTERVAL_SECONDS: Final = 0.5
STOP_WAIT_TIMEOUT_SECONDS: Final = 60.0
DAEMON_EXIT_POLL_SECONDS: Final = 0.1

COMPUTE_CONCURRENCY: Final = 1
"""Read tools running at once in the daemon.

One keeps the embedding model and the shared Chroma client single-threaded for reads,
which is also what lets the daemon reopen the client between two reads. A sync runs
beside them under its own lock.
"""

# -- Fingerprints --------------------------------------------------------------

ENVIRONMENT_FINGERPRINT_PREFIX: Final = "CORTEX_"
ENVIRONMENT_FINGERPRINT_KEYS: Final = ("APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME")
"""Variables outside the CORTEX_ prefix that decide which configuration a process reads."""

POSIX_ENVIRONMENT_FINGERPRINT_KEYS: Final = ("HOME",)
"""Read as well outside Windows, where HOME decides the data home; on Windows a shell
that sets HOME would otherwise split one user into two environments."""

ABSENT_CONFIG_FINGERPRINT: Final = "absent"

# -- Relay error ---------------------------------------------------------------

JSONRPC_VERSION: Final = "2.0"
RELAY_INTERRUPTED_ERROR_CODE: Final = -32603
RELAY_INTERRUPTED_MESSAGE: Final = (
    "The Cortex shared server connection closed while this request was in flight. "
    "The request was not replayed; send it again."
)

# -- Exit codes of `cortex daemon run` -------------------------------------------

DAEMON_EXIT_ENDPOINT_FOREIGN: Final = 3
"""The endpoint name is held by a process that is not this user's Cortex daemon."""


class DaemonFrameError(ValueError):
    """Raised when an opening frame is malformed, too large or of another protocol."""


def environment_fingerprint(environ: Mapping[str, str]) -> str:
    """Hash every variable that changes which configuration a Cortex process resolves."""
    keys = set(ENVIRONMENT_FINGERPRINT_KEYS)
    if os.name != "nt":
        keys.update(POSIX_ENVIRONMENT_FINGERPRINT_KEYS)
    selected = sorted(
        (key, value)
        for key, value in environ.items()
        if key.upper().startswith(ENVIRONMENT_FINGERPRINT_PREFIX) or key.upper() in keys
    )
    return hashlib.sha256(json.dumps(selected).encode("utf-8")).hexdigest()


def config_fingerprint(path: Path) -> str:
    """Hash the exact bytes of the user configuration file, or mark it absent."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return ABSENT_CONFIG_FINGERPRINT


def endpoint_suffix(environ: Mapping[str, str]) -> str:
    """Return the test-only endpoint suffix, `-<value>`, or an empty string."""
    raw = environ.get(ENDPOINT_SUFFIX_ENV, "").strip()
    if not raw:
        return ""
    if not ENDPOINT_SUFFIX_PATTERN.fullmatch(raw):
        raise ValueError(f"{ENDPOINT_SUFFIX_ENV} must match {ENDPOINT_SUFFIX_PATTERN.pattern}")
    return f"-{raw}"


def encode_frame(frame: Mapping[str, Any]) -> bytes:
    """Serialize one opening frame and refuse one over the size bound."""
    data = json.dumps(frame, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
    if len(data) > OPENING_FRAME_MAX_BYTES:
        raise DaemonFrameError("opening frame exceeds the size bound")
    return data


def decode_frame(line: bytes) -> dict[str, Any]:
    """Parse one opening frame; the protocol version must match exactly."""
    if len(line) > OPENING_FRAME_MAX_BYTES or not line.endswith(b"\n"):
        raise DaemonFrameError("opening frame is truncated or exceeds the size bound")
    try:
        frame = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DaemonFrameError("opening frame is not JSON") from exc
    if not isinstance(frame, dict):
        raise DaemonFrameError("opening frame is not an object")
    if frame.get("protocol") != PROTOCOL_VERSION:
        raise DaemonFrameError("opening frame names another protocol version")
    return frame


def parse_product_version(value: str) -> tuple[int, ...] | None:
    """Return a comparable CalVer tuple, or None for a version that is not numeric."""
    parts = value.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


__all__ = [
    "DEFAULT_IDLE_TIMEOUT_SECONDS",
    "DEFAULT_SERVER_MODE",
    "SERVER_MODES",
    "SERVER_MODE_PER_CLIENT",
    "SERVER_MODE_SHARED",
    "DaemonFrameError",
    "ServerMode",
    "config_fingerprint",
    "decode_frame",
    "encode_frame",
    "endpoint_suffix",
    "environment_fingerprint",
    "parse_product_version",
]
