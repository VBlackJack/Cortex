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
"""End-to-end tests for configuration failures at lazy CLI import boundaries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from confluence_writer.constants import EXIT_INVALID_INPUT, EXIT_OK

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_UTF8_BOM = b"\xef\xbb\xbf"
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
_JSON_COMMANDS = (
    pytest.param(("sync", "--json"), True, id="sync"),
    pytest.param(
        ("confluence", "resolve", "--json", "ZZ-000"),
        False,
        id="confluence-resolve",
    ),
    pytest.param(
        ("confluence", "pages", "--json"),
        False,
        id="confluence-pages",
    ),
)


def _run_cli(
    tmp_path: Path,
    arguments: tuple[str, ...],
    *,
    config_body: str | None,
    python_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the installed dispatcher against one isolated user configuration."""
    appdata = tmp_path / "appdata"
    config_path = appdata / "Cortex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    if config_body is not None:
        config_path.write_text(config_body, encoding="utf-8")
        assert not config_path.read_bytes().startswith(_UTF8_BOM)
    environment = {**os.environ, "APPDATA": str(appdata)}
    if python_path is not None:
        inherited_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (str(python_path), inherited_python_path)
            if part is not None
        )
    return subprocess.run(
        [sys.executable, "cli.py", *arguments],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(("arguments", "expects_sync_report"), _JSON_COMMANDS)
@pytest.mark.parametrize("config_body", _INVALID_CONFIGURATIONS)
def test_invalid_user_config_stops_at_json_import_boundary(
    arguments: tuple[str, ...],
    expects_sync_report: bool,
    config_body: str,
    tmp_path: Path,
) -> None:
    completed = _run_cli(tmp_path, arguments, config_body=config_body)

    assert completed.returncode == EXIT_INVALID_INPUT
    assert "Traceback" not in completed.stderr
    if expects_sync_report:
        payload = json.loads(completed.stdout)
        assert completed.stderr == ""
        assert payload["status"] == "failed"
        assert payload["recommendation"] == "none"
        assert payload["errors"] == [
            {"code": "invalid_configuration", "phase": "validate", "path": None}
        ]
        assert payload["scope"] == {
            "requested_section": None,
            "resolved_sections": [],
            "index_whole_folder": False,
            "included_ingestion_documents": False,
        }
    else:
        assert completed.stdout == ""
        assert "Cortex Confluence error:" in completed.stderr


def test_invalid_user_config_preserves_requested_sync_section(tmp_path: Path) -> None:
    completed = _run_cli(
        tmp_path,
        ("sync", "knowledge", "--json"),
        config_body="schema_version = 99\n",
    )

    assert completed.returncode == EXIT_INVALID_INPUT
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["scope"]["requested_section"] == "knowledge"


def test_invalid_user_config_keeps_human_sync_output_human(tmp_path: Path) -> None:
    completed = _run_cli(
        tmp_path,
        ("sync",),
        config_body="schema_version = 99\n",
    )

    assert completed.returncode == EXIT_INVALID_INPUT
    assert completed.stdout == ""
    assert completed.stderr.startswith("Cortex sync error:")
    assert "Traceback" not in completed.stderr


def test_invalid_sync_config_stops_before_ml_runtime_import(tmp_path: Path) -> None:
    guard_path = tmp_path / "module-guard"
    guard_path.mkdir()
    (guard_path / "fastembed.py").write_text(
        "raise RuntimeError('fastembed imported before config validation')\n",
        encoding="utf-8",
    )

    completed = _run_cli(
        tmp_path,
        ("sync", "--json"),
        config_body="schema_version = 99\n",
        python_path=guard_path,
    )

    assert completed.returncode == EXIT_INVALID_INPUT
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["errors"] == [
        {"code": "invalid_configuration", "phase": "validate", "path": None}
    ]


def test_absent_user_config_keeps_confluence_pages_json_valid(tmp_path: Path) -> None:
    completed = _run_cli(
        tmp_path,
        ("confluence", "pages", "--json"),
        config_body=None,
    )

    assert completed.returncode == EXIT_OK
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["contract_version"] == 1


def test_absent_confluence_config_classifies_resolve_as_invalid_input(
    tmp_path: Path,
) -> None:
    completed = _run_cli(
        tmp_path,
        ("confluence", "resolve", "123", "--json"),
        config_body=None,
    )

    assert completed.returncode == EXIT_INVALID_INPUT
    assert completed.stdout == ""
    assert "Confluence resolve requires: base_url, auth_expires_at" in completed.stderr
    assert "Traceback" not in completed.stderr
