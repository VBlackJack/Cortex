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
"""The relay's bookkeeping and its fallbacks, with fake daemons and fake backends."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import cli
import daemon_relay
from _version import __version__
from daemon_contract import (
    RELAY_FAILURE_LIMIT,
    RELAY_INTERRUPTED_ERROR_CODE,
    environment_fingerprint,
)
from daemon_relay import Relay

_INITIALIZE = b'{"jsonrpc":"2.0","id":0,"method":"initialize","params":{}}\n'
_INITIALIZED = b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'


def _relay(tmp_path: Path) -> Relay:
    return Relay({"APPDATA": str(tmp_path / "a"), "LOCALAPPDATA": str(tmp_path / "l")})


class _Backend:
    def __init__(self, answers: list[bytes]) -> None:
        self.sent: list[bytes] = []
        self._answers = list(answers)

    async def send(self, line: bytes) -> bool:
        self.sent.append(line)
        return True

    async def receive(self) -> bytes | None:
        return self._answers.pop(0) if self._answers else None

    async def close(self) -> None:
        return None


def test_requests_are_tracked_until_answered(tmp_path: Path) -> None:
    relay = _relay(tmp_path)
    relay._track_client(_INITIALIZE)
    relay._track_client(_INITIALIZED)
    relay._track_client(b'{"jsonrpc":"2.0","id":"a","method":"tools/list"}\n')
    assert set(relay._in_flight) == {"0", '"a"'}
    relay._track_backend(b'{"jsonrpc":"2.0","id":0,"result":{}}\n')
    relay._track_backend(b'{"jsonrpc":"2.0","method":"notifications/message","params":{}}\n')
    assert set(relay._in_flight) == {'"a"'}
    assert relay._initialize == _INITIALIZE and relay._initialized == _INITIALIZED


async def test_in_flight_requests_get_an_error_not_a_replay(tmp_path: Path) -> None:
    relay = _relay(tmp_path)
    written: list[bytes] = []

    async def collect(line: bytes) -> None:
        written.append(line)

    relay._write_client = collect  # type: ignore[method-assign]
    relay._track_client(b'{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{}}\n')
    await relay._fail_in_flight()
    error = json.loads(written[0])
    assert error["id"] == 5
    assert error["error"]["code"] == RELAY_INTERRUPTED_ERROR_CODE
    assert relay._in_flight == {}


async def test_replay_drops_the_repeated_initialize_answer(tmp_path: Path) -> None:
    relay = _relay(tmp_path)
    relay._track_client(_INITIALIZE)
    relay._track_client(_INITIALIZED)
    backend = _Backend(
        [
            b'{"jsonrpc":"2.0","method":"notifications/message","params":{}}\n',
            b'{"jsonrpc":"2.0","id":0,"result":{"capabilities":{}}}\n',
        ]
    )
    assert await relay._replay(backend) is True
    assert backend.sent == [_INITIALIZE, _INITIALIZED]


def test_third_loss_in_the_window_selects_the_in_process_fallback(tmp_path: Path) -> None:
    relay = _relay(tmp_path)
    outcomes = [relay._record_failure() for _ in range(RELAY_FAILURE_LIMIT)]
    assert outcomes == [False] * (RELAY_FAILURE_LIMIT - 1) + [True]


async def test_session_moves_in_process_after_the_daemon_is_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = _relay(tmp_path)
    relay._track_client(_INITIALIZE)
    local = _Backend([b'{"jsonrpc":"2.0","id":0,"result":{}}\n'])

    class FakeInProcess:
        def __init__(self) -> None:
            self.started = False

        async def start(self) -> None:
            self.started = True

        def __getattr__(self, name: str) -> Any:
            return getattr(local, name)

    async def unreachable() -> None:
        return None

    monkeypatch.setattr(daemon_relay, "InProcessBackend", FakeInProcess)
    monkeypatch.setattr(relay, "connect", unreachable)
    backend = await relay._next_backend()
    assert relay.in_process is True
    assert local.sent == [_INITIALIZE]
    assert backend is not None


def _reply(**overrides: Any) -> dict[str, Any]:
    reply = {
        "status": "accepted",
        "product_version": __version__,
        "environment": None,
        "pid": 1,
    }
    reply.update(overrides)
    return reply


class _Connection:
    def __init__(self) -> None:
        self.closed = False
        self.peer_pid = 1

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("overrides", "expect_connection"),
    [
        ({}, True),
        ({"environment": "another"}, False),
        ({"product_version": "9999.1231.99"}, False),
    ],
)
async def test_connect_accepts_only_the_same_version_and_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, Any],
    expect_connection: bool,
) -> None:
    relay = _relay(tmp_path)
    connection = _Connection()
    reply = _reply(environment=environment_fingerprint(relay._environ))
    reply.update(overrides)

    async def fake_open(*_args: Any, **_kwargs: Any) -> tuple[_Connection, dict[str, Any]]:
        return connection, reply

    monkeypatch.setattr(daemon_relay, "open_daemon", fake_open)
    result = await relay.connect()
    assert (result is connection) is expect_connection
    assert connection.closed is not expect_connection


async def test_outdated_daemon_is_asked_to_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = _relay(tmp_path)
    kinds: list[str] = []
    replies = [
        _reply(environment=environment_fingerprint(relay._environ), product_version="1.0.0"),
        _reply(environment=environment_fingerprint(relay._environ)),
    ]

    async def fake_open(kind: str, *_args: Any, **_kwargs: Any) -> tuple[_Connection, Any]:
        kinds.append(kind)
        if kind == "drain":
            return _Connection(), _reply()
        return _Connection(), replies.pop(0)

    monkeypatch.setattr(daemon_relay, "open_daemon", fake_open)
    assert await relay.connect() is not None
    assert kinds == ["session", "drain", "session"]


def _fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> None:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


def test_shared_serve_falls_back_to_per_client_when_the_relay_declines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "_serve_mode", lambda: "shared")
    _fake_module(monkeypatch, "daemon_relay", run_relay=lambda: calls.append("relay") or False)
    _fake_module(monkeypatch, "server", run_stdio=lambda: calls.append("stdio"))
    assert cli.main(["serve"]) == 0
    assert calls == ["relay", "stdio"]


def test_per_client_serve_never_reaches_the_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "_serve_mode", lambda: "per-client")
    _fake_module(monkeypatch, "daemon_relay", run_relay=lambda: calls.append("relay") or True)
    _fake_module(monkeypatch, "server", run_stdio=lambda: calls.append("stdio"))
    assert cli.main(["serve"]) == 0
    assert calls == ["stdio"]


def test_unreadable_configuration_serves_per_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "Cortex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("schema_version = 1\n[server]\nmode = 3\n", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert cli._serve_mode() == "per-client"
