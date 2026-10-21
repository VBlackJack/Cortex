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
"""Measure N concurrent MCP sessions in per-client or shared mode.

For each requested N, the script starts N `cortex serve` processes at once against a
throwaway data home holding a small fixture corpus, drives `initialize` and one
`cortex_search` through each with the MCP client library, and records the time from
process launch to the first search result. While every session is still open, it adds
up the private memory and working set of every Cortex process it started, directly or
through a relay (the shared daemon included). The report goes to `--output` as JSON.

In shared mode the script starts the daemon itself, then warms it with one extra
session whose timing, from the daemon launch, is reported apart as the cold start; the
per-session figures are those of a warm daemon. The daemon is started here rather than
by a relay because the MCP Python client puts every server it starts in a kill-on-close
job that forbids breakaway: a daemon started by a relay there would die with the first
session that closes.

The throwaway data home reaches the developer's model cache through a directory link,
so nothing is downloaded. Windows only for the memory figures, which come from
GetProcessMemoryInfo through ctypes.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from contextlib import AsyncExitStack, suppress
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPOSITORY))

from _version import __version__  # noqa: E402
from daemon_contract import SERVER_MODES  # noqa: E402

DEFAULT_SESSION_COUNTS = (1, 10, 30)
SESSION_TIMEOUT_SECONDS = 300.0
DAEMON_STOP_TIMEOUT_SECONDS = 120.0
SEARCH_QUERY = "telemetry relay pipeline"
FIXTURE_DOCUMENTS = 12
FIXTURE_PARAGRAPH_REPEAT = 25
FIXTURE_TOPICS = (
    "telemetry relay pipeline",
    "certificate rotation runbook",
    "backup retention policy",
    "network segmentation review",
)
REPORT_SCHEMA_VERSION = 1
P95_QUANTILE_INDEX = 18  # statistics.quantiles(n=20) index of the 95th percentile.

# Win32 process inspection.
_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_VM_READ = 0x0010
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MAX_PATH = 260


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * _MAX_PATH),
    ]


class _MemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def _process_parents() -> dict[int, int]:
    """Return pid -> parent pid for every process, from a Toolhelp snapshot."""
    if sys.platform != "win32":
        raise OSError("process snapshots need Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    parents: dict[int, int] = {}
    entry = _ProcessEntry()
    entry.dwSize = ctypes.sizeof(_ProcessEntry)
    try:
        found = kernel32.Process32First(ctypes.c_void_p(snapshot), ctypes.byref(entry))
        while found:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            found = kernel32.Process32Next(ctypes.c_void_p(snapshot), ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(snapshot))
    return parents


def descendants(root: int) -> list[int]:
    """Return every live descendant of `root`, detached children included."""
    parents = _process_parents()
    children: dict[int, list[int]] = {}
    for pid, parent in parents.items():
        if pid != parent:
            children.setdefault(parent, []).append(pid)
    found: list[int] = []
    pending = list(children.get(root, []))
    while pending:
        pid = pending.pop()
        found.append(pid)
        pending.extend(children.get(pid, []))
    return found


def process_memory(pid: int) -> tuple[int, int] | None:
    """Return (private bytes, working set bytes) of one process, or None if gone."""
    if sys.platform != "win32":
        raise OSError("process memory counters need Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_VM_READ, False, pid
    )
    if not handle:
        return None
    counters = _MemoryCounters()
    counters.cb = ctypes.sizeof(_MemoryCounters)
    try:
        if not psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(handle), ctypes.byref(counters), counters.cb
        ):
            return None
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
    return int(counters.PrivateUsage), int(counters.WorkingSetSize)


# -- Throwaway data home ---------------------------------------------------------


def _link_directory(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def prepare_home(mode: str, models: Path) -> tuple[Path, dict[str, str]]:
    """Create the data home, the configuration and the fixture corpus; index it."""
    root = Path(tempfile.mkdtemp(prefix="cortex-measure-"))
    appdata, local, kb = root / "appdata", root / "local", root / "kb"
    section = kb / "knowledge"
    section.mkdir(parents=True)
    for index in range(FIXTURE_DOCUMENTS):
        topic = FIXTURE_TOPICS[index % len(FIXTURE_TOPICS)]
        body = f"Notes {index} about the {topic}. " * FIXTURE_PARAGRAPH_REPEAT
        (section / f"note-{index:02d}.md").write_text(f"# Note {index}\n\n{body}\n", "utf-8")
    (appdata / "Cortex").mkdir(parents=True)
    (local / "Cortex").mkdir(parents=True)
    _link_directory(models, local / "Cortex" / "models")
    (appdata / "Cortex" / "config.toml").write_text(
        "schema_version = 1\n"
        f"kb_path = {json.dumps(str(kb))}\n"
        'included_sections = ["knowledge"]\n'
        f'\n[server]\nmode = "{mode}"\nidle_timeout_seconds = 0\n',
        encoding="utf-8",
    )
    environ = {key: value for key, value in os.environ.items() if not key.startswith("CORTEX_")}
    environ.update(
        APPDATA=str(appdata),
        LOCALAPPDATA=str(local),
        CORTEX_DAEMON_ENDPOINT_SUFFIX=f"measure{uuid.uuid4().hex[:12]}",
    )
    completed = _cli(environ, "sync")
    if completed.returncode != 0:
        raise RuntimeError(f"fixture sync failed: {completed.stderr[-2000:]}")
    return root, environ


def remove_home(root: Path, environ: dict[str, str]) -> None:
    """Remove the data home; the model link goes first so the cache is never touched."""
    link = Path(environ["LOCALAPPDATA"]) / "Cortex" / "models"
    with suppress(OSError):
        if link.is_symlink():
            link.unlink()
        else:
            os.rmdir(link)
    shutil.rmtree(root, ignore_errors=True)


def _cli(environ: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_REPOSITORY / "cli.py"), *arguments],
        cwd=_REPOSITORY,
        env=environ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=DAEMON_STOP_TIMEOUT_SECONDS,
        check=False,
    )


# -- Sessions ------------------------------------------------------------------------


async def _open_session(
    stack: AsyncExitStack, environ: dict[str, str], errors: Any
) -> float:
    """Start one `cortex serve`, initialize and search; return seconds to the result."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(_REPOSITORY / "cli.py"), "serve"],
        env=environ,
        cwd=str(_REPOSITORY),
    )
    started = time.perf_counter()
    read, write = await stack.enter_async_context(stdio_client(parameters, errlog=errors))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    result = await session.call_tool("cortex_search", {"query": SEARCH_QUERY})
    if result.isError:
        raise RuntimeError("cortex_search returned an error")
    return time.perf_counter() - started


def _summary(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95 = (
        statistics.quantiles(ordered, n=20)[P95_QUANTILE_INDEX]
        if len(ordered) > 1
        else ordered[0]
    )
    return {
        "median": round(statistics.median(ordered), 3),
        "p95": round(p95, 3),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


def _memory_snapshot() -> dict[str, int]:
    private_total = working_total = count = 0
    for pid in descendants(os.getpid()):
        memory = process_memory(pid)
        if memory is None:
            continue
        count += 1
        private_total += memory[0]
        working_total += memory[1]
    return {
        "processes": count,
        "private_bytes_total": private_total,
        "working_set_bytes_total": working_total,
    }


async def _hold_session(
    environ: dict[str, str],
    errors: Any,
    latencies: list[float],
    opened: asyncio.Event,
    release: asyncio.Event,
    expected: int,
) -> None:
    """Open one session, report its latency, and keep it open until released.

    The MCP client contexts must be left in the task that entered them, so each
    session lives in its own task for its whole life.
    """
    async with AsyncExitStack() as stack:
        latencies.append(await _open_session(stack, environ, errors))
        if len(latencies) == expected:
            opened.set()
        await release.wait()


async def measure(count: int, environ: dict[str, str], errors: Any) -> dict[str, Any]:
    """Open `count` sessions at once and measure them while they are all open."""
    latencies: list[float] = []
    opened, release = asyncio.Event(), asyncio.Event()
    tasks = [
        asyncio.create_task(_hold_session(environ, errors, latencies, opened, release, count))
        for _ in range(count)
    ]
    try:
        await asyncio.wait_for(opened.wait(), SESSION_TIMEOUT_SECONDS)
        memory = _memory_snapshot()
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {
        "sessions": count,
        **memory,
        "first_result_seconds": [round(value, 3) for value in latencies],
        "first_result_summary": _summary(latencies),
    }


async def run(mode: str, counts: Sequence[int], models: Path) -> dict[str, Any]:
    """Measure every count in one mode against one data home."""
    root, environ = prepare_home(mode, models)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "product_version": __version__,
        "mode": mode,
        "measured_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "logical_processors": os.cpu_count(),
        "daemon_cold_start_seconds": None,
        "runs": [],
    }
    daemon: subprocess.Popen[bytes] | None = None
    try:
        with open(root / "sessions.err", "a", encoding="utf-8") as errors:
            if mode == "shared":
                launched = time.perf_counter()
                daemon = subprocess.Popen(
                    [sys.executable, str(_REPOSITORY / "cli.py"), "daemon", "run"],
                    cwd=_REPOSITORY,
                    env=environ,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=errors,
                )
                async with AsyncExitStack() as warmup:
                    await _open_session(warmup, environ, errors)
                report["daemon_cold_start_seconds"] = round(time.perf_counter() - launched, 3)
            for count in counts:
                report["runs"].append(await measure(count, environ, errors))
    finally:
        if daemon is not None:
            _cli(environ, "daemon", "stop", "--wait")
            if daemon.poll() is None:
                daemon.kill()
            daemon.wait(DAEMON_STOP_TIMEOUT_SECONDS)
        remove_home(root, environ)
    return report


def build_parser() -> argparse.ArgumentParser:
    """Build the measurement command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--mode", choices=SERVER_MODES, required=True)
    parser.add_argument(
        "--sessions", type=int, nargs="+", default=list(DEFAULT_SESSION_COUNTS)
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--models",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", "")) / "Cortex" / "models",
        help="Model cache to reach from the throwaway data home",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the measurement and write the JSON report."""
    namespace = build_parser().parse_args(argv)
    if sys.platform != "win32":
        sys.stderr.write("measure_sessions: the memory figures need Windows.\n")
        return 1
    if not namespace.models.is_dir():
        sys.stderr.write(f"measure_sessions: no model cache at {namespace.models}\n")
        return 1
    report = asyncio.run(run(namespace.mode, namespace.sessions, namespace.models))
    namespace.output.parent.mkdir(parents=True, exist_ok=True)
    namespace.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
