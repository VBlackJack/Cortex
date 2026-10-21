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
"""Constants of the shared per-user server, importable without any Cortex configuration.

The user configuration validates the `[server]` table against these values, so this
module must never import `config` or anything that resolves the configuration.
"""

from __future__ import annotations

from typing import Final, Literal

ServerMode = Literal["per-client", "shared"]

SERVER_MODE_PER_CLIENT: Final[ServerMode] = "per-client"
"""Every MCP client starts its own complete server process (the historical behaviour)."""

SERVER_MODE_SHARED: Final[ServerMode] = "shared"
"""`cortex serve` relays to one per-user daemon that hosts every session."""

SERVER_MODES: Final[tuple[ServerMode, ...]] = (SERVER_MODE_PER_CLIENT, SERVER_MODE_SHARED)
DEFAULT_SERVER_MODE: Final[ServerMode] = SERVER_MODE_PER_CLIENT

DEFAULT_IDLE_TIMEOUT_SECONDS: Final = 900
"""The daemon stops after this long without an open connection; zero disables it."""

__all__ = [
    "DEFAULT_IDLE_TIMEOUT_SECONDS",
    "DEFAULT_SERVER_MODE",
    "SERVER_MODES",
    "SERVER_MODE_PER_CLIENT",
    "SERVER_MODE_SHARED",
    "ServerMode",
]
