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
"""Cross-process proofs of the shared daemon on a real endpoint.

Every test drives real `cortex serve` relays through the MCP client library, against a
daemon the first relay starts detached, in a throwaway data home whose endpoint name
carries a unique suffix. The model cache is the developer's own, reached through a
directory junction, so nothing is downloaded. Each fixture stops its daemon, and kills
it when it does not stop, so no process outlives the test.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the cross-process proofs run on the Windows named pipe",
)

_REPOSITORY = Path(__file__).resolve().parents[1]
_CLI = _REPOSITORY / "cli.py"
_MODELS = Path(os.environ.get("LOCALAPPDATA", "")) / "Cortex" / "models"
_WAIT_SECONDS = 30.0
_POLL_SECONDS = 0.2


@dataclass
class SharedHome:
    """A throwaway data home with a shared-mode configuration."""

    root: Path
    environ: dict[str, str]
    kb: Path
    daemons: list[subprocess.Popen[bytes]] = field(default_factory=list)

    def start_daemon(self) -> subprocess.Popen[bytes]:
        """Start the daemon from the test process, outside any MCP client's job.

        The MCP Python client puts each server it starts in a kill-on-close job that
        forbids breakaway, so a daemon a relay starts there dies with that client.
        """
        daemon = subprocess.Popen(
            [sys.executable, str(_CLI), "daemon", "run"],
            cwd=_REPOSITORY,
            env=self.environ,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        self.daemons.append(daemon)
        self.wait_state("running")
        return daemon

    @property
    def config(self) -> Path:
        return Path(self.environ["APPDATA"]) / "Cortex" / "config.toml"

    def cli(self, *arguments: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_CLI), *arguments],
            cwd=_REPOSITORY,
            env=self.environ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )

    def status(self) -> dict[str, Any]:
        completed = self.cli("daemon", "status", "--json", timeout=30)
        assert completed.returncode == 0, completed.stderr
        report: dict[str, Any] = json.loads(completed.stdout)
        return report

    def wait_state(self, state: str) -> dict[str, Any]:
        deadline = time.monotonic() + _WAIT_SECONDS
        while True:
            report = self.status()
            if report["state"] == state or time.monotonic() > deadline:
                assert report["state"] == state, report
                return report
            time.sleep(_POLL_SECONDS)

    def stop(self) -> None:
        report = self.status()
        self.cli("daemon", "stop", "--wait", timeout=90)
        pid = report.get("pid")
        if pid:
            with suppress(OSError):
                os.kill(int(pid), signal.SIGTERM)
        for daemon in self.daemons:
            if daemon.poll() is None:
                daemon.kill()
            daemon.wait(_WAIT_SECONDS)


def _make_home(idle_timeout_seconds: int) -> SharedHome:
    import _winapi

    # Every test here starts the real server, which needs the embedding model; a
    # fresh runner has no cache to link, and these tests must not download one.
    if not _MODELS.is_dir():
        pytest.skip("no local model cache to share with the throwaway data home")
    root = Path(tempfile.mkdtemp(prefix="cortex-daemon-"))
    appdata = root / "appdata"
    local = root / "local"
    kb = root / "kb"
    (kb / "knowledge").mkdir(parents=True)
    (kb / "knowledge" / "alpha.md").write_text(
        "# Alpha\n\n" + "The alpha pipeline routes telemetry through relays. " * 20,
        encoding="utf-8",
    )
    (appdata / "Cortex").mkdir(parents=True)
    (local / "Cortex").mkdir(parents=True)
    _winapi.CreateJunction(str(_MODELS), str(local / "Cortex" / "models"))
    (appdata / "Cortex" / "config.toml").write_text(
        "schema_version = 1\n"
        f"kb_path = {json.dumps(str(kb))}\n"
        'included_sections = ["knowledge"]\n'
        "\n[server]\n"
        'mode = "shared"\n'
        f"idle_timeout_seconds = {idle_timeout_seconds}\n",
        encoding="utf-8",
    )
    environ = {key: value for key, value in os.environ.items() if not key.startswith("CORTEX_")}
    environ.update(
        APPDATA=str(appdata),
        LOCALAPPDATA=str(local),
        CORTEX_DAEMON_ENDPOINT_SUFFIX=uuid.uuid4().hex[:16],
    )
    return SharedHome(root=root, environ=environ, kb=kb)


def _remove_home(home: SharedHome) -> None:
    junction = Path(home.environ["LOCALAPPDATA"]) / "Cortex" / "models"
    with suppress(OSError):
        os.rmdir(junction)  # Removes the junction itself, never the model cache.
    shutil.rmtree(home.root, ignore_errors=True)


@pytest.fixture(scope="module")
def shared_home() -> Iterator[SharedHome]:
    home = _make_home(idle_timeout_seconds=0)
    synced = home.cli("sync")
    assert synced.returncode == 0, synced.stderr[-2000:]
    try:
        home.start_daemon()
        yield home
    finally:
        home.stop()
        _remove_home(home)


@asynccontextmanager
async def _session(home: SharedHome) -> AsyncIterator[Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(_CLI), "serve"],
        env=home.environ,
        cwd=str(_REPOSITORY),
    )
    async with AsyncExitStack() as stack:
        errors = stack.enter_context(open(home.root / "relay.err", "a", encoding="utf-8"))
        read, write = await stack.enter_async_context(stdio_client(parameters, errlog=errors))
        session = await stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), _WAIT_SECONDS)
        yield session


def _text(result: Any) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content)


async def test_two_relays_share_one_daemon(shared_home: SharedHome) -> None:
    async with _session(shared_home) as first, _session(shared_home) as second:
        first_tools = await first.list_tools()
        second_tools = await second.list_tools()
        names = {tool.name for tool in first_tools.tools}
        assert names == {tool.name for tool in second_tools.tools}
        assert {"cortex_search", "cortex_sync"} <= names
        report = shared_home.status()
        assert report["state"] == "running"
        assert report["sessions"] == 2
        result = await first.call_tool("cortex_search", {"query": "alpha telemetry relays"})
        assert "alpha.md" in _text(result)


async def test_wrong_token_is_rejected_before_any_mcp_byte(shared_home: SharedHome) -> None:
    from daemon_client import DaemonRejectedError, daemon_address, exchange_opening, opening_frame
    from daemon_transport import connect

    async with _session(shared_home):
        connection = await connect(daemon_address(shared_home.environ))
        try:
            frame = opening_frame("session", "00" * 32, shared_home.environ)
            with pytest.raises(DaemonRejectedError) as rejected:
                await exchange_opening(connection, frame)
            assert rejected.value.reason == "bad_token"
            assert await connection.reader.read() == b""
        finally:
            await connection.close()


async def test_daemon_search_sees_an_external_sync(shared_home: SharedHome) -> None:
    """Question 8: a long-lived daemon and a sync run by another process."""
    async with _session(shared_home) as session:
        before = _text(await session.call_tool("cortex_search", {"query": "zebra migration"}))
        assert "beta.md" not in before
        (shared_home.kb / "knowledge" / "beta.md").write_text(
            "# Beta\n\n" + "Zebra migration across the savannah follows the rains. " * 20,
            encoding="utf-8",
        )
        synced = shared_home.cli("sync")
        assert synced.returncode == 0, synced.stderr[-2000:]
        after = _text(await session.call_tool("cortex_search", {"query": "zebra migration"}))
        assert "beta.md" in after


async def test_config_change_drains_and_the_open_session_continues(
    shared_home: SharedHome,
) -> None:
    async with _session(shared_home) as session:
        first_pid = shared_home.status()["pid"]
        with shared_home.config.open("a", encoding="utf-8") as handle:
            handle.write("# touched by the drain test\n")
        deadline = time.monotonic() + _WAIT_SECONDS
        while shared_home.status().get("pid") == first_pid:
            assert time.monotonic() < deadline, "the daemon never drained"
            await asyncio.sleep(_POLL_SECONDS)
        tools = await asyncio.wait_for(session.list_tools(), _WAIT_SECONDS)
        assert tools.tools
        report = shared_home.wait_state("running")
        assert report["pid"] != first_pid
        assert report["sessions"] == 1


async def test_idle_daemon_stops_after_its_delay() -> None:
    home = _make_home(idle_timeout_seconds=2)
    try:
        daemon = home.start_daemon()
        async with _session(home) as session:
            await session.list_tools()
            assert home.status()["sessions"] == 1
        home.wait_state("stopped")
        # A clean exit: the daemon drained on its idle delay, it was not killed.
        assert daemon.wait(_WAIT_SECONDS) == 0
    finally:
        home.stop()
        _remove_home(home)


async def test_relay_with_another_environment_serves_per_client(
    shared_home: SharedHome,
) -> None:
    async with _session(shared_home) as attached:
        await attached.list_tools()
        other = SharedHome(
            root=shared_home.root,
            environ={**shared_home.environ, "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "31"},
            kb=shared_home.kb,
        )
        async with _session(other) as separate:
            assert (await separate.list_tools()).tools
            assert shared_home.status()["sessions"] == 1
