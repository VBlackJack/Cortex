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
"""End-to-end machine contract tests for the user configuration command."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from confluence_writer.constants import (
    EXIT_CONFLICT,
    EXIT_INVALID_INPUT,
    EXIT_LOCKED,
    EXIT_OK,
)
from user_config import load_user_config, render_user_config
from user_config_mutation import user_config_backup_path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_LOCK_WORKER = Path(__file__).parent / "fixtures" / "confluence_config_mutation_worker.py"
_INVALID_CONFIGURATIONS = (
    pytest.param(
        "schema_version = 1\nthis is not valid TOML [\n",
        id="invalid-toml",
    ),
    pytest.param(
        "schema_version = 1\nnope_unknown_key = 42\n",
        id="unknown-key",
    ),
    pytest.param("schema_version = 99\n", id="future-version"),
    pytest.param(
        "schema_version = 1\nkb_path = 42\n",
        id="invalid-type",
    ),
)


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("CORTEX_")
    }
    environment["APPDATA"] = str(tmp_path / "appdata")
    environment["LOCALAPPDATA"] = str(tmp_path / "localappdata")
    return environment


def _config_path(environment: dict[str, str]) -> Path:
    return Path(environment["APPDATA"]) / "Cortex" / "config.toml"


def _rendered_config(
    path: Path,
    environment: dict[str, str],
    kb_path: str,
) -> bytes:
    defaults = load_user_config(path=path, environ=environment)
    return render_user_config(replace(defaults, kb_path=kb_path)).encode("utf-8")


def _run_cli(
    environment: dict[str, str],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "cli.py", *arguments],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _payload(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.stderr == ""
    return json.loads(completed.stdout)


def test_get_valid_config_returns_raw_hash_and_all_values(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    content = _rendered_config(path, environment, "G:/Knowledge")
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    completed = _run_cli(environment, "config", "get", "--json")
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    assert payload["operation"] == "config_get"
    assert payload["status"] == "succeeded"
    assert payload["present"] is True
    assert payload["content_hash"] == hashlib.sha256(content).hexdigest()
    assert payload["valid"] is True
    assert payload["error"] is None
    assert isinstance(payload["values"], dict)
    assert len(payload["values"]) == 11


def test_get_absent_config_is_valid_and_present_false(tmp_path: Path) -> None:
    environment = _environment(tmp_path)

    completed = _run_cli(environment, "config", "get", "--json")
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    assert payload["present"] is False
    assert payload["content_hash"] is None
    assert payload["valid"] is True
    assert isinstance(payload["values"], dict)


@pytest.mark.parametrize("config_body", _INVALID_CONFIGURATIONS)
def test_get_invalid_config_describes_invalidity_without_failure(
    tmp_path: Path,
    config_body: str,
) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    path.parent.mkdir(parents=True)
    path.write_text(config_body, encoding="utf-8")

    completed = _run_cli(environment, "config", "get", "--json")
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    assert "Traceback" not in completed.stderr
    assert payload["status"] == "succeeded"
    assert payload["present"] is True
    assert payload["valid"] is False
    assert payload["error"] == {
        "code": "invalid_configuration",
        "phase": "validate",
        "path": None,
    }
    assert payload["values"] is None


def test_set_expect_absent_creates_canonical_config(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)

    completed = _run_cli(
        environment,
        "config",
        "set",
        "--json",
        "--expect-absent",
        "--kb-path",
        "G:/Created",
    )
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    assert payload["status"] == "succeeded"
    assert payload["changed"] is True
    assert payload["previous_content_hash"] is None
    assert payload["content_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert payload["backup_written"] is False
    assert payload["rebuilt_from_defaults"] is False
    assert payload["restart_required"] is True
    assert payload["reindex_required"] is True
    assert load_user_config(path=path, environ=environment).kb_path == "G:/Created"


def test_set_valid_config_updates_path_and_preserves_exact_backup(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    previous = _rendered_config(path, environment, "G:/Before").replace(b"\n", b"\r\n")
    path.parent.mkdir(parents=True)
    path.write_bytes(previous)

    completed = _run_cli(
        environment,
        "config",
        "set",
        "--json",
        "--expected-hash",
        hashlib.sha256(previous).hexdigest(),
        "--kb-path",
        "G:/After",
    )
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    assert payload["status"] == "succeeded"
    assert payload["changed"] is True
    assert payload["backup_written"] is True
    assert payload["rebuilt_from_defaults"] is False
    assert payload["restart_required"] is True
    assert payload["reindex_required"] is True
    assert user_config_backup_path(path).read_bytes() == previous
    assert load_user_config(path=path, environ=environment).kb_path == "G:/After"


def test_set_stale_hash_reports_conflict_and_preserves_external_bytes(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    initial = _rendered_config(path, environment, "G:/Initial")
    external = _rendered_config(path, environment, "G:/External")
    path.parent.mkdir(parents=True)
    path.write_bytes(external)

    completed = _run_cli(
        environment,
        "config",
        "set",
        "--json",
        "--expected-hash",
        hashlib.sha256(initial).hexdigest(),
        "--kb-path",
        "G:/Caller",
    )
    payload = _payload(completed)

    assert completed.returncode == EXIT_CONFLICT
    assert payload["status"] == "conflict"
    assert payload["changed"] is False
    assert payload["error"] == {
        "code": "hash_mismatch",
        "phase": "compare",
        "path": None,
    }
    assert path.read_bytes() == external


@pytest.mark.parametrize("config_body", _INVALID_CONFIGURATIONS)
def test_set_invalid_config_rebuilds_and_preserves_invalid_backup(
    tmp_path: Path,
    config_body: str,
) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    invalid = config_body.encode("utf-8")
    path.parent.mkdir(parents=True)
    path.write_bytes(invalid)

    completed = _run_cli(
        environment,
        "config",
        "set",
        "--json",
        "--expected-hash",
        hashlib.sha256(invalid).hexdigest(),
        "--kb-path",
        "G:/Repaired",
    )
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    assert payload["status"] == "succeeded"
    assert payload["rebuilt_from_defaults"] is True
    assert payload["reindex_required"] is True
    assert user_config_backup_path(path).read_bytes() == invalid
    assert load_user_config(path=path, environ=environment).kb_path == "G:/Repaired"


def test_set_identical_value_is_unchanged_without_backup(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    content = _rendered_config(path, environment, "G:/Stable")
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    completed = _run_cli(
        environment,
        "config",
        "set",
        "--json",
        "--expected-hash",
        hashlib.sha256(content).hexdigest(),
        "--kb-path",
        "G:/Stable",
    )
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    assert payload["status"] == "unchanged"
    assert payload["changed"] is False
    assert payload["backup_written"] is False
    assert payload["restart_required"] is False
    assert payload["reindex_required"] is False
    assert not user_config_backup_path(path).exists()


@pytest.mark.parametrize(
    "arguments",
    (
        ("--expected-hash", "NOTAHASH", "--kb-path", "G:/Knowledge"),
        ("--kb-path", "G:/Knowledge"),
        ("--expect-absent", "--expected-hash", "0" * 64, "--kb-path", "G:/Knowledge"),
        ("--expect-absent", "--kb-path", ""),
    ),
)
def test_set_invalid_arguments_return_structured_invalid_input(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)

    completed = _run_cli(environment, "config", "set", "--json", *arguments)
    payload = _payload(completed)

    assert completed.returncode == EXIT_INVALID_INPUT
    assert payload["status"] == "failed"
    assert payload["changed"] is False
    assert payload["error"] == {
        "code": "invalid_argument",
        "phase": "validate",
        "path": None,
    }
    assert not path.exists()


@pytest.mark.parametrize("module", ("config_contract", "config_command"))
def test_config_modules_import_with_invalid_user_config(
    tmp_path: Path,
    module: str,
) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    path.parent.mkdir(parents=True)
    path.write_text("schema_version = 99\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == EXIT_OK, completed.stderr


def _wait_for_ready(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15.0
    while not path.exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            break
        time.sleep(0.02)
    assert path.exists()


def test_set_while_real_process_holds_lock_is_locked_without_mutation(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    ready = tmp_path / "holder.ready"
    release = tmp_path / "holder.release"
    holder = subprocess.Popen(
        [sys.executable, str(_LOCK_WORKER), "hold", str(path), str(ready), str(release)],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        text=True,
    )
    try:
        _wait_for_ready(ready, holder)
        completed = _run_cli(
            environment,
            "config",
            "set",
            "--json",
            "--expect-absent",
            "--kb-path",
            "G:/Locked",
        )
        payload = _payload(completed)

        assert completed.returncode == EXIT_LOCKED
        assert payload["status"] == "locked"
        assert payload["changed"] is False
        assert payload["error"] == {
            "code": "locked",
            "phase": "lock",
            "path": None,
        }
        assert not path.exists()
    finally:
        release.write_text("release\n", encoding="utf-8")
        holder.wait(timeout=15)
