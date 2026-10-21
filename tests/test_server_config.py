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
"""The `[server]` table: validation, rendering, mutation and its own JSON contract."""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

import pytest

import config_command
from confluence_writer.constants import EXIT_CONFLICT, EXIT_ERROR, EXIT_INVALID_INPUT, EXIT_OK
from daemon_contract import DEFAULT_IDLE_TIMEOUT_SECONDS, DEFAULT_SERVER_MODE
from user_config import CortexConfigError, load_user_config, render_user_config
from user_config_mutation import (
    UserConfigInvalidBaseError,
    write_server_settings_cas,
    write_user_config_cas,
)

_BASE = 'schema_version = 1\nkb_path = "G:/kb"\n'


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "APPDATA": str(tmp_path / "appdata"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }


def _config_path(environment: dict[str, str]) -> Path:
    return Path(environment["APPDATA"]) / "Cortex" / "config.toml"


def _write(environment: dict[str, str], body: str) -> Path:
    path = _config_path(environment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    return path


def _run(environment: dict[str, str], *arguments: str) -> tuple[int, dict[str, object]]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = config_command.main(list(arguments), environ=environment)
    return code, json.loads(stream.getvalue())


def test_absent_table_resolves_to_per_client_and_fifteen_minutes(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(_BASE, encoding="utf-8")
    config = load_user_config(path=path, environ={})
    assert config.server_mode == DEFAULT_SERVER_MODE == "per-client"
    assert config.server_idle_timeout_seconds == DEFAULT_IDLE_TIMEOUT_SECONDS == 900


def test_table_values_are_read(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(_BASE + '\n[server]\nmode = "shared"\nidle_timeout_seconds = 0\n')
    config = load_user_config(path=path, environ={})
    assert config.server_mode == "shared"
    assert config.server_idle_timeout_seconds == 0


@pytest.mark.parametrize(
    "table",
    [
        'server = "shared"\n',
        '[server]\nmode = "pooled"\n',
        "[server]\nmode = 1\n",
        "[server]\nidle_timeout_seconds = -1\n",
        "[server]\nidle_timeout_seconds = 1.5\n",
        "[server]\nidle_timeout_seconds = true\n",
        '[server]\nport = 8080\n',
    ],
)
def test_invalid_table_is_refused(tmp_path: Path, table: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(_BASE + table, encoding="utf-8")
    with pytest.raises(CortexConfigError):
        load_user_config(path=path, environ={})


def test_default_table_is_not_rendered_and_a_chosen_one_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(_BASE, encoding="utf-8")
    config = load_user_config(path=path, environ={})
    assert "[server]" not in render_user_config(config)

    chosen = replace(config, server_mode="shared", server_idle_timeout_seconds=60)
    rendered = render_user_config(chosen)
    assert rendered.endswith('[server]\nmode = "shared"\nidle_timeout_seconds = 60\n')
    path.write_text(rendered, encoding="utf-8")
    assert load_user_config(path=path, environ={}) == chosen


def test_server_settings_mutation_validates_before_writing(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _write(environment, _BASE)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="server mode"):
        write_server_settings_cas(path, mode="pooled", expected_hash=digest, environ=environment)
    with pytest.raises(ValueError, match="idle_timeout_seconds"):
        write_server_settings_cas(
            path, idle_timeout_seconds=-1, expected_hash=digest, environ=environment
        )
    with pytest.raises(ValueError, match="at least one"):
        write_server_settings_cas(path, expected_hash=digest, environ=environment)
    assert path.read_text(encoding="utf-8") == _BASE

    write_server_settings_cas(
        path, idle_timeout_seconds=30, expected_hash=digest, environ=environment
    )
    config = load_user_config(path=path, environ={})
    assert (config.server_mode, config.server_idle_timeout_seconds) == ("per-client", 30)


def test_server_mode_needs_a_recorded_knowledge_base(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _write(environment, "schema_version = 1\n")
    with pytest.raises(UserConfigInvalidBaseError):
        write_server_settings_cas(
            path,
            mode="shared",
            expected_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            environ=environment,
        )


def test_kb_path_change_preserves_the_server_table(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _write(environment, _BASE + '\n[server]\nmode = "shared"\nidle_timeout_seconds = 5\n')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    write_user_config_cas(path, kb_path="G:/other", expected_hash=digest, environ=environment)
    config = load_user_config(path=path, environ={})
    assert (config.kb_path, config.server_mode, config.server_idle_timeout_seconds) == (
        "G:/other",
        "shared",
        5,
    )


def test_config_server_reports_the_table_in_its_own_contract(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _write(environment, _BASE + '\n[server]\nmode = "shared"\n')

    code, payload = _run(environment, "server", "--json")

    assert code == EXIT_OK
    assert payload == {
        "contract_version": 1,
        "operation": "config_server",
        "status": "succeeded",
        "present": True,
        "content_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "valid": True,
        "error": None,
        "values": {"mode": "shared", "idle_timeout_seconds": 900},
    }


def test_config_get_document_is_unchanged_by_the_table(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    _write(environment, _BASE + '\n[server]\nmode = "shared"\n')

    code, payload = _run(environment, "get", "--json")

    assert code == EXIT_OK
    assert payload["valid"] is True
    values = payload["values"]
    assert isinstance(values, dict)
    assert "server_mode" not in values and len(values) == 11


def test_set_server_mode_swaps_and_reports(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _write(environment, _BASE)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    code, payload = _run(
        environment, "set-server-mode", "shared", "--json", "--expected-hash", before
    )

    assert code == EXIT_OK
    assert payload["operation"] == "config_set_server_mode"
    assert payload["status"] == "succeeded"
    assert payload["previous_content_hash"] == before
    assert payload["content_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert payload["values"] == {"mode": "shared", "idle_timeout_seconds": 900}
    assert load_user_config(path=path, environ={}).server_mode == "shared"

    current = str(payload["content_hash"])
    code, payload = _run(
        environment, "set-server-mode", "shared", "--json", "--expected-hash", current
    )
    assert code == EXIT_OK
    assert payload["status"] == "unchanged"

    code, payload = _run(
        environment, "set-server-mode", "per-client", "--json", "--expected-hash", current
    )
    assert code == EXIT_OK
    assert "[server]" not in path.read_text(encoding="utf-8")


def test_set_server_mode_requires_a_well_formed_hash(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    _write(environment, _BASE)
    code, payload = _run(
        environment, "set-server-mode", "shared", "--json", "--expected-hash", "nothex"
    )
    assert code == EXIT_INVALID_INPUT
    assert payload["status"] == "failed"


def test_set_server_mode_refuses_a_stale_hash(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    _write(environment, _BASE)

    code, payload = _run(
        environment, "set-server-mode", "shared", "--json", "--expected-hash", "0" * 64
    )

    assert code == EXIT_CONFLICT
    assert payload["status"] == "conflict"


def test_set_server_mode_without_valid_configuration_fails(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _write(environment, "schema_version = 1\nnope = 1\n")
    code, payload = _run(
        environment,
        "set-server-mode",
        "shared",
        "--json",
        "--expected-hash",
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    assert code == EXIT_ERROR
    assert payload["error"] == {
        "code": "invalid_configuration",
        "phase": "validate",
        "path": None,
    }
