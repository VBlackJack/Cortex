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
"""Raw-byte CAS, backup, validation, and idempotence tests for user config."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from user_config import load_user_config, render_user_config
from user_config_mutation import (
    UserConfigConflictError,
    user_config_backup_path,
    write_user_config_cas,
)


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "APPDATA": str(tmp_path / "appdata"),
        "LOCALAPPDATA": str(tmp_path / "localappdata"),
    }


def _rendered_config(path: Path, environment: dict[str, str], kb_path: str) -> bytes:
    defaults = load_user_config(path=path, environ=environment)
    return render_user_config(replace(defaults, kb_path=kb_path)).encode("utf-8")


def test_create_requires_absence_and_writes_no_backup(tmp_path: Path) -> None:
    path = tmp_path / "appdata" / "Cortex" / "config.toml"
    environment = _environment(tmp_path)

    result = write_user_config_cas(
        path,
        kb_path="G:/Knowledge",
        expected_hash=None,
        environ=environment,
    )

    assert result.changed is True
    assert result.backup_written is False
    assert result.rebuilt_from_defaults is False
    assert result.current.content == path.read_bytes()
    assert result.current.config is not None
    assert result.current.config.kb_path == "G:/Knowledge"
    assert not user_config_backup_path(path).exists()


def test_update_preserves_exact_previous_bytes_in_backup(tmp_path: Path) -> None:
    path = tmp_path / "appdata" / "Cortex" / "config.toml"
    environment = _environment(tmp_path)
    previous = _rendered_config(path, environment, "G:/Before").replace(b"\n", b"\r\n")
    path.parent.mkdir(parents=True)
    path.write_bytes(previous)
    expected_hash = hashlib.sha256(previous).hexdigest()

    result = write_user_config_cas(
        path,
        kb_path="G:/After",
        expected_hash=expected_hash,
        environ=environment,
    )

    assert result.changed is True
    assert result.backup_written is True
    assert result.previous.content == previous
    assert user_config_backup_path(path).read_bytes() == previous
    assert result.current.config is not None
    assert result.current.config.kb_path == "G:/After"


def test_stale_hash_preserves_external_bytes_and_existing_backup(tmp_path: Path) -> None:
    path = tmp_path / "appdata" / "Cortex" / "config.toml"
    environment = _environment(tmp_path)
    initial = _rendered_config(path, environment, "G:/Initial")
    external = _rendered_config(path, environment, "G:/External")
    backup = user_config_backup_path(path)
    path.parent.mkdir(parents=True)
    path.write_bytes(initial)
    backup.write_bytes(b"existing backup\n")
    path.write_bytes(external)

    with pytest.raises(UserConfigConflictError):
        write_user_config_cas(
            path,
            kb_path="G:/Caller",
            expected_hash=hashlib.sha256(initial).hexdigest(),
            environ=environment,
        )

    assert path.read_bytes() == external
    assert backup.read_bytes() == b"existing backup\n"


def test_invalid_config_rebuilds_defaults_and_backs_up_invalid_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "appdata" / "Cortex" / "config.toml"
    environment = _environment(tmp_path)
    invalid = b"schema_version = 1\nthis is not valid TOML [\n"
    path.parent.mkdir(parents=True)
    path.write_bytes(invalid)

    result = write_user_config_cas(
        path,
        kb_path="G:/Repaired",
        expected_hash=hashlib.sha256(invalid).hexdigest(),
        environ=environment,
    )

    assert result.changed is True
    assert result.rebuilt_from_defaults is True
    assert result.backup_written is True
    assert user_config_backup_path(path).read_bytes() == invalid
    assert result.current.config is not None
    assert result.current.config.kb_path == "G:/Repaired"


def test_identical_canonical_bytes_are_unchanged_without_backup(tmp_path: Path) -> None:
    path = tmp_path / "appdata" / "Cortex" / "config.toml"
    environment = _environment(tmp_path)
    content = _rendered_config(path, environment, "G:/Stable")
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    result = write_user_config_cas(
        path,
        kb_path="G:/Stable",
        expected_hash=hashlib.sha256(content).hexdigest(),
        environ=environment,
    )

    assert result.changed is False
    assert result.backup_written is False
    assert result.rebuilt_from_defaults is False
    assert path.read_bytes() == content
    assert not user_config_backup_path(path).exists()


@pytest.mark.parametrize("expected_hash", ["NOTAHASH", "A" * 64])
def test_malformed_hash_fails_before_filesystem_mutation(
    tmp_path: Path,
    expected_hash: str,
) -> None:
    path = tmp_path / "missing" / "config.toml"

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        write_user_config_cas(
            path,
            kb_path="G:/Knowledge",
            expected_hash=expected_hash,
            environ=_environment(tmp_path),
        )

    assert not path.parent.exists()
