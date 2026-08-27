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
"""CAS, canonical TOML, backup, and real mutation-lock tests."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import confluence_writer.config_mutation as mutation
from confluence_writer.config import (
    ConfluenceConfigError,
    ConfluenceSettings,
    PageSelection,
    SpaceMapping,
    parse_confluence_settings_bytes,
)
from confluence_writer.config_mutation import (
    ConfluenceConfigConflictError,
    ConfluenceConfigLockedError,
    confluence_config_backup_path,
    read_confluence_config_snapshot,
    render_confluence_settings,
    write_confluence_config_cas,
)

_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
_WORKER = Path(__file__).parent / "fixtures" / "confluence_config_mutation_worker.py"


def _v1_settings() -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=1,
        base_url="https://confluence.example.test",
        credential_target="Cortex Writer",
        auth_expires_at=_NOW,
        console_path=Path("C:/Tools/Confluence/console.exe"),
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="knowledge/doc",
                classification="perso-non-sensible",
            ),
        ),
    )


def _v2_settings(*, empty: bool = False, label: str = "doc") -> ConfluenceSettings:
    pages = () if empty else (PageSelection(page_id="1001"), PageSelection(page_id="1002"))
    return ConfluenceSettings(
        schema_version=2,
        base_url="https://confluence.example.test:8443",
        credential_target=f"Cortex {label}",
        auth_expires_at=_NOW,
        console_path=Path(f"C:/Tools/{label}/console.exe"),
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target=f"knowledge/{label}",
                classification="pro-confidentiel",
                selection="pages",
                pages=pages,
            ),
        ),
    )


def _v3_subtree_settings() -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=3,
        base_url="https://confluence.example.test:8443",
        credential_target="Cortex doc",
        auth_expires_at=_NOW,
        console_path=Path("C:/Tools/doc/console.exe"),
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="knowledge/doc",
                classification="pro-confidentiel",
                selection="subtree",
                pages=(PageSelection(page_id="1001"), PageSelection(page_id="1002")),
            ),
        ),
    )


def test_subtree_round_trip_keeps_every_root_and_the_schema_version(tmp_path: Path) -> None:
    settings = _v3_subtree_settings()
    path = tmp_path / "confluence.toml"

    first = render_confluence_settings(settings)
    reloaded = parse_confluence_settings_bytes(first, source=path)
    second = render_confluence_settings(reloaded)

    assert reloaded == settings
    assert second == first
    assert b"schema_version = 3" in first
    assert b'selection = "subtree"' in first
    assert first.count(b"[[spaces.pages]]") == 2


def _worker_settings(label: str) -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=2,
        base_url=f"https://{label}.example.test:8443",
        credential_target=f"Cortex {label}",
        auth_expires_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
        console_path=Path(f"C:/Tools/{label}/console.exe"),
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target=f"knowledge/{label}",
                classification="perso-non-sensible",
                selection="pages",
                pages=(),
            ),
        ),
    )


@pytest.mark.parametrize("settings", [_v1_settings(), _v2_settings()])
def test_snapshot_hash_and_model_come_from_exact_file_bytes(
    tmp_path: Path,
    settings: ConfluenceSettings,
) -> None:
    path = tmp_path / "confluence.toml"
    content = render_confluence_settings(settings).replace(b"\n", b"\r\n")
    path.write_bytes(content)

    snapshot = read_confluence_config_snapshot(path)

    assert snapshot.content == content
    assert snapshot.content_hash == hashlib.sha256(content).hexdigest()
    assert snapshot.settings == settings


@pytest.mark.parametrize("settings", [_v1_settings(), _v2_settings(empty=True)])
def test_canonical_round_trip_is_deterministic_lf_and_schema_complete(
    tmp_path: Path,
    settings: ConfluenceSettings,
) -> None:
    path = tmp_path / "confluence.toml"

    first = render_confluence_settings(settings)
    reloaded = parse_confluence_settings_bytes(first, source=path)
    second = render_confluence_settings(reloaded)

    assert reloaded == settings
    assert second == first
    assert b"\r" not in first
    if settings.schema_version == 1:
        assert b"selection" not in first
        assert b"pages" not in first
    else:
        assert b'selection = "pages"' in first
        assert b"pages = []" in first


def test_toml_escaping_round_trip_preserves_windows_path_apostrophe_and_port(
    tmp_path: Path,
) -> None:
    windows_console_path = Path(
        "C:" + chr(92) + chr(92).join(("Users", "me", "console", "builder.exe"))
    )
    settings = ConfluenceSettings(
        schema_version=2,
        base_url="https://confluence.example.test:8443",
        credential_target="Julien's Cortex writer",
        auth_expires_at=_NOW,
        console_path=windows_console_path,
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="knowledge/doc",
                classification="perso-non-sensible",
                selection="whole_space",
            ),
        ),
    )

    rendered = render_confluence_settings(settings)
    reloaded = parse_confluence_settings_bytes(rendered, source=tmp_path / "confluence.toml")

    assert reloaded == settings
    assert reloaded.console_path == windows_console_path
    assert reloaded.credential_target == "Julien's Cortex writer"
    assert reloaded.base_url == "https://confluence.example.test:8443"


def test_create_requires_absence_and_writes_no_backup(tmp_path: Path) -> None:
    path = tmp_path / "confluence.toml"
    settings = _v2_settings(empty=True)

    result = write_confluence_config_cas(path, settings, expected_hash=None)

    assert result.content == path.read_bytes()
    assert result.settings == settings
    assert not confluence_config_backup_path(path).exists()


def test_update_with_matching_hash_preserves_exact_previous_bytes_in_backup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "confluence.toml"
    previous = b"# operator comment\r\n" + render_confluence_settings(_v1_settings()).replace(
        b"\n", b"\r\n"
    )
    path.write_bytes(previous)
    snapshot = read_confluence_config_snapshot(path)
    replacement = _v2_settings()

    result = write_confluence_config_cas(
        path,
        replacement,
        expected_hash=snapshot.content_hash,
    )

    assert result.settings == replacement
    assert path.read_bytes() == result.content
    assert confluence_config_backup_path(path).read_bytes() == previous


def test_stale_hash_preserves_external_update_and_existing_backup(tmp_path: Path) -> None:
    path = tmp_path / "confluence.toml"
    backup = confluence_config_backup_path(path)
    path.write_bytes(render_confluence_settings(_v1_settings()))
    backup.write_bytes(b"existing backup\n")
    snapshot = read_confluence_config_snapshot(path)
    external = render_confluence_settings(_v2_settings(label="external"))
    path.write_bytes(external)

    with pytest.raises(ConfluenceConfigConflictError, match="changed"):
        write_confluence_config_cas(
            path,
            _v2_settings(label="caller"),
            expected_hash=snapshot.content_hash,
        )

    assert path.read_bytes() == external
    assert backup.read_bytes() == b"existing backup\n"


def test_file_appearance_after_absent_snapshot_is_a_conflict(tmp_path: Path) -> None:
    path = tmp_path / "confluence.toml"
    external = render_confluence_settings(_v1_settings())
    path.write_bytes(external)

    with pytest.raises(ConfluenceConfigConflictError, match="appeared"):
        write_confluence_config_cas(path, _v2_settings(), expected_hash=None)

    assert path.read_bytes() == external


def test_file_disappearance_after_snapshot_is_a_conflict(tmp_path: Path) -> None:
    path = tmp_path / "confluence.toml"
    path.write_bytes(render_confluence_settings(_v1_settings()))
    snapshot = read_confluence_config_snapshot(path)
    path.unlink()

    with pytest.raises(ConfluenceConfigConflictError, match="disappeared"):
        write_confluence_config_cas(
            path,
            _v2_settings(),
            expected_hash=snapshot.content_hash,
        )

    assert not path.exists()


@pytest.mark.parametrize("expected_hash", ["not-a-hash", "A" * 64])
def test_malformed_expected_hash_fails_before_filesystem_mutation(
    tmp_path: Path,
    expected_hash: str,
) -> None:
    path = tmp_path / "missing" / "confluence.toml"

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        write_confluence_config_cas(
            path,
            _v2_settings(),
            expected_hash=expected_hash,
        )

    assert not path.parent.exists()


def test_invalid_temporary_never_replaces_target_or_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "confluence.toml"
    backup = confluence_config_backup_path(path)
    previous = render_confluence_settings(_v1_settings())
    path.write_bytes(previous)
    backup.write_bytes(b"previous backup\n")
    snapshot = read_confluence_config_snapshot(path)
    monkeypatch.setattr(mutation, "render_confluence_settings", lambda _settings: b"broken = [")

    with pytest.raises(ConfluenceConfigError):
        write_confluence_config_cas(
            path,
            _v2_settings(),
            expected_hash=snapshot.content_hash,
        )

    assert path.read_bytes() == previous
    assert backup.read_bytes() == b"previous backup\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_target_replace_failure_preserves_readable_previous_file_and_cleans_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "confluence.toml"
    previous = render_confluence_settings(_v1_settings())
    path.write_bytes(previous)
    snapshot = read_confluence_config_snapshot(path)
    real_replace = os.replace

    def fail_target_replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == path:
            raise OSError("injected target replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(mutation.os, "replace", fail_target_replace)

    with pytest.raises(OSError, match="injected target replace failure"):
        write_confluence_config_cas(
            path,
            _v2_settings(),
            expected_hash=snapshot.content_hash,
        )

    assert path.read_bytes() == previous
    assert confluence_config_backup_path(path).read_bytes() == previous
    assert list(tmp_path.glob("*.tmp")) == []


def _wait_for_files(paths: tuple[Path, ...], processes: tuple[subprocess.Popen[str], ...]) -> None:
    deadline = time.monotonic() + 15.0
    while not all(path.exists() for path in paths) and time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            break
        time.sleep(0.02)
    assert all(path.exists() for path in paths)


def test_real_process_contention_fails_locked_without_touching_target(tmp_path: Path) -> None:
    path = tmp_path / "confluence.toml"
    ready = tmp_path / "holder.ready"
    release = tmp_path / "holder.release"
    holder = subprocess.Popen(
        [sys.executable, str(_WORKER), "hold", str(path), str(ready), str(release)],
        cwd=Path(__file__).parents[1],
        text=True,
    )
    try:
        _wait_for_files((ready,), (holder,))
        contender = subprocess.run(
            [
                sys.executable,
                str(_WORKER),
                "mutate",
                str(path),
                "contender",
                "absent",
                "0",
            ],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        assert contender.stdout.strip() == "LOCKED:contender"
        assert not path.exists()
        assert not confluence_config_backup_path(path).exists()
    finally:
        release.write_text("release\n", encoding="utf-8")
        holder.wait(timeout=15)


def test_hard_kill_releases_real_process_lock(tmp_path: Path) -> None:
    path = tmp_path / "confluence.toml"
    ready = tmp_path / "holder.ready"
    never_release = tmp_path / "never.release"
    holder = subprocess.Popen(
        [sys.executable, str(_WORKER), "hold", str(path), str(ready), str(never_release)],
        cwd=Path(__file__).parents[1],
        text=True,
    )
    _wait_for_files((ready,), (holder,))
    holder.kill()
    holder.wait(timeout=15)

    result = write_confluence_config_cas(
        path,
        _v2_settings(),
        expected_hash=None,
        timeout_seconds=1.0,
    )

    assert result.settings == _v2_settings()


def test_two_real_mutators_from_same_hash_allow_one_commit_and_one_conflict(
    tmp_path: Path,
) -> None:
    path = tmp_path / "confluence.toml"
    initial = render_confluence_settings(_v1_settings())
    path.write_bytes(initial)
    expected_hash = hashlib.sha256(initial).hexdigest()
    go = tmp_path / "go"
    ready_a = tmp_path / "a.ready"
    ready_b = tmp_path / "b.ready"

    def launch(label: str, ready: Path) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [
                sys.executable,
                str(_WORKER),
                "race",
                str(path),
                label,
                expected_hash,
                "5",
                str(ready),
                str(go),
            ],
            cwd=Path(__file__).parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    process_a = launch("a", ready_a)
    process_b = launch("b", ready_b)
    _wait_for_files((ready_a, ready_b), (process_a, process_b))
    go.write_text("go\n", encoding="utf-8")
    stdout_a, stderr_a = process_a.communicate(timeout=20)
    stdout_b, stderr_b = process_b.communicate(timeout=20)

    assert process_a.returncode == 0, stderr_a
    assert process_b.returncode == 0, stderr_b
    assert {stdout_a.strip().split(":")[0], stdout_b.strip().split(":")[0]} == {
        "OK",
        "CONFLICT",
    }
    final = read_confluence_config_snapshot(path)
    assert final.settings in (_worker_settings("a"), _worker_settings("b"))
    assert confluence_config_backup_path(path).read_bytes() == initial


def test_locked_error_type_is_public_contract() -> None:
    assert issubclass(ConfluenceConfigLockedError, mutation.ConfluenceConfigMutationError)
