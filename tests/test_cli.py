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

import logging
import sys
from types import ModuleType

import pytest

import cli
from _version import __version__


@pytest.mark.parametrize(
    ("command", "arguments", "module_name", "expected_prog"),
    [
        ("sync", ["knowledge"], "indexer", "cortex sync"),
        ("doctor", ["--json"], "doctor", None),
    ],
)
def test_direct_subcommands_dispatch_existing_main(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    arguments: list[str],
    module_name: str,
    expected_prog: str | None,
) -> None:
    received: list[str] = []
    progs: list[str | None] = []
    module = ModuleType(module_name)

    def fake_main(argv: list[str], *, prog: str | None = None) -> int:
        received.extend(argv)
        progs.append(prog)
        return 7

    module.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)

    assert cli.main([command, *arguments]) == 7
    assert received == arguments
    assert progs == [expected_prog]


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
        ("unregister", ["--unregister"]),
        ("check", ["--check"]),
    ],
)
def test_setup_subcommands_add_only_their_existing_flag(
    monkeypatch: pytest.MonkeyPatch, command: str, expected: list[str]
) -> None:
    received: list[str] = []
    progs: list[str] = []

    def fake_setup(arguments: list[str], *, prog: str) -> int:
        received.extend(arguments)
        progs.append(prog)
        return 3

    monkeypatch.setattr(cli, "_run_setup", fake_setup)

    assert cli.main([command, "--clients", "all"]) == 3
    assert received == [*expected, "--clients", "all"]
    assert progs == [f"cortex {command}"]


def test_register_forwards_non_interactive_yes_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str] = []

    def fake_setup(arguments: list[str], *, prog: str) -> int:
        received.extend(arguments)
        assert prog == "cortex register"
        return 0

    monkeypatch.setattr(cli, "_run_setup", fake_setup)

    assert cli.main(["register", "--yes"]) == 0
    assert received == ["--yes"]


def test_version_uses_package_single_source(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--version"])

    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_root_help_describes_every_public_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`cortex --help` must explain the surface, not just list bare names."""
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])

    assert raised.value.code == 0
    rendered = capsys.readouterr().out
    for name, summary in cli._COMMANDS:
        assert name in rendered
        assert summary.split(" (")[0].split(".")[0][:40] in " ".join(rendered.split())


def test_subcommand_help_names_the_typed_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The usage line must be copy-pasteable, so it has to include the command.

    Rendering help runs the real subcommand entry point, so the Cortex logger is
    restored afterwards: a handler bound to a capture stream that pytest later
    closes would silently break logging assertions in every subsequent test.
    """
    cortex_logger = logging.getLogger("cortex")
    preserved = list(cortex_logger.handlers)
    try:
        with pytest.raises(SystemExit) as raised:
            cli.main(["sync", "--help"])
    finally:
        cortex_logger.handlers[:] = preserved

    assert raised.value.code == 0
    assert capsys.readouterr().out.startswith("usage: cortex sync")
