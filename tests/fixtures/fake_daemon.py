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
"""Run the real daemon with a fake MCP server, so endpoint proofs need no model.

Everything but the server preparation is the product: the single-instance lock,
the token, the endpoint (named pipe or Unix socket), the peer checks, the opening
exchange, the idle stop and the drain. The fake session answers every request
with `{"method": <name>}`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import daemon_server  # noqa: E402


class _EchoServer:
    SYNC_LOCKED_MESSAGE = "locked"

    @staticmethod
    async def run_session(read_stream: Any, write_stream: Any) -> None:
        from mcp.shared.message import SessionMessage
        from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

        async with read_stream, write_stream:
            async for item in read_stream:
                if isinstance(item, Exception):
                    continue
                request = item.message.root
                if not isinstance(request, JSONRPCRequest):
                    continue
                response = JSONRPCResponse(
                    jsonrpc="2.0", id=request.id, result={"method": request.method}
                )
                await write_stream.send(SessionMessage(JSONRPCMessage(response)))


def _prepare(_runtime: daemon_server.DaemonRuntime) -> Any:
    return _EchoServer


if __name__ == "__main__":
    daemon_server.DaemonRuntime._prepare = _prepare  # type: ignore[method-assign]
    raise SystemExit(daemon_server.run_daemon())
