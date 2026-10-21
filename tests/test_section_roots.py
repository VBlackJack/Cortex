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
"""Per-section roots: configuration, resolution, sync, freshness, doctor and CLI."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import chunker
import chunker_pdf
import chunker_utils
import doctor
import freshness
import indexer
import sync_hash_aware
from config_contract import ConfigRootMutationReport, ConfigRootsReport
from confluence_writer.constants import (
    EXIT_CONFLICT,
    EXIT_ERROR,
    EXIT_INVALID_INPUT,
    EXIT_OK,
)
from search_command import present_hit, safe_document_path
from section_roots import (
    locate_section,
    logical_source_path,
    resolve_logical_path,
    section_root,
)
from sync_hash_aware import _sync_section_locked
from tests.test_sync_hash_aware import Collection
from user_config import (
    CortexConfigError,
    CortexUserConfig,
    load_user_config,
    render_user_config,
)
from user_config_mutation import (
    UserConfigConflictError,
    UserConfigInvalidBaseError,
    read_user_config_snapshot,
    user_config_backup_path,
    write_section_root_cas,
    write_user_config_cas,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SECTION = "_memory"
_OTHER = "knowledge"
_NOTE_BODY = "# Title\n\nThis body is comfortably longer than the minimum chunk size.\n"


def _base_config(tmp_path: Path, **changes: object) -> CortexUserConfig:
    defaults = load_user_config(path=tmp_path / "absent.toml", environ={})
    config = replace(
        defaults,
        kb_path=str(tmp_path / "kb"),
        included_sections=frozenset({_SECTION, _OTHER}),
        write_lock_path=str(tmp_path / "lock"),
        chroma_path=str(tmp_path / "chroma_db"),
    )
    return replace(config, **changes)


def _write(path: Path, config: CortexUserConfig) -> bytes:
    content = render_user_config(config).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


# -- Configuration ------------------------------------------------------------


def test_section_roots_round_trip_through_render_and_load(tmp_path: Path) -> None:
    mount = tmp_path / "moved" / _SECTION
    config = _base_config(tmp_path, section_roots={_SECTION: str(mount)})
    path = tmp_path / "config.toml"
    _write(path, config)

    loaded = load_user_config(path=path, environ={})

    assert loaded == config
    assert loaded.section_roots == {_SECTION: os.path.normpath(str(mount))}
    assert "[section_roots]" in path.read_text(encoding="utf-8")


def test_config_without_mounts_renders_no_table(tmp_path: Path) -> None:
    rendered = render_user_config(_base_config(tmp_path))
    assert "section_roots" not in rendered


def test_section_root_value_is_normalized(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    _write(path, _base_config(tmp_path))
    raw = (tmp_path / "moved" / "extra" / ".." / _SECTION).as_posix() + "/"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[section_roots]\n{_SECTION} = {json.dumps(raw)}\n")

    loaded = load_user_config(path=path, environ={})

    assert loaded.section_roots[_SECTION] == os.path.normpath(
        str(tmp_path / "moved" / _SECTION)
    )


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('unknown = "{mount}"', "not in included_sections"),
        (f'{_SECTION} = "relative/folder"', "absolute directory"),
        (f'{_SECTION} = ""', "absolute directory"),
        (f"{_SECTION} = 42", "must be a string"),
    ],
    ids=["unknown-section", "relative-path", "empty-path", "not-a-string"],
)
def test_invalid_section_root_entries_are_rejected(
    tmp_path: Path, table: str, message: str
) -> None:
    path = tmp_path / "config.toml"
    _write(path, _base_config(tmp_path))
    mount = json.dumps(str(tmp_path / "moved"))[1:-1]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n[section_roots]\n" + table.replace("{mount}", mount) + "\n")

    with pytest.raises(CortexConfigError, match=message):
        load_user_config(path=path, environ={})


def test_section_roots_must_be_a_table(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    content = render_user_config(_base_config(tmp_path))
    path.write_text(content + 'section_roots = "nope"\n', encoding="utf-8")

    with pytest.raises(CortexConfigError, match="section_roots"):
        load_user_config(path=path, environ={})


def test_section_roots_are_refused_in_whole_folder_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    _write(path, _base_config(tmp_path, index_whole_folder=True))
    mount = json.dumps(str(tmp_path / "moved"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[section_roots]\n{_SECTION} = {mount}\n")

    with pytest.raises(CortexConfigError, match="index_whole_folder = false"):
        load_user_config(path=path, environ={})


# -- Compare-and-swap mutation --------------------------------------------------


def test_set_and_clear_root_use_compare_and_swap_and_keep_a_backup(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = _write(path, _base_config(tmp_path))
    mount = tmp_path / "moved" / _SECTION

    mounted = write_section_root_cas(
        path,
        section=_SECTION,
        root=str(mount),
        expected_hash=hashlib.sha256(original).hexdigest(),
        environ={},
    )

    assert mounted.changed is True
    assert mounted.current.config is not None
    assert mounted.current.config.section_roots == {_SECTION: str(mount)}
    assert user_config_backup_path(path).read_bytes() == original

    cleared = write_section_root_cas(
        path,
        section=_SECTION,
        root=None,
        expected_hash=str(mounted.current.content_hash),
        environ={},
    )

    assert cleared.changed is True
    assert path.read_bytes() == original


def test_set_root_refuses_a_stale_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    _write(path, _base_config(tmp_path))

    with pytest.raises(UserConfigConflictError):
        write_section_root_cas(
            path,
            section=_SECTION,
            root=str(tmp_path / "moved"),
            expected_hash="0" * 64,
            environ={},
        )


@pytest.mark.parametrize(
    ("section", "root_name", "whole"),
    [("unknown", "moved", False), (_SECTION, None, False), (_SECTION, "moved", True)],
    ids=["unknown-section", "relative-path", "whole-folder"],
)
def test_set_root_rule_violations_raise_value_error_before_writing(
    tmp_path: Path, section: str, root_name: str | None, whole: bool
) -> None:
    path = tmp_path / "config.toml"
    original = _write(path, _base_config(tmp_path, index_whole_folder=whole))
    root = str(tmp_path / root_name) if root_name else "relative/folder"

    with pytest.raises(ValueError):
        write_section_root_cas(
            path,
            section=section,
            root=root,
            expected_hash=hashlib.sha256(original).hexdigest(),
            environ={},
        )

    assert path.read_bytes() == original


def test_set_root_refuses_an_invalid_configuration(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("schema_version = 1\nkb_path = 42\n", encoding="utf-8")
    original = path.read_bytes()

    with pytest.raises(UserConfigInvalidBaseError):
        write_section_root_cas(
            path,
            section=_SECTION,
            root=str(tmp_path / "moved"),
            expected_hash=hashlib.sha256(original).hexdigest(),
            environ={},
        )

    assert path.read_bytes() == original


def test_changing_kb_path_keeps_the_mounts(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mounts = {_SECTION: str(tmp_path / "moved")}
    content = _write(path, _base_config(tmp_path, section_roots=mounts))

    result = write_user_config_cas(
        path,
        kb_path=str(tmp_path / "other-kb"),
        expected_hash=hashlib.sha256(content).hexdigest(),
        environ={},
    )

    assert result.current.config is not None
    assert result.current.config.section_roots == mounts


# -- Resolution -----------------------------------------------------------------


def test_resolution_maps_both_directions_through_the_mount(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    mount = tmp_path / "elsewhere" / "memory"
    mounts = {_SECTION: str(mount)}

    assert section_root(kb, _SECTION, mounts) == mount
    assert section_root(kb, _OTHER, mounts) == kb / _OTHER
    location = locate_section(kb, _SECTION, mounts)
    assert location.mounted is True
    assert location.logical_path(mount / "sub" / "a.md") == f"{_SECTION}/sub/a.md"
    assert locate_section(kb, _OTHER, mounts).logical_path(kb / _OTHER / "b.md") == (
        f"{_OTHER}/b.md"
    )
    assert logical_source_path(mount / "sub" / "a.md", kb, mounts) == f"{_SECTION}/sub/a.md"
    assert logical_source_path(kb / _OTHER / "b.md", kb, mounts) == f"{_OTHER}/b.md"
    assert logical_source_path(tmp_path / "stray.md", kb, mounts) is None
    assert resolve_logical_path(kb, f"{_SECTION}/sub/a.md", mounts) == (
        mount / "sub" / "a.md",
        mount,
    )
    assert resolve_logical_path(kb, f"{_OTHER}/b.md", mounts) == (kb / f"{_OTHER}/b.md", kb)


def test_a_mount_inside_the_knowledge_base_still_gets_its_section_prefix(
    tmp_path: Path,
) -> None:
    kb = tmp_path / "kb"
    mount = kb / "archive-2026" / _SECTION
    assert logical_source_path(mount / "a.md", kb, {_SECTION: str(mount)}) == f"{_SECTION}/a.md"


def test_discover_sections_resolves_mounts_and_names_the_missing_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    kb = tmp_path / "kb"
    (kb / _OTHER).mkdir(parents=True)
    mount = tmp_path / "elsewhere" / _SECTION
    mount.mkdir(parents=True)
    missing_mount = tmp_path / "gone" / "drafts"
    monkeypatch.setattr(indexer, "KB_PATH", str(kb))
    monkeypatch.setattr(indexer, "INDEX_WHOLE_FOLDER", False)
    monkeypatch.setattr(indexer, "INCLUDED_SECTIONS", frozenset({_SECTION, _OTHER, "_drafts"}))
    monkeypatch.setattr(
        indexer, "SECTION_ROOTS", {_SECTION: str(mount), "_drafts": str(missing_mount)}
    )

    with caplog.at_level(logging.WARNING, logger="cortex"):
        sections = indexer.discover_sections()

    assert sections == [_SECTION, _OTHER]
    assert any(str(missing_mount) in record.getMessage() for record in caplog.records)


# -- Sync -----------------------------------------------------------------------


def _use_real_chunkers(
    monkeypatch: pytest.MonkeyPatch, kb: Path, mounts: dict[str, str]
) -> None:
    monkeypatch.setattr(chunker, "KB_PATH", str(kb))
    monkeypatch.setattr(chunker_pdf, "KB_PATH", str(kb))
    monkeypatch.setattr(chunker_utils, "SECTION_ROOTS", mounts)


def _write_notes(section_dir: Path) -> None:
    (section_dir / "nested").mkdir(parents=True)
    (section_dir / "first.md").write_text(_NOTE_BODY, encoding="utf-8")
    (section_dir / "nested" / "second.md").write_text(_NOTE_BODY + "More.\n", encoding="utf-8")


def test_sync_on_a_mounted_section_publishes_logical_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    mount = tmp_path / "elsewhere" / "memory-store"
    _write_notes(mount)
    mounts = {_SECTION: str(mount)}
    _use_real_chunkers(monkeypatch, kb, mounts)
    collection = Collection()

    stats = _sync_section_locked(collection, kb, _SECTION, section_roots=mounts)

    assert stats["published_files"] == 2
    assert stats["errors"] == 0
    paths = {row["metadata"]["path"] for row in collection.rows.values()}
    assert paths == {f"{_SECTION}/first.md", f"{_SECTION}/nested/second.md"}
    assert all(chunk_id.startswith(f"{_SECTION}/") for chunk_id in collection.rows)
    assert {row["metadata"]["section"] for row in collection.rows.values()} == {_SECTION}


def test_moving_a_section_and_mounting_it_keeps_every_chunk_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "kb"
    _write_notes(kb / _SECTION)
    _use_real_chunkers(monkeypatch, kb, {})
    collection = Collection()

    first = _sync_section_locked(collection, kb, _SECTION, section_roots={})
    ids_before = set(collection.rows)
    upserts_before = collection.upsert_calls
    assert first["published_files"] == 2

    moved = tmp_path / "new-drive" / "renamed-memory"
    moved.parent.mkdir()
    shutil.move(str(kb / _SECTION), str(moved))

    unmounted = _sync_section_locked(collection, kb, _SECTION, section_roots={})
    assert unmounted["errors"] == 1
    assert set(collection.rows) == ids_before

    mounts = {_SECTION: str(moved)}
    _use_real_chunkers(monkeypatch, kb, mounts)
    second = _sync_section_locked(collection, kb, _SECTION, section_roots=mounts)

    assert set(collection.rows) == ids_before
    assert collection.upsert_calls == upserts_before
    assert second == {
        "published_files": 0,
        "added_chunks": 0,
        "deleted_chunks": 0,
        "removed_files": 0,
        "skipped_files": 2,
        "empty_files": 0,
        "errors": 0,
    }


def test_exclusions_apply_to_logical_paths_inside_a_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    mount = tmp_path / "elsewhere"
    _write_notes(mount)
    (mount / "_archive").mkdir()
    (mount / "_archive" / "old.md").write_text(_NOTE_BODY, encoding="utf-8")
    mounts = {_SECTION: str(mount)}
    _use_real_chunkers(monkeypatch, kb, mounts)
    collection = Collection()

    _sync_section_locked(collection, kb, _SECTION, section_roots=mounts)

    paths = {row["metadata"]["path"] for row in collection.rows.values()}
    assert f"{_SECTION}/_archive/old.md" not in paths


def test_unavailable_mount_error_carries_the_resolved_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    mount = tmp_path / "unplugged" / _SECTION
    monkeypatch.setattr(indexer, "KB_PATH", str(kb))
    monkeypatch.setattr(indexer, "CHROMA_PATH", str(tmp_path / "chroma_db"))
    monkeypatch.setattr(indexer, "LEGACY_CHROMA_PATH", str(tmp_path / "chroma_db"))
    monkeypatch.setattr(indexer, "INDEX_WHOLE_FOLDER", False)
    monkeypatch.setattr(indexer, "INCLUDED_SECTIONS", frozenset({_SECTION}))
    monkeypatch.setattr(sync_hash_aware, "SECTION_ROOTS", {_SECTION: str(mount)})
    collection = Collection()
    monkeypatch.setattr(indexer, "get_client", object)
    monkeypatch.setattr(indexer, "get_collection", lambda _client=None: collection)
    monkeypatch.setattr(indexer, "prepare_lexical_index", lambda *_a, **_k: None)

    report = indexer._sync_locked_report(_SECTION, verbose=False)

    assert [(error.code, error.path) for error in report.errors] == [
        ("section_unavailable", str(mount))
    ]


# -- Freshness, search and doctor ----------------------------------------------


def test_freshness_reads_a_mounted_section_under_its_logical_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    mount = tmp_path / "elsewhere"
    _write_notes(mount)
    (mount / "_archive").mkdir()
    (mount / "_archive" / "old.md").write_text(_NOTE_BODY, encoding="utf-8")
    mounts = {_SECTION: str(mount)}
    _use_real_chunkers(monkeypatch, kb, mounts)
    collection = Collection()
    _sync_section_locked(collection, kb, _SECTION, section_roots=mounts)
    scope = freshness.FreshnessScope(
        kb_path=str(kb),
        included_sections=frozenset({_SECTION}),
        excluded_dirs=frozenset({"_archive"}),
        exclude_files=frozenset(),
        section_roots=mounts,
    )

    report = freshness.cortex_freshness_report(collection, scope=scope, emit_log=False)

    assert report["summary"] == {"excluded": 1, "fresh": 2}
    assert {entry["path"] for entry in report["entries"]} == {
        f"{_SECTION}/_archive/old.md",
        f"{_SECTION}/first.md",
        f"{_SECTION}/nested/second.md",
    }


def test_search_annotation_and_open_target_follow_the_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    mount = tmp_path / "elsewhere"
    _write_notes(mount)
    mounts = {_SECTION: str(mount)}
    _use_real_chunkers(monkeypatch, kb, mounts)
    collection = Collection()
    _sync_section_locked(collection, kb, _SECTION, section_roots=mounts)
    row = next(iter(collection.rows.values()))
    monkeypatch.setattr(freshness, "KB_PATH", str(kb))
    monkeypatch.setattr(freshness, "SECTION_ROOTS", mounts)

    hits = freshness.annotate_search_hits([{"metadata": dict(row["metadata"])}])
    presented = present_hit({"id": "x", "metadata": row["metadata"]}, kb, mounts)

    assert hits[0]["freshness"] == "fresh"
    relative = row["metadata"]["path"].split("/", 1)[1]
    assert presented["open_target"] == str((mount / relative).resolve())
    assert safe_document_path(kb, f"{_SECTION}/../../outside.md", mounts) is None


def _doctor_context(tmp_path: Path, config_path: Path) -> doctor.DoctorContext:
    return doctor.DoctorContext(
        script_dir=tmp_path,
        config_path=config_path,
        environ={},
        home=tmp_path,
        python_exe=sys.executable,
        python_version=(3, 11, 0),
    )


def test_doctor_checks_each_mount_and_freshness_uses_it(tmp_path: Path) -> None:
    (tmp_path / "kb").mkdir()
    present = tmp_path / "elsewhere"
    present.mkdir()
    absent = tmp_path / "unplugged"
    config = _base_config(
        tmp_path, section_roots={_SECTION: str(present), _OTHER: str(absent)}
    )
    path = tmp_path / "config.toml"
    _write(path, config)

    checks, loaded, _accessible = doctor._configuration_checks(_doctor_context(tmp_path, path))
    by_id = {check.id: check for check in checks}

    ok = by_id[f"{doctor.SECTION_ROOTS_CHECK_ID}.{_SECTION}"]
    failed = by_id[f"{doctor.SECTION_ROOTS_CHECK_ID}.{_OTHER}"]
    assert ok.status == "OK"
    assert failed.status == "FAIL"
    assert str(absent) in failed.message
    assert failed.details["path"] == str(absent)
    assert loaded is not None
    freshness_check = doctor._freshness_check(loaded, [])
    assert freshness_check.id == "freshness.summary"


def test_doctor_adds_no_mount_check_without_mounts(tmp_path: Path) -> None:
    (tmp_path / "kb").mkdir()
    path = tmp_path / "config.toml"
    _write(path, _base_config(tmp_path))

    checks, _config, _accessible = doctor._configuration_checks(_doctor_context(tmp_path, path))

    assert not any(check.id.startswith(doctor.SECTION_ROOTS_CHECK_ID) for check in checks)


# -- Command-line contract --------------------------------------------------------


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("CORTEX_")
    }
    environment["APPDATA"] = str(tmp_path / "appdata")
    environment["LOCALAPPDATA"] = str(tmp_path / "localappdata")
    return environment


def _config_path(environment: dict[str, str]) -> Path:
    return Path(environment["APPDATA"]) / "Cortex" / "config.toml"


def _run_cli(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "cli.py", "config", *arguments],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _payload(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.stderr == ""
    payload: dict[str, object] = json.loads(completed.stdout)
    return payload


def test_roots_lists_each_section_with_its_resolved_root(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    (tmp_path / "kb" / _OTHER).mkdir(parents=True)
    mount = tmp_path / "elsewhere"
    mount.mkdir()
    content = _write(
        _config_path(environment), _base_config(tmp_path, section_roots={_SECTION: str(mount)})
    )

    completed = _run_cli(environment, "roots", "--json")
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    ConfigRootsReport.model_validate(payload)
    assert payload["contract_version"] == 1
    assert payload["operation"] == "config_roots"
    assert payload["content_hash"] == hashlib.sha256(content).hexdigest()
    assert payload["sections"] == [
        {"section": _SECTION, "root": str(mount), "mounted": True, "exists": True},
        {
            "section": _OTHER,
            "root": str(tmp_path / "kb" / _OTHER),
            "mounted": False,
            "exists": True,
        },
    ]


def test_roots_on_an_invalid_configuration_reports_it_without_failing(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    path.parent.mkdir(parents=True)
    path.write_text("schema_version = 1\nkb_path = 42\n", encoding="utf-8")

    completed = _run_cli(environment, "roots", "--json")
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    assert payload["valid"] is False
    assert payload["sections"] == []
    assert payload["error"] == {
        "code": "invalid_configuration",
        "phase": "validate",
        "path": None,
    }


def test_set_root_then_clear_root_through_the_command_line(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    original = _write(path, _base_config(tmp_path))
    mount = tmp_path / "elsewhere"

    completed = _run_cli(
        environment,
        "set-root",
        _SECTION,
        str(mount),
        "--json",
        "--expected-hash",
        hashlib.sha256(original).hexdigest(),
    )
    payload = _payload(completed)

    assert completed.returncode == EXIT_OK
    ConfigRootMutationReport.model_validate(payload)
    assert payload["operation"] == "config_set_root"
    assert payload["status"] == "succeeded"
    assert payload["root"] == str(mount)
    assert payload["restart_required"] is True
    assert payload["content_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()

    get_payload = _payload(_run_cli(environment, "get", "--json"))
    assert isinstance(get_payload["values"], dict)
    assert len(get_payload["values"]) == 11

    cleared = _run_cli(
        environment,
        "clear-root",
        _SECTION,
        "--json",
        "--expected-hash",
        str(payload["content_hash"]),
    )
    cleared_payload = _payload(cleared)
    assert cleared.returncode == EXIT_OK
    assert cleared_payload["operation"] == "config_clear_root"
    assert cleared_payload["status"] == "succeeded"
    assert cleared_payload["root"] is None
    assert path.read_bytes() == original

    again = _payload(
        _run_cli(
            environment,
            "clear-root",
            _SECTION,
            "--json",
            "--expected-hash",
            hashlib.sha256(original).hexdigest(),
        )
    )
    assert again["status"] == "unchanged"
    assert again["changed"] is False


@pytest.mark.parametrize(
    ("arguments", "config_body", "exit_code", "status", "code"),
    [
        (("unknown", "{mount}"), None, EXIT_INVALID_INPUT, "failed", "invalid_argument"),
        ((_SECTION, "relative/folder"), None, EXIT_INVALID_INPUT, "failed", "invalid_argument"),
        ((_SECTION, "{mount}"), None, EXIT_CONFLICT, "conflict", "hash_mismatch"),
        (
            (_SECTION, "{mount}"),
            "schema_version = 1\nkb_path = 42\n",
            EXIT_ERROR,
            "failed",
            "invalid_configuration",
        ),
    ],
    ids=["unknown-section", "relative-path", "stale-hash", "invalid-config"],
)
def test_set_root_failures_use_the_config_set_error_classes(
    tmp_path: Path,
    arguments: tuple[str, str],
    config_body: str | None,
    exit_code: int,
    status: str,
    code: str,
) -> None:
    environment = _environment(tmp_path)
    path = _config_path(environment)
    if config_body is None:
        original = _write(path, _base_config(tmp_path))
    else:
        path.parent.mkdir(parents=True)
        path.write_text(config_body, encoding="utf-8")
        original = path.read_bytes()
    expected_hash = "0" * 64 if code == "hash_mismatch" else hashlib.sha256(original).hexdigest()
    section, root = arguments

    completed = _run_cli(
        environment,
        "set-root",
        section,
        root.replace("{mount}", str(tmp_path / "elsewhere")),
        "--json",
        "--expected-hash",
        expected_hash,
    )
    payload = _payload(completed)

    assert completed.returncode == exit_code
    assert payload["status"] == status
    assert payload["changed"] is False
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == code
    assert error["path"] is None
    assert path.read_bytes() == original
    assert read_user_config_snapshot(path, environ={}).content == original
