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
"""The command lines a desktop client builds, parsed by the parsers that run them."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

import cli
import cli_surface
import config_command
import search_command
import sync_command
from _version import __version__
from confluence_writer import cli as confluence_cli
from ingestion import cli as ingestion_cli

_CONFIG = str(Path("C:/fixtures/confluence.toml"))
_INGESTION = str(Path("C:/fixtures/ingestion.toml"))
_HASH = "a" * 64


@pytest.mark.parametrize(
    ("arguments", "command", "expected"),
    [
        (["sync", "--json"], "sync", {"section": None, "json": True, "search": None}),
        (
            ["search", "plan d'action", "--json", "--section", "docs", "--source-kind", "doc"],
            "search",
            {"query": "plan d'action", "json": True, "section": "docs", "source_kind": "doc"},
        ),
        (
            ["search", "plan d'action", "--json"],
            "search",
            {"query": "plan d'action", "json": True, "section": None, "source_kind": None},
        ),
        (
            ["ingestion", "--config", _INGESTION, "due", "doc"],
            "ingestion",
            {"command": "due", "config": Path(_INGESTION), "source_kind": "doc"},
        ),
        (
            ["confluence", "--config", _CONFIG, "catalog", "PN", "--json"],
            "confluence",
            {"command": "catalog", "config": Path(_CONFIG), "space_key": "PN", "json": True},
        ),
        (
            ["confluence", "--config", _CONFIG, "source-status", "--json"],
            "confluence",
            {"command": "source-status", "config": Path(_CONFIG), "json": True},
        ),
        (
            ["confluence", "--config", _CONFIG, "pages", "--json"],
            "confluence",
            {"command": "pages", "config": Path(_CONFIG), "json": True},
        ),
        (
            ["confluence", "--config", _CONFIG, "resolve", "https://wiki.test/x/AA", "--json"],
            "confluence",
            {"command": "resolve", "reference": "https://wiki.test/x/AA", "json": True},
        ),
        (
            ["confluence", "--config", _CONFIG, "preview", "2134730685", "--json"],
            "confluence",
            {"command": "preview", "reference": "2134730685", "json": True},
        ),
        (
            ["confluence", "--config", _CONFIG, "sync"],
            "confluence",
            {"command": "sync", "config": Path(_CONFIG), "force": False},
        ),
        (
            ["confluence", "--config", _CONFIG, "sync", "--force"],
            "confluence",
            {"command": "sync", "force": True},
        ),
        (
            ["confluence", "--config", _CONFIG, "--ingestion-config", _INGESTION, "sync"],
            "confluence",
            {"command": "sync", "config": Path(_CONFIG), "ingestion_config": Path(_INGESTION)},
        ),
        (["config", "get", "--json"], "config", {"operation": "get", "json": True}),
        (
            ["config", "set", "--json", "--expected-hash", _HASH, "--kb-path", "C:/kb"],
            "config",
            {"operation": "set", "expected_hash": _HASH, "kb_path": "C:/kb"},
        ),
        (
            ["config", "set", "--json", "--expect-absent", "--kb-path", "C:/kb"],
            "config",
            {"operation": "set", "expect_absent": True, "expected_hash": None},
        ),
    ],
)
def test_every_desktop_line_lands_its_values_in_the_right_slots(
    arguments: list[str], command: str, expected: dict[str, Any]
) -> None:
    invocation = cli_surface.parse_invocation(arguments)
    assert invocation.command == command
    assert {key: getattr(invocation.namespace, key) for key in expected} == expected


def test_version_flag_prints_exactly_the_package_version() -> None:
    invocation = cli_surface.parse_invocation(["--version"])
    assert invocation.command is None
    assert invocation.output == __version__


@pytest.mark.parametrize(
    "arguments",
    [
        ["catalogue", "PN", "--json"],
        ["confluence", "catalog", "--config", _CONFIG, "PN", "--json"],
        ["confluence", "--config", _CONFIG, "catalog", "PN"],
        ["config", "set", "--json", "--kb-path", "C:/kb", "--expected-sha", _HASH],
        ["search", "plan", "--json", "--source-kind", "confluence"],
        ["ingestion", "due", "doc", "--config", _INGESTION],
        ["--release"],
    ],
)
def test_a_line_the_console_would_refuse_is_refused_here(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as refusal:
        cli_surface.parse_invocation(arguments)
    assert refusal.value.code == cli._ARGPARSE_USAGE_EXIT


def test_a_command_without_machine_parser_is_reported_as_such_not_as_a_usage_error() -> None:
    with pytest.raises(cli_surface.UnsupportedInvocationError, match="cortex doctor"):
        cli_surface.parse_invocation(["doctor", "--json"])


def test_machine_commands_are_a_subset_of_the_root_commands() -> None:
    root = {name for name, _ in cli._COMMANDS}
    assert set(cli_surface.machine_commands()) <= root


class _ParserUsed(Exception):
    """Raised by a spy parser so a test can prove which builder the command went through."""


def _spy(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    class SpyParser(argparse.ArgumentParser):
        def parse_args(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
            raise _ParserUsed

        def parse_known_args(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
            raise _ParserUsed

    monkeypatch.setattr(module, "build_parser", lambda *args, **kwargs: SpyParser())


def test_the_root_dispatcher_parses_through_the_exposed_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spy(monkeypatch, cli)
    with pytest.raises(_ParserUsed):
        cli.main(["--version"])


@pytest.mark.parametrize(
    ("module", "arguments"),
    [
        (confluence_cli, ["pages", "--json"]),
        (config_command, ["get", "--json"]),
        (ingestion_cli, ["due", "doc"]),
    ],
)
def test_each_command_parses_through_its_exposed_builder(
    monkeypatch: pytest.MonkeyPatch, module: Any, arguments: list[str]
) -> None:
    _spy(monkeypatch, module)
    with pytest.raises(_ParserUsed):
        module.main(arguments)


@pytest.mark.parametrize(
    ("module", "entry_point", "arguments"),
    [
        (sync_command, "main", ["--json"]),
        (search_command, "search_main", ["plan", "--json"]),
    ],
)
def test_the_indexer_entry_points_parse_through_the_exposed_builders(
    monkeypatch: pytest.MonkeyPatch, module: Any, entry_point: str, arguments: list[str]
) -> None:
    indexer = pytest.importorskip("indexer")
    _spy(monkeypatch, module)
    with pytest.raises(_ParserUsed):
        getattr(indexer, entry_point)(arguments)
