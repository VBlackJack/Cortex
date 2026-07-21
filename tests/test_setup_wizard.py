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
import setup_wizard
from setup_wizard import SetupPlan, SetupResult, run_setup


def _ok(client: str = "claude-desktop") -> setup_config.ClientResult:
    return setup_config.ClientResult(client, "OK", "registered", True)


def _fail(client: str = "codex") -> setup_config.ClientResult:
    return setup_config.ClientResult(client, "FAIL", "boom")


def test_run_setup_runs_init_register_index_in_order() -> None:
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

    result = run_setup(SetupPlan(), init_fn=init_fn, index_fn=index_fn, register_fn=register_fn)

    assert calls == ["init", "register", "index"]
    assert result.config_created is True
    assert result.indexed is True
    assert result.index_error is None
    assert result.client_results == [_ok()]
    assert result.successful is True
    assert result.warnings == []


def test_run_setup_resets_before_init_when_explicitly_requested() -> None:
    calls: list[str] = []

    result = run_setup(
        SetupPlan(reset=True, build_index=False),
        reset_fn=lambda: (
            calls.append("reset")
            or setup_config.ResetResult(config_removed=True, data_home_removed=True)
        ),
        init_fn=lambda *, assume_yes: calls.append("init") or True,
        index_fn=lambda: {},
        register_fn=lambda python_exe, *, clients: calls.append("register") or [_ok()],
    )

    assert calls == ["reset", "init", "register"]
    assert result.reset is True


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
    assert result.index_error is None
    assert result.config_created is False


def test_run_setup_defers_index_failure_after_registering_clients() -> None:
    calls: list[str] = []

    def index_fn() -> dict[str, int]:
        calls.append("index")
        raise RuntimeError("model unavailable")

    result = run_setup(
        SetupPlan(),
        init_fn=lambda *, assume_yes: calls.append("init") or True,
        index_fn=index_fn,
        register_fn=lambda python_exe, *, clients: calls.append("register") or [_ok()],
    )

    assert calls == ["init", "register", "index"]
    assert result.client_results == [_ok()]
    assert result.indexed is False
    assert result.index_error == "RuntimeError: model unavailable"
    assert result.successful is True


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

    assert cli.main(["setup", "--reset", "--yes", "--no-index"]) == 0
    assert received == ["--reset", "--yes", "--no-index"]


def test_setup_main_reports_deferred_index_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = SetupResult(
        config_created=True,
        indexed=False,
        index_error="RuntimeError: model unavailable",
        client_results=[_ok()],
    )
    monkeypatch.setattr(setup_wizard, "run_setup", lambda plan: result)

    assert setup_wizard.main(["--yes"]) == 0
    output = capsys.readouterr().out
    assert "index deferred: RuntimeError: model unavailable" in output
    assert "Run `cortex sync` when the model is available." in output


def test_interactive_setup_explains_prompts_and_preserves_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []
    plans: list[SetupPlan] = []

    def output(message: str) -> None:
        events.append(("output", message))

    def answer(prompt: str) -> str:
        events.append(("prompt", prompt))
        return ""

    def run(plan: SetupPlan) -> SetupResult:
        plans.append(plan)
        return SetupResult(True, True, None, [_ok()])

    monkeypatch.setattr(setup_wizard, "run_setup", run)

    assert setup_wizard.main([], input_fn=answer, output_fn=output) == 0
    assert plans == [SetupPlan(clients="all", build_index=True)]
    prompt_indexes = [index for index, event in enumerate(events) if event[0] == "prompt"]
    assert len(prompt_indexes) == 2
    for prompt_index in prompt_indexes:
        guidance = [message for _, message in events[prompt_index - 3 : prompt_index]]
        assert guidance[0].startswith("  Option:")
        assert guidance[1].startswith("  Default:")
        assert guidance[2].startswith("  Consequence:")


def test_interactive_reset_defaults_to_cancel_before_any_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output: list[str] = []

    def forbidden(_plan: SetupPlan) -> SetupResult:
        raise AssertionError("setup must not run after reset is declined")

    monkeypatch.setattr(setup_wizard, "run_setup", forbidden)

    assert setup_wizard.main(
        ["--reset", "--clients", "all", "--no-index"],
        input_fn=lambda _prompt: "",
        output_fn=output.append,
    ) == 0
    assert output[-1] == "Reset cancelled; nothing changed."
    assert output[-3].startswith("  Default: no")


def test_setup_yes_keeps_defaults_without_guidance_or_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans: list[SetupPlan] = []
    guidance: list[str] = []

    def forbidden(_prompt: str) -> str:
        raise AssertionError("input must not be called in non-interactive mode")

    def run(plan: SetupPlan) -> SetupResult:
        plans.append(plan)
        return SetupResult(True, True, None, [_ok()])

    monkeypatch.setattr(setup_wizard, "run_setup", run)

    assert setup_wizard.main(
        ["--yes"],
        input_fn=forbidden,
        output_fn=guidance.append,
    ) == 0
    assert plans == [SetupPlan(clients="all", build_index=True, assume_yes=True)]
    assert guidance == []
