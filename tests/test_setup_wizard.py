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
"""Guided setup orchestration and CLI routing tests."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

import cli
import setup_config
from setup_wizard import SetupPlan, run_setup


def _ok(client: str = "claude-desktop") -> setup_config.ClientResult:
    return setup_config.ClientResult(client, "OK", "registered", True)


def _fail(client: str = "codex") -> setup_config.ClientResult:
    return setup_config.ClientResult(client, "FAIL", "boom")


def test_run_setup_runs_init_index_register_in_order() -> None:
    calls: list[str] = []

    def init_fn(*, assume_yes: bool) -> bool:
        calls.append("init")
        return True

    def index_fn() -> dict[str, int]:
        calls.append("index")
        return {"reindexed": 0}

    def register_fn(python_exe: str, *, clients: str | None) -> list[setup_config.ClientResult]:
        calls.append("register")
        return [_ok()]

    result = run_setup(
        SetupPlan(), init_fn=init_fn, index_fn=index_fn, register_fn=register_fn
    )

    assert calls == ["init", "index", "register"]
    assert result.config_created is True
    assert result.indexed is True
    assert result.client_results == [_ok()]
    assert result.successful is True
    assert result.warnings == []


def test_run_setup_skips_index_when_build_index_false() -> None:
    calls: list[str] = []

    def index_fn() -> dict[str, int]:
        calls.append("index")
        return {}

    result = run_setup(
        SetupPlan(build_index=False),
        init_fn=lambda *, assume_yes: False,
        index_fn=index_fn,
        register_fn=lambda python_exe, *, clients: [_ok()],
    )

    assert calls == []
    assert result.indexed is False
    assert result.config_created is False


def test_run_setup_threads_assume_yes_and_clients() -> None:
    seen: dict[str, object] = {}

    def init_fn(*, assume_yes: bool) -> bool:
        seen["assume_yes"] = assume_yes
        return True

    def register_fn(python_exe: str, *, clients: str | None) -> list[setup_config.ClientResult]:
        seen["clients"] = clients
        return [_ok()]

    run_setup(
        SetupPlan(clients="codex,gemini", assume_yes=True, build_index=False),
        init_fn=init_fn,
        index_fn=lambda: {},
        register_fn=register_fn,
    )

    assert seen == {"assume_yes": True, "clients": "codex,gemini"}


def test_run_setup_client_failure_becomes_warning_not_abort() -> None:
    result = run_setup(
        SetupPlan(build_index=False),
        init_fn=lambda *, assume_yes: True,
        index_fn=lambda: {},
        register_fn=lambda python_exe, *, clients: [_ok(), _fail()],
    )

    assert result.successful is False
    assert any("codex" in warning for warning in result.warnings)
    assert len(result.client_results) == 2


def test_cli_routes_setup_to_wizard(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[str] = []
    module = ModuleType("setup_wizard")

    def fake_main(argv: list[str]) -> int:
        received.extend(argv)
        return 0

    module.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "setup_wizard", module)

    assert cli.main(["setup", "--yes", "--no-index"]) == 0
    assert received == ["--yes", "--no-index"]
