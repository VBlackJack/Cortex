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
"""User data home, safe migration, telemetry and file logging tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import data_home
import setup_config
from chroma_client import create_persistent_client
from cortex_logging import configure_logging
from data_home import (
    CortexDataHomeError,
    DataHomeConflictError,
    LegacyDataMigrationRequiredError,
    ensure_index_location,
    move_legacy_index,
)
from user_config import load_user_config


def _config(path: Path, chroma_path: Path, write_lock_path: Path | None = None) -> None:
    lines = [
        "schema_version = 1",
        f'chroma_path = "{chroma_path.as_posix()}"',
    ]
    if write_lock_path is not None:
        lines.append(f'write_lock_path = "{write_lock_path.as_posix()}"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_schema_v1_accepts_optional_path_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    chroma_path = tmp_path / "custom-index"
    lock_path = tmp_path / "custom.lock"
    _config(config_path, chroma_path, lock_path)

    config = load_user_config(
        path=config_path,
        environ={"LOCALAPPDATA": str(tmp_path / "local")},
        script_dir=tmp_path / "install",
    )

    assert config.schema_version == 1
    assert config.chroma_path == chroma_path.as_posix()
    assert config.write_lock_path == lock_path.as_posix()


def test_chroma_data_home_is_created_on_demand_with_telemetry_off(
    tmp_path: Path,
) -> None:
    chroma_path = tmp_path / "local" / "Cortex" / "chroma_db"
    assert not chroma_path.parent.exists()

    client = create_persistent_client(chroma_path)

    assert chroma_path.is_dir()
    assert client.get_settings().anonymized_telemetry is False


def test_setup_offers_and_atomically_moves_legacy_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_dir = tmp_path / "install"
    legacy = script_dir / "chroma_db"
    target = tmp_path / "local" / "Cortex" / "chroma_db"
    config_path = tmp_path / "roaming" / "Cortex" / "config.toml"
    legacy.mkdir(parents=True)
    (legacy / "chroma.sqlite3").write_bytes(b"index")
    _config(config_path, target)
    real_replace = os.replace
    replacements: list[tuple[Path, Path]] = []
    events: list[tuple[str, str]] = []

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(data_home.os, "replace", recording_replace)

    def output(message: str) -> None:
        events.append(("output", message))

    def answer(prompt: str) -> str:
        events.append(("prompt", prompt))
        return "y"

    moved = setup_config.offer_legacy_data_migration(
        config_path=config_path,
        script_dir=script_dir,
        environ={"LOCALAPPDATA": str(tmp_path / "local")},
        input_fn=answer,
        output_fn=output,
    )

    assert moved
    assert replacements == [(legacy, target)]
    assert not legacy.exists()
    assert (target / "chroma.sqlite3").read_bytes() == b"index"
    prompt_index = next(index for index, event in enumerate(events) if event[0] == "prompt")
    guidance = [message for _, message in events[prompt_index - 3 : prompt_index]]
    assert guidance[0].startswith("  Option:")
    assert guidance[1].startswith("  Default:")
    assert guidance[2].startswith("  Consequence:")


def test_migration_refuses_existing_target_without_changes(tmp_path: Path) -> None:
    legacy = tmp_path / "install" / "chroma_db"
    target = tmp_path / "local" / "Cortex" / "chroma_db"
    legacy.mkdir(parents=True)
    target.mkdir(parents=True)
    (legacy / "source").write_text("legacy", encoding="utf-8")
    (target / "source").write_text("target", encoding="utf-8")

    with pytest.raises(DataHomeConflictError, match="already exists"):
        move_legacy_index(legacy, target)

    assert (legacy / "source").read_text(encoding="utf-8") == "legacy"
    assert (target / "source").read_text(encoding="utf-8") == "target"


def test_atomic_move_failure_never_falls_back_to_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = tmp_path / "install" / "chroma_db"
    target = tmp_path / "local" / "Cortex" / "chroma_db"
    legacy.mkdir(parents=True)
    (legacy / "source").write_text("legacy", encoding="utf-8")

    def refuse_replace(_source: Path, _destination: Path) -> None:
        raise OSError("different volume")

    monkeypatch.setattr(data_home.os, "replace", refuse_replace)

    with pytest.raises(CortexDataHomeError, match="does not silently copy"):
        move_legacy_index(legacy, target)

    assert (legacy / "source").read_text(encoding="utf-8") == "legacy"
    assert not target.exists()


def test_runtime_refuses_required_migration_and_double_index(tmp_path: Path) -> None:
    legacy = tmp_path / "install" / "chroma_db"
    target = tmp_path / "local" / "Cortex" / "chroma_db"
    legacy.mkdir(parents=True)

    with pytest.raises(LegacyDataMigrationRequiredError, match="--migrate-data"):
        ensure_index_location(legacy, target)

    target.mkdir(parents=True)
    with pytest.raises(DataHomeConflictError, match="Both the legacy"):
        ensure_index_location(legacy, target)


def test_file_logging_rotates_and_keeps_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = configure_logging(
        log_dir=tmp_path / "logs",
        logger_name="cortex.rotation_test",
        max_bytes=180,
        backup_count=2,
    )
    try:
        for index in range(30):
            logger.info("sync_path=%s published_files=%d", f"section-{index}", index)
        for handler in logger.handlers:
            handler.flush()

        files = sorted((tmp_path / "logs").glob("cortex.log*"))
        backups = [path for path in files if path.name != "cortex.log"]
        assert (tmp_path / "logs" / "cortex.log").is_file()
        assert backups
        assert len(backups) <= 2
        assert "published_files=29" in capsys.readouterr().err
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_production_chroma_clients_use_the_central_factory() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if (
            "tests" in path.parts
            or "local" in path.parts
            or path.name == "chroma_client.py"
        ):
            continue
        if "PersistentClient(" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(root).as_posix())

    assert offenders == []


def test_setup_check_reports_data_migration_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script_dir = tmp_path / "install"
    legacy = script_dir / "chroma_db"
    target = tmp_path / "local" / "Cortex" / "chroma_db"
    config_path = tmp_path / "config.toml"
    legacy.mkdir(parents=True)
    _config(config_path, target)
    monkeypatch.setattr(setup_config, "SCRIPT_DIR", script_dir)
    monkeypatch.setattr(setup_config, "CORTEX_CONFIG_PATH", config_path)

    assert not setup_config.check_user_config()
    assert "--migrate-data" in capsys.readouterr().out
