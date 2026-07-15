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
"""Tests for the thin installed console dispatcher."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

import cli
from _version import __version__


@pytest.mark.parametrize(
    ("command", "arguments", "module_name"),
    [
        ("sync", ["knowledge"], "indexer"),
        ("doctor", ["--json"], "doctor"),
    ],
)
def test_direct_subcommands_dispatch_existing_main(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    arguments: list[str],
    module_name: str,
) -> None:
    received: list[str] = []
    module = ModuleType(module_name)

    def fake_main(argv: list[str]) -> int:
        received.extend(argv)
        return 7

    module.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)

    assert cli.main([command, *arguments]) == 7
    assert received == arguments


def test_serve_dispatches_server_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    module = ModuleType("server")

    def fake_run_stdio() -> None:
        calls.append("serve")

    module.run_stdio = fake_run_stdio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "server", module)

    assert cli.main(["serve"]) == 0
    assert calls == ["serve"]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("init", ["--init"]),
        ("register", []),
        ("check", ["--check"]),
    ],
)
def test_setup_subcommands_add_only_their_existing_flag(
    monkeypatch: pytest.MonkeyPatch, command: str, expected: list[str]
) -> None:
    received: list[str] = []

    def fake_setup(arguments: list[str]) -> int:
        received.extend(arguments)
        return 3

    monkeypatch.setattr(cli, "_run_setup", fake_setup)

    assert cli.main([command, "--clients", "all"]) == 3
    assert received == [*expected, "--clients", "all"]


def test_register_forwards_non_interactive_yes_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str] = []

    def fake_setup(arguments: list[str]) -> int:
        received.extend(arguments)
        return 0

    monkeypatch.setattr(cli, "_run_setup", fake_setup)

    assert cli.main(["register", "--yes"]) == 0
    assert received == ["--yes"]


def test_version_uses_package_single_source(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--version"])

    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == __version__
