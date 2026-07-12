# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Strict user configuration, migration and portability tests."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import setup_config
import user_config
from user_config import CortexConfigError, load_user_config, require_kb_path


def _write_config(path: Path, extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"schema_version = 1\n{extra}", encoding="utf-8")


def test_environment_overrides_file_and_file_overrides_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    _write_config(
        path,
        """
kb_path = "from-file"
included_sections = ["custom"]
excluded_dirs = ["archive"]
exclude_files = ["index.md"]
max_markdown_file_size_bytes = 123
max_pdf_size_bytes = 789
write_lock_path = "file.lock"
write_lock_timeout_seconds = 7
""",
    )

    config = load_user_config(
        path=path,
        script_dir=tmp_path,
        environ={
            "CORTEX_KB_PATH": "from-env",
            "CORTEX_MAX_MARKDOWN_FILE_SIZE_BYTES": "456",
            "CORTEX_WRITE_LOCK_PATH": "env.lock",
            "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS": "9.5",
        },
    )

    assert config.kb_path == "from-env"
    assert config.included_sections == frozenset({"custom"})
    assert config.excluded_dirs == frozenset({"archive"})
    assert config.exclude_files == frozenset({"index.md"})
    assert config.max_markdown_file_size_bytes == 456
    assert config.max_pdf_size_bytes == 789
    assert config.write_lock_path == "env.lock"
    assert config.write_lock_timeout_seconds == 9.5


def test_env_only_without_file_is_valid(tmp_path: Path) -> None:
    config = load_user_config(
        path=tmp_path / "missing.toml",
        script_dir=tmp_path,
        environ={"CORTEX_KB_PATH": "env-only"},
    )

    assert require_kb_path(config.kb_path) == "env-only"
    assert config.included_sections == user_config.DEFAULT_INCLUDED_SECTIONS


def test_appdata_selects_per_user_config_path(tmp_path: Path) -> None:
    assert user_config.user_config_path({"APPDATA": str(tmp_path)}) == (
        tmp_path / "Cortex" / "config.toml"
    )


def test_server_imports_without_kb_configuration(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    environ = dict(os.environ)
    environ.pop("CORTEX_KB_PATH", None)
    environ["APPDATA"] = str(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import config; assert config.KB_PATH is None; import server; print('OK')",
        ],
        cwd=root,
        env=environ,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    _write_config(path, "include_sections = []\n")

    with pytest.raises(CortexConfigError, match="Unknown configuration key"):
        load_user_config(path=path, environ={})


@pytest.mark.parametrize(
    "value",
    [
        'included_sections = "knowledge"',
        'max_pdf_size_bytes = "large"',
        "write_lock_timeout_seconds = false",
    ],
)
def test_invalid_types_are_rejected(tmp_path: Path, value: str) -> None:
    path = tmp_path / "config.toml"
    _write_config(path, value + "\n")

    with pytest.raises(CortexConfigError, match="Invalid type|must be"):
        load_user_config(path=path, environ={})


def test_missing_kb_path_has_actionable_typed_error(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.toml"
    config = load_user_config(path=config_path, environ={})

    with pytest.raises(CortexConfigError) as raised:
        require_kb_path(config.kb_path, config_path=config_path)

    message = str(raised.value)
    assert "setup_config.py --init" in message
    assert str(config_path) in message


def test_future_schema_is_rejected_actionably(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("schema_version = 2\n", encoding="utf-8")

    with pytest.raises(CortexConfigError, match="Upgrade Cortex"):
        load_user_config(path=path, environ={})


def test_init_is_atomic_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "Cortex" / "config.toml"
    real_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(user_config.os, "replace", recording_replace)

    assert setup_config.init_user_config(
        path=path,
        environ={"CORTEX_KB_PATH": "first-kb"},
    )
    first_content = path.read_bytes()
    assert replacements and replacements[0][0].parent == path.parent
    assert replacements[0][1] == path
    assert load_user_config(path=path, environ={}).kb_path == "first-kb"

    assert not setup_config.init_user_config(
        path=path,
        environ={"CORTEX_KB_PATH": "must-not-overwrite"},
    )
    assert path.read_bytes() == first_content
    assert len(replacements) == 1


def test_init_prompts_when_environment_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"

    assert setup_config.init_user_config(
        path=path,
        environ={},
        input_fn=lambda _prompt: "interactive-kb",
    )
    assert load_user_config(path=path, environ={}).kb_path == "interactive-kb"


def test_python_sources_contain_no_machine_specific_path_literals() -> None:
    root = Path(__file__).resolve().parents[1]
    drive_literal = re.compile(r"[A-Za-z]:" + re.escape(chr(92)))
    offenders = []
    for path in root.rglob("*.py"):
        if any(part in {".git", "chroma_db", "local"} for part in path.parts):
            continue
        if drive_literal.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(root).as_posix())

    assert offenders == []
