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
"""Safe multi-client MCP registration tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

import setup_config


def _which(mapping: dict[str, str]):
    return lambda name: mapping.get(name)


def _make_detected_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    appdata = tmp_path / "appdata"
    home = tmp_path / "home"
    claude = appdata / "Claude" / "claude_desktop_config.json"
    codex = home / ".codex" / "config.toml"
    gemini = home / ".gemini" / "settings.json"
    for path in (claude, codex, gemini):
        path.parent.mkdir(parents=True, exist_ok=True)
    return claude, codex, gemini


def _register(
    tmp_path: Path,
    clients: str,
    *,
    which=None,
    runner=None,
) -> list[setup_config.ClientResult]:
    kwargs: dict[str, Any] = {
        "clients": clients,
        "environ": {"APPDATA": str(tmp_path / "appdata")},
        "home": tmp_path / "home",
        "which": which or _which({}),
    }
    if runner is not None:
        kwargs["runner"] = runner
    return setup_config.register_clients(sys.executable, **kwargs)


def test_registry_declares_paths_formats_and_entries(tmp_path: Path) -> None:
    registry = setup_config.client_registry(
        sys.executable,
        environ={"APPDATA": str(tmp_path / "appdata")},
        home=tmp_path / "home",
        which=_which({"claude": "claude", "codex": "codex", "gemini": "gemini"}),
    )

    assert tuple(registry) == setup_config.CLIENT_NAMES
    assert registry["claude-desktop"].config_path == (
        tmp_path / "appdata" / "Claude" / "claude_desktop_config.json"
    )
    assert registry["gemini"].config_path == tmp_path / "home" / ".gemini" / "settings.json"
    assert registry["codex"].config_path == tmp_path / "home" / ".codex" / "config.toml"
    assert registry["codex"].config_format == "toml-table:mcp_servers.cortex"
    assert registry["claude-code"].config_format == "claude-cli-user-scope"
    assert registry["gemini"].entry["args"] == [str(setup_config.SERVER_PY)]


def test_registry_respects_home_and_appdata_environment(tmp_path: Path) -> None:
    registry = setup_config.client_registry(
        sys.executable,
        environ={
            "HOME": str(tmp_path / "fake-home"),
            "APPDATA": str(tmp_path / "fake-appdata"),
        },
        which=_which({}),
    )

    assert registry["codex"].config_path == tmp_path / "fake-home" / ".codex" / "config.toml"
    assert registry["gemini"].config_path == (
        tmp_path / "fake-home" / ".gemini" / "settings.json"
    )


@pytest.mark.parametrize("client", ["claude-desktop", "codex", "gemini"])
def test_file_client_registration_is_idempotent(tmp_path: Path, client: str) -> None:
    claude, codex, gemini = _make_detected_paths(tmp_path)
    paths = {"claude-desktop": claude, "codex": codex, "gemini": gemini}

    first = _register(tmp_path, client)
    first_bytes = paths[client].read_bytes()
    first_backups = sorted(paths[client].parent.glob(f"{paths[client].name}.*.bak"))
    second = _register(tmp_path, client)

    assert first == [setup_config.ClientResult(client, "OK", first[0].message, True)]
    assert second == [setup_config.ClientResult(client, "OK", "already registered")]
    assert paths[client].read_bytes() == first_bytes
    assert sorted(paths[client].parent.glob(f"{paths[client].name}.*.bak")) == first_backups


def test_json_foreign_keys_and_servers_are_preserved_with_backup(tmp_path: Path) -> None:
    claude, _, _ = _make_detected_paths(tmp_path)
    original = {
        "theme": "dark",
        "mcpServers": {
            "foreign": {"command": "foreign", "args": ["serve"]},
            "cortex": {"command": "old", "args": ["old.py"]},
        },
    }
    claude.write_text(json.dumps(original), encoding="utf-8")

    result = _register(tmp_path, "claude-desktop")
    updated = json.loads(claude.read_text(encoding="utf-8"))
    backups = list(claude.parent.glob(f"{claude.name}.*.bak"))

    assert result[0].changed
    assert updated["theme"] == "dark"
    assert updated["mcpServers"]["foreign"] == original["mcpServers"]["foreign"]
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == json.dumps(original)


def test_client_replacement_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claude, _, _ = _make_detected_paths(tmp_path)
    claude.write_text("{}", encoding="utf-8")
    real_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(setup_config.os, "replace", recording_replace)

    _register(tmp_path, "claude-desktop")

    assert len(replacements) == 1
    assert replacements[0][0].parent == claude.parent
    assert replacements[0][1] == claude


def test_codex_preserves_non_cortex_bytes_and_unknown_cortex_keys(
    tmp_path: Path,
) -> None:
    _, codex, _ = _make_detected_paths(tmp_path)
    prefix = (
        '# user comment\r\nmodel = "custom"\r\n\r\n[mcp_servers.other]\r\n'
        'command = "other"\r\n\r\n'
    )
    cortex = (
        '[mcp_servers.cortex]\r\ncommand = "old"\r\nargs = ["old.py"]\r\n'
        "enabled = true # keep\r\n"
    )
    suffix = '\r\n[projects."workspace"]\r\ntrust_level = "trusted"\r\n'
    codex.write_bytes((prefix + cortex + suffix).encode("utf-8"))

    _register(tmp_path, "codex")
    updated = codex.read_bytes().decode("utf-8")

    assert updated.startswith(prefix)
    assert updated.endswith(suffix)
    assert "enabled = true # keep\n" in updated.replace("\r\n", "\n")
    assert '[mcp_servers.other]\ncommand = "other"' in updated.replace("\r\n", "\n")


@pytest.mark.parametrize(
    ("client", "content"),
    [
        ("claude-desktop", "{not-json"),
        ("gemini", "[]"),
        ("codex", '[mcp_servers.cortex\ncommand = "broken"'),
    ],
)
def test_corrupt_client_config_aborts_without_writing(
    tmp_path: Path, client: str, content: str
) -> None:
    claude, codex, gemini = _make_detected_paths(tmp_path)
    paths = {"claude-desktop": claude, "codex": codex, "gemini": gemini}
    path = paths[client]
    path.write_text(content, encoding="utf-8")

    results = _register(tmp_path, client)

    assert results[0].status == "FAIL"
    assert path.read_text(encoding="utf-8") == content
    assert list(path.parent.glob(f"{path.name}.*.bak")) == []


def test_preflight_failure_prevents_other_selected_writes(tmp_path: Path) -> None:
    claude, codex, _ = _make_detected_paths(tmp_path)
    claude.write_text('{"foreign": true}', encoding="utf-8")
    codex.write_text("not = valid = toml", encoding="utf-8")
    before = claude.read_bytes()

    results = _register(tmp_path, "claude-desktop,codex")

    assert results[0].client == "codex"
    assert results[0].status == "FAIL"
    assert claude.read_bytes() == before
    assert list(claude.parent.glob(f"{claude.name}.*.bak")) == []


def test_absent_client_is_clean_skip(tmp_path: Path) -> None:
    results = _register(tmp_path, "gemini")

    assert results == [
        setup_config.ClientResult("gemini", "SKIP", "client not installed")
    ]
    assert not (tmp_path / "home" / ".gemini").exists()


def test_default_selection_contains_only_detected_clients(tmp_path: Path) -> None:
    (tmp_path / "home" / ".codex").mkdir(parents=True)
    results = _register(tmp_path, None)

    assert [result.client for result in results] == ["codex"]


def test_claude_code_uses_documented_user_scope_cli_and_is_idempotent(
    tmp_path: Path,
) -> None:
    state = {"registered": False}
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        if command[1:4] == ["mcp", "get", "cortex"]:
            if not state["registered"]:
                return setup_config.subprocess.CompletedProcess(command, 1, "", "missing")
            output = f"{Path(sys.executable).resolve()} {setup_config.SERVER_PY}"
            return setup_config.subprocess.CompletedProcess(command, 0, output, "")
        assert command[1:6] == ["mcp", "add", "--scope", "user", "cortex"]
        state["registered"] = True
        return setup_config.subprocess.CompletedProcess(command, 0, "added", "")

    which = _which({"claude": "claude"})
    first = _register(tmp_path, "claude-code", which=which, runner=runner)
    second = _register(tmp_path, "claude-code", which=which, runner=runner)

    assert first[0].changed
    assert second == [
        setup_config.ClientResult(
            "claude-code", "OK", "already registered at user scope"
        )
    ]
    assert sum(call[1:3] == ["mcp", "add"] for call in calls) == 1


def test_check_reports_entry_and_valid_paths(tmp_path: Path) -> None:
    _make_detected_paths(tmp_path)
    _register(tmp_path, "codex")

    results = setup_config.check_clients(
        sys.executable,
        clients="codex,gemini",
        environ={"APPDATA": str(tmp_path / "appdata")},
        home=tmp_path / "home",
        which=_which({}),
    )

    assert results[0].status == "OK"
    assert results[1].status == "FAIL"
    assert "missing" in results[1].message
