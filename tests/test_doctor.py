# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Layered read-only doctor diagnostics and failure taxonomy tests."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import doctor
import server
from doctor import (
    DiagnosticCheck,
    DoctorContext,
    RuntimeContracts,
    render_json,
    run_doctor,
)

FINGERPRINT = {
    "embedding_model": "test-model",
    "fastembed_version": "0.8.0",
    "pooling": "mean",
}


def _write_config(
    path: Path,
    *,
    kb_path: Path,
    chroma_path: Path,
    lock_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                f'kb_path = "{kb_path.as_posix()}"',
                f'chroma_path = "{chroma_path.as_posix()}"',
                'included_sections = ["knowledge"]',
                "excluded_dirs = []",
                "exclude_files = []",
                f'write_lock_path = "{lock_path.as_posix()}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _create_index(
    path: Path,
    *,
    fingerprint: dict[str, str] | None = None,
    source_path: str = "knowledge/note.md",
    content_hash: str | None = None,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path / "chroma.sqlite3")
    connection.executescript(
        """
        CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE collection_metadata (
            collection_id TEXT, key TEXT, str_value TEXT,
            int_value INTEGER, float_value REAL, bool_value INTEGER
        );
        CREATE TABLE segments (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, collection TEXT NOT NULL
        );
        CREATE TABLE embeddings (
            id INTEGER PRIMARY KEY, segment_id TEXT NOT NULL,
            embedding_id TEXT NOT NULL
        );
        CREATE TABLE embedding_metadata (
            id INTEGER, key TEXT, string_value TEXT,
            int_value INTEGER, float_value REAL, bool_value INTEGER
        );
        """
    )
    connection.execute("INSERT INTO collections VALUES ('collection', 'cortex')")
    for key, value in (fingerprint or FINGERPRINT).items():
        connection.execute(
            "INSERT INTO collection_metadata VALUES (?, ?, ?, NULL, NULL, NULL)",
            ("collection", key, value),
        )
    connection.execute("INSERT INTO segments VALUES ('metadata', 'METADATA', 'collection')")
    connection.execute("INSERT INTO embeddings VALUES (1, 'metadata', 'chunk-1')")
    metadata = {
        "path": source_path,
        "section": source_path.split("/", 1)[0],
        "content_hash": content_hash or ("a" * 64),
        "contract_id": "freshness-contract-v1",
        "content_hash_contract_version": "v1",
    }
    for key, value in metadata.items():
        connection.execute(
            "INSERT INTO embedding_metadata VALUES (1, ?, ?, NULL, NULL, NULL)",
            (key, value),
        )
    connection.commit()
    connection.close()


def _ok_handshake(
    _python: str,
    _server: Path,
    _environ: Any,
    timeout: float,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        "mcp.handshake",
        "OK",
        "fixture initialize succeeded",
        {"timeout_seconds": timeout},
    )


def _context(
    tmp_path: Path,
    *,
    python_version: tuple[int, int, int] = (3, 13, 0),
    which_map: dict[str, str] | None = None,
    runner=None,
    lock_probe=None,
    handshake_probe=_ok_handshake,
) -> DoctorContext:
    script_dir = tmp_path / "install"
    appdata = tmp_path / "roaming"
    local = tmp_path / "local"
    home = tmp_path / "home"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "server.py").write_text("# fixture server\n", encoding="utf-8")
    config_path = appdata / "Cortex" / "config.toml"
    values = {
        "APPDATA": str(appdata),
        "LOCALAPPDATA": str(local),
        "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    mapping = which_map or {}
    return DoctorContext(
        script_dir=script_dir,
        config_path=config_path,
        environ=values,
        home=home,
        python_exe=sys.executable,
        python_version=python_version,
        package_finder=lambda _name: object(),
        which=lambda name: mapping.get(name),
        runner=runner or subprocess.run,
        handshake_probe=handshake_probe,
        contracts_provider=lambda: RuntimeContracts("cortex", FINGERPRINT),
        lock_probe=lock_probe,
        now=lambda: datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
    )


def _baseline(tmp_path: Path, **context_kwargs: Any) -> DoctorContext:
    context = _context(tmp_path, **context_kwargs)
    kb = tmp_path / "kb"
    section = kb / "knowledge"
    section.mkdir(parents=True)
    source = section / "note.md"
    source.write_bytes(b"# Note\nBody used by freshness.\n")
    content_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    chroma = tmp_path / "local" / "Cortex" / "chroma_db"
    lock = tmp_path / "local" / "Cortex" / "chroma_db.write.lock"
    _write_config(
        context.config_path,
        kb_path=kb,
        chroma_path=chroma,
        lock_path=lock,
    )
    _create_index(chroma, content_hash=content_hash)
    return context


def _checks(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        check["id"]: check
        for section in report["sections"]
        for check in section["checks"]
    }


def test_python_too_old_is_fail(tmp_path: Path) -> None:
    report = run_doctor(_baseline(tmp_path, python_version=(3, 9, 19)))

    assert _checks(report)["python.version"]["status"] == "FAIL"
    assert report["summary"]["exit_code"] == 1


def test_invalid_config_is_typed_fail(tmp_path: Path) -> None:
    context = _context(tmp_path)
    context.config_path.parent.mkdir(parents=True)
    context.config_path.write_text("schema_version = 1\ntypo = true\n", encoding="utf-8")

    report = run_doctor(context)

    check = _checks(report)["config.valid"]
    assert check["status"] == "FAIL"
    assert "Unknown configuration key" in check["message"]


def test_inaccessible_kb_path_is_distinct_fail(tmp_path: Path) -> None:
    context = _context(tmp_path)
    chroma = tmp_path / "local" / "Cortex" / "chroma_db"
    _write_config(
        context.config_path,
        kb_path=tmp_path / "missing-kb",
        chroma_path=chroma,
        lock_path=tmp_path / "local" / "Cortex" / "lock",
    )
    _create_index(chroma)

    report = run_doctor(context)

    checks = _checks(report)
    assert checks["kb.configured"]["status"] == "OK"
    assert checks["kb.accessible"]["status"] == "FAIL"


def test_migration_required_is_fail(tmp_path: Path) -> None:
    context = _context(tmp_path)
    kb = tmp_path / "kb"
    kb.mkdir()
    target = tmp_path / "local" / "Cortex" / "chroma_db"
    _write_config(
        context.config_path,
        kb_path=kb,
        chroma_path=target,
        lock_path=tmp_path / "lock",
    )
    (context.script_dir / "chroma_db").mkdir()

    report = run_doctor(context)

    check = _checks(report)["data_home.migration"]
    assert check["status"] == "FAIL"
    assert check["details"]["state"] == "required"


def test_migration_conflict_is_fail(tmp_path: Path) -> None:
    context = _baseline(tmp_path)
    (context.script_dir / "chroma_db").mkdir()

    report = run_doctor(context)

    check = _checks(report)["data_home.migration"]
    assert check["status"] == "FAIL"
    assert check["details"]["state"] == "conflict"


def test_fingerprint_mismatch_has_existing_detail(tmp_path: Path) -> None:
    context = _baseline(tmp_path)
    sqlite_path = tmp_path / "local" / "Cortex" / "chroma_db" / "chroma.sqlite3"
    connection = sqlite3.connect(sqlite_path)
    connection.execute(
        "UPDATE collection_metadata SET str_value = 'cls' WHERE key = 'pooling'"
    )
    connection.commit()
    connection.close()

    report = run_doctor(context)

    check = _checks(report)["index.fingerprint"]
    assert check["status"] == "FAIL"
    assert check["details"]["differences"]["pooling"] == {
        "stored": "cls",
        "runtime": "mean",
    }


def test_stale_lock_is_warn_and_preserved(tmp_path: Path) -> None:
    context = _baseline(tmp_path)
    lock_path = tmp_path / "local" / "Cortex" / "chroma_db.write.lock"
    lock_path.write_bytes(b"")
    before = lock_path.stat()

    report = run_doctor(context)

    check = _checks(report)["write_lock.state"]
    assert check["status"] == "WARN"
    assert check["details"]["state"] == "stale"
    assert lock_path.read_bytes() == b""
    assert lock_path.stat().st_mtime_ns == before.st_mtime_ns


def test_missing_client_entry_is_fail(tmp_path: Path) -> None:
    context = _baseline(tmp_path, which_map={"gemini": "gemini"})
    settings = context.home / ".gemini" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")

    report = run_doctor(context)

    assert _checks(report)["client.gemini.entry"]["status"] == "FAIL"


def test_invalid_client_paths_are_fail(tmp_path: Path) -> None:
    context = _baseline(tmp_path, which_map={"gemini": "gemini"})
    settings = context.home / ".gemini" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cortex": {
                        "command": str(tmp_path / "missing-python"),
                        "args": [str(tmp_path / "missing-server.py")],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    report = run_doctor(context)

    checks = _checks(report)
    assert checks["client.gemini.entry"]["status"] == "OK"
    assert checks["client.gemini.paths"]["status"] == "FAIL"


def test_absent_gemini_extension_is_info_not_fail(tmp_path: Path) -> None:
    report = run_doctor(_baseline(tmp_path))

    check = _checks(report)["client.gemini.vscode_extension"]
    assert check["status"] == "INFO"
    assert check["details"]["installed"] is False


def test_unprobeable_auth_is_unknown_never_ok(tmp_path: Path) -> None:
    context = _baseline(tmp_path, which_map={"gemini": "gemini"})
    settings = context.home / ".gemini" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cortex": {
                        "command": sys.executable,
                        "args": [str(context.script_dir / "server.py")],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    report = run_doctor(context)

    auth = _checks(report)["client.gemini.auth"]
    assert auth["status"] == "UNKNOWN"
    assert report["summary"]["counts"]["UNKNOWN"] >= 1


def test_claude_probe_propagates_strict_read_only_mode(tmp_path: Path) -> None:
    observed: dict[str, Any] = {}
    context = _baseline(tmp_path, which_map={"claude": "claude"})

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["env"] = kwargs["env"]
        output = f"{Path(sys.executable).resolve()} {context.script_dir / 'server.py'}"
        return subprocess.CompletedProcess(command, 0, output, "")

    context.runner = runner

    report = run_doctor(context)

    assert _checks(report)["client.claude-code.auth"]["status"] == "OK"
    assert observed["command"][1:] == ["mcp", "get", "cortex"]
    assert observed["env"]["CORTEX_DOCTOR_READ_ONLY"] == "1"
    assert observed["env"]["PYTHONDONTWRITEBYTECODE"] == "1"


def _snapshot(root: Path) -> dict[str, tuple[str, int, int]]:
    snapshot: dict[str, tuple[str, int, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot[relative] = ("dir", 0, path.stat().st_mtime_ns)
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[relative] = (digest, path.stat().st_size, path.stat().st_mtime_ns)
    return snapshot


def test_complete_run_is_strictly_read_only(tmp_path: Path) -> None:
    context = _baseline(tmp_path)
    logs = tmp_path / "local" / "Cortex" / "logs"
    logs.mkdir()
    (logs / "cortex.log").write_text(
        "2026-07-12T12:00:00+0200 ERROR cortex.sync errors=1\n",
        encoding="utf-8",
    )
    lock = tmp_path / "local" / "Cortex" / "chroma_db.write.lock"
    lock.write_bytes(b"")
    before = _snapshot(tmp_path)

    report = run_doctor(context)

    assert report["read_only"] is True
    assert _snapshot(tmp_path) == before


def test_json_schema_is_stable_and_warn_unknown_do_not_break_exit(tmp_path: Path) -> None:
    report = run_doctor(_baseline(tmp_path))
    parsed = json.loads(render_json(report))

    assert set(parsed) == {
        "schema_version",
        "tool",
        "read_only",
        "generated_at_utc",
        "summary",
        "sections",
    }
    assert parsed["schema_version"] == 1
    assert set(parsed["summary"]) == {"counts", "failures", "exit_code"}
    assert set(parsed["summary"]["counts"]) == set(doctor.DOCTOR_STATUSES)
    assert parsed["summary"]["exit_code"] == 0
    assert [section["id"] for section in parsed["sections"]] == [
        "system",
        "configuration",
        "data",
        "index",
        "operations",
        "clients",
        "mcp",
    ]
    for section in parsed["sections"]:
        assert set(section) == {"id", "title", "checks"}
        for check in section["checks"]:
            assert set(check) == {"id", "status", "message", "details"}
            assert check["status"] in doctor.DOCTOR_STATUSES


def test_handshake_runs_once_globally(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handshake(*args: Any) -> DiagnosticCheck:
        calls["count"] += 1
        return _ok_handshake(*args)

    report = run_doctor(_baseline(tmp_path, handshake_probe=handshake))

    assert calls["count"] == 1
    assert _checks(report)["mcp.handshake"]["status"] == "OK"


@pytest.mark.asyncio
async def test_doctor_lifespan_never_opens_chroma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORTEX_DOCTOR_READ_ONLY", "1")

    def forbidden_collection() -> None:
        raise AssertionError("doctor lifespan must not open PersistentClient")

    monkeypatch.setattr(server, "get_collection", forbidden_collection)

    async with server.app_lifespan(None) as state:
        assert state == {"doctor_read_only": True}


def test_real_server_handshake_is_read_only_and_self_terminating(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    environ = dict(os.environ)
    environ.pop("CORTEX_KB_PATH", None)
    environ["APPDATA"] = str(tmp_path / "roaming")
    environ["LOCALAPPDATA"] = str(tmp_path / "local")
    environ["HOME"] = str(tmp_path / "home")
    before = _snapshot(tmp_path)

    check = doctor._default_handshake_probe(
        sys.executable,
        root / "server.py",
        environ,
        timeout=10,
    )

    assert check.status == "OK"
    assert check.details["diagnostic_lifespan"] is True
    assert _snapshot(tmp_path) == before


def test_recent_errors_are_bounded_across_rotated_logs(tmp_path: Path) -> None:
    context = _baseline(tmp_path)
    logs = tmp_path / "local" / "Cortex" / "logs"
    logs.mkdir()
    (logs / "cortex.log.1").write_text(
        "old ERROR cortex.sync errors=1\n",
        encoding="utf-8",
    )
    (logs / "cortex.log").write_text(
        "new ERROR cortex.sync errors=2\nnew ERROR cortex.sync errors=3\n",
        encoding="utf-8",
    )
    context.error_line_limit = 2

    report = run_doctor(context)

    check = _checks(report)["logs.recent_errors"]
    assert check["status"] == "WARN"
    assert len(check["details"]["lines"]) == 2
    assert check["details"]["lines"][-1].endswith("errors=3")
