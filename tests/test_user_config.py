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
chroma_path = "file-chroma"
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
    assert config.chroma_path == "file-chroma"
    assert config.included_sections == frozenset({"custom"})
    assert config.index_whole_folder is False
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
        environ={
            "CORTEX_KB_PATH": "env-only",
            "LOCALAPPDATA": str(tmp_path / "local"),
        },
    )

    assert require_kb_path(config.kb_path) == "env-only"
    assert config.chroma_path == str(tmp_path / "local" / "Cortex" / "chroma_db")
    assert config.write_lock_path == str(
        tmp_path / "local" / "Cortex" / "chroma_db.write.lock"
    )
    assert config.included_sections == user_config.DEFAULT_INCLUDED_SECTIONS
    assert config.index_whole_folder is False


def test_whole_folder_mode_parses_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    _write_config(
        path,
        'kb_path = "kb"\nindex_whole_folder = true\n',
    )

    config = load_user_config(path=path, environ={})

    assert config.index_whole_folder is True
    rendered = user_config.render_user_config(config)
    assert "index_whole_folder = true" in rendered


def test_onboarding_mode_only_applies_when_config_is_new(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    whole = load_user_config(
        path=missing,
        environ={"CORTEX_KB_PATH": "kb", "CORTEX_INDEX_MODE": "whole"},
    )
    assert whole.index_whole_folder is True
    assert whole.included_sections == user_config.GENERIC_INCLUDED_SECTIONS

    existing = tmp_path / "existing.toml"
    _write_config(existing, 'kb_path = "kb"\nincluded_sections = ["custom"]\n')
    preserved = load_user_config(
        path=existing,
        environ={"CORTEX_INDEX_MODE": "whole"},
    )
    assert preserved.index_whole_folder is False
    assert preserved.included_sections == frozenset({"custom"})


def test_appdata_selects_per_user_config_path(tmp_path: Path) -> None:
    assert user_config.user_config_path({"APPDATA": str(tmp_path)}) == (
        tmp_path / "Cortex" / "config.toml"
    )


def test_localappdata_selects_non_roaming_data_home(tmp_path: Path) -> None:
    assert user_config.local_data_home({"LOCALAPPDATA": str(tmp_path)}) == (
        tmp_path / "Cortex"
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
        "index_whole_folder = 1",
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


def test_init_sections_mode_creates_generic_or_custom_folders(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    kb = tmp_path / "kb"

    assert setup_config.init_user_config(
        path=path,
        environ={
            "CORTEX_KB_PATH": str(kb),
            "CORTEX_INDEX_MODE": "sections",
            "CORTEX_INDEX_SECTIONS": "reference,work,notes",
        },
    )

    config = load_user_config(path=path, environ={})
    assert config.index_whole_folder is False
    assert config.included_sections == frozenset({"reference", "work", "notes"})
    assert {item.name for item in kb.iterdir()} == {"reference", "work", "notes"}


def test_init_whole_mode_creates_no_section_folders(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    kb = tmp_path / "kb"
    kb.mkdir()

    assert setup_config.init_user_config(
        path=path,
        environ={
            "CORTEX_KB_PATH": str(kb),
            "CORTEX_INDEX_MODE": "whole",
        },
    )

    assert load_user_config(path=path, environ={}).index_whole_folder is True
    assert list(kb.iterdir()) == []


def test_reset_user_state_removes_only_config_and_generated_data(tmp_path: Path) -> None:
    roaming = tmp_path / "roaming" / "Cortex"
    data_home = tmp_path / "local" / "Cortex"
    kb = tmp_path / "documents"
    config_path = roaming / "config.toml"
    config_path.parent.mkdir(parents=True)
    data_home.mkdir(parents=True)
    kb.mkdir()
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    (data_home / "chroma.sqlite3").write_text("index", encoding="utf-8")
    document = kb / "keep.md"
    document.write_text("keep", encoding="utf-8")

    result = setup_config.reset_user_state(
        config_path=config_path,
        data_home=data_home,
    )

    assert result == setup_config.ResetResult(
        config_removed=True, data_home_removed=True
    )
    assert not config_path.exists()
    assert not data_home.exists()
    assert document.read_text(encoding="utf-8") == "keep"

    second = setup_config.reset_user_state(
        config_path=config_path,
        data_home=data_home,
    )
    assert second == setup_config.ResetResult(
        config_removed=False, data_home_removed=False
    )


def test_reset_user_state_rejects_unexpected_or_linked_targets(tmp_path: Path) -> None:
    with pytest.raises(CortexConfigError, match="unexpected config path"):
        setup_config.reset_user_state(
            config_path=tmp_path / "not-cortex.toml",
            data_home=tmp_path / "local" / "Cortex",
        )

    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "local" / "Cortex"
    linked.parent.mkdir()
    try:
        linked.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks require unavailable privileges")
    with pytest.raises(CortexConfigError, match="linked Cortex data home"):
        setup_config.reset_user_state(
            config_path=tmp_path / "roaming" / "Cortex" / "config.toml",
            data_home=linked,
        )
    assert target.exists()


def test_reset_failure_keeps_config_and_reports_active_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "roaming" / "Cortex" / "config.toml"
    data_home = tmp_path / "local" / "Cortex"
    config_path.parent.mkdir(parents=True)
    data_home.mkdir(parents=True)
    config_path.write_text("schema_version = 1\n", encoding="utf-8")

    def fail_remove(_path: Path) -> None:
        raise PermissionError(13, "in use", str(data_home / "chroma.sqlite3"))

    monkeypatch.setattr(setup_config.shutil, "rmtree", fail_remove)

    with pytest.raises(CortexConfigError, match="Close all AI clients"):
        setup_config.reset_user_state(
            config_path=config_path,
            data_home=data_home,
        )

    assert config_path.exists()


@pytest.mark.parametrize(
    "environ",
    [
        {"CORTEX_INDEX_MODE": "invalid"},
        {
            "CORTEX_INDEX_MODE": "sections",
            "CORTEX_INDEX_SECTIONS": "knowledge,../escape",
        },
    ],
)
def test_invalid_onboarding_mode_or_section_is_rejected(
    tmp_path: Path, environ: dict[str, str]
) -> None:
    path = tmp_path / "config.toml"
    values = {"CORTEX_KB_PATH": str(tmp_path / "kb"), **environ}

    with pytest.raises(CortexConfigError):
        setup_config.init_user_config(path=path, environ=values)

    assert not path.exists()


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
