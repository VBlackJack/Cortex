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
"""Layered, strictly read-only Cortex support diagnostics."""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _version import __version__
from data_home import migration_state
from dependencies import REQUIRED_PACKAGES
from user_config import (
    CortexConfigError,
    CortexUserConfig,
    load_user_config,
    local_data_home,
    user_config_path,
)

DOCTOR_SCHEMA_VERSION = 1
DOCTOR_STATUSES = ("OK", "WARN", "FAIL", "SKIP", "UNKNOWN", "INFO")
DEFAULT_HANDSHAKE_TIMEOUT_SECONDS = 20.0
DEFAULT_ERROR_LINE_LIMIT = 10
_FINGERPRINT_KEYS = ("embedding_model", "fastembed_version", "pooling")
_FRESHNESS_KEYS = (
    "path",
    "section",
    "content_hash",
    "contract_id",
    "content_hash_contract_version",
)


@dataclass(frozen=True)
class DiagnosticCheck:
    """One stable, copy-friendly diagnostic result."""

    id: str
    status: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class RuntimeContracts:
    """Index contracts needed by the read-only SQLite inspector."""

    collection_name: str
    fingerprint: Mapping[str, str]
    lexical_contract_version: str = "v1"


PackageFinder = Callable[[str], object | None]
Which = Callable[[str], str | None]
Runner = Callable[..., subprocess.CompletedProcess[str]]
HandshakeProbe = Callable[[str, Path, Mapping[str, str], float], DiagnosticCheck]
ContractsProvider = Callable[[], RuntimeContracts]
LockProbe = Callable[[Path], tuple[str, int | None, str | None]]
RerankerProbe = Callable[[], DiagnosticCheck]


@dataclass
class DoctorContext:
    """Injectable environment for deterministic, side-effect-free tests."""

    script_dir: Path
    config_path: Path
    environ: Mapping[str, str]
    home: Path
    python_exe: str
    python_version: tuple[int, int, int]
    package_finder: PackageFinder = importlib.util.find_spec
    which: Which = shutil.which
    runner: Runner = subprocess.run
    handshake_probe: HandshakeProbe | None = None
    contracts_provider: ContractsProvider | None = None
    lock_probe: LockProbe | None = None
    reranker_probe: RerankerProbe | None = None
    handshake_timeout_seconds: float = DEFAULT_HANDSHAKE_TIMEOUT_SECONDS
    error_line_limit: int = DEFAULT_ERROR_LINE_LIMIT
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def default_context(
    *,
    script_dir: Path | None = None,
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    python_exe: str | None = None,
) -> DoctorContext:
    """Build the real local context without creating any paths."""
    values = dict(os.environ if environ is None else environ)
    root = Path(__file__).parent.resolve() if script_dir is None else Path(script_dir)
    configured_home = values.get("HOME") or values.get("USERPROFILE")
    user_home = Path(configured_home) if configured_home else Path.home()
    if home is not None:
        user_home = Path(home)
    return DoctorContext(
        script_dir=root,
        config_path=user_config_path(values) if config_path is None else Path(config_path),
        environ=values,
        home=user_home,
        python_exe=python_exe or sys.executable,
        python_version=(sys.version_info.major, sys.version_info.minor, sys.version_info.micro),
        reranker_probe=_default_reranker_probe,
    )


def _default_contracts() -> RuntimeContracts:
    from config import COLLECTION_NAME, LEXICAL_INDEX_CONTRACT_VERSION
    from embedding_fingerprint import current_embedding_fingerprint

    return RuntimeContracts(
        collection_name=COLLECTION_NAME,
        fingerprint=current_embedding_fingerprint(),
        lexical_contract_version=LEXICAL_INDEX_CONTRACT_VERSION,
    )


def _check(
    check_id: str,
    status: str,
    message: str,
    **details: Any,
) -> DiagnosticCheck:
    if status not in DOCTOR_STATUSES:
        raise ValueError(f"Unsupported doctor status: {status}")
    return DiagnosticCheck(check_id, status, message, details)


def _default_reranker_probe() -> DiagnosticCheck:
    """Probe only an already cached reranker without network or filesystem writes."""
    from offline_models import activate_if_embedded

    model_runtime = activate_if_embedded()

    from fastembed.rerank.cross_encoder import TextCrossEncoder

    from config import RERANKER_MODEL, SEARCH_RERANK_CANDIDATES

    cache_root = model_runtime.cache_dir
    model_cache = cache_root / f"models--{RERANKER_MODEL.replace('/', '--')}"
    if not model_cache.is_dir():
        return _check(
            "reranker.runtime",
            "WARN",
            "Configured reranker is not present in the fastembed cache",
            model=RERANKER_MODEL,
            cache_path=str(model_cache),
            cached=False,
            read_only=True,
        )
    model: Any = None
    try:
        model = TextCrossEncoder(
            RERANKER_MODEL,
            cache_dir=str(cache_root),
            threads=None,
            cuda=False,
            local_files_only=True,
        )
        started = time.perf_counter()
        scores = list(
            model.rerank(
                "cortex doctor reranker probe",
                ["cortex diagnostic document"] * SEARCH_RERANK_CANDIDATES,
                batch_size=SEARCH_RERANK_CANDIDATES,
            )
        )
        latency_ms = (time.perf_counter() - started) * 1000
        if len(scores) != SEARCH_RERANK_CANDIDATES:
            raise ValueError(
                f"reranker returned {len(scores)} scores for "
                f"{SEARCH_RERANK_CANDIDATES} documents"
            )
    except Exception as exc:  # noqa: BLE001 -- diagnostic must remain honest and total.
        return _check(
            "reranker.runtime",
            "UNKNOWN",
            f"Cached reranker could not be probed read-only: {exc}",
            model=RERANKER_MODEL,
            cache_path=str(model_cache),
            cached=True,
            read_only=True,
        )
    finally:
        del model
        gc.collect()
    within_budget = latency_ms <= 250.0
    return _check(
        "reranker.runtime",
        "OK" if within_budget else "WARN",
        "Cached reranker loaded and completed a read-only batch probe",
        model=RERANKER_MODEL,
        cache_path=str(model_cache),
        cached=True,
        candidate_count=SEARCH_RERANK_CANDIDATES,
        latency_ms=round(latency_ms, 3),
        budget_ms=250.0,
        within_budget=within_budget,
        read_only=True,
    )


def _reranker_check(context: DoctorContext) -> DiagnosticCheck:
    if context.reranker_probe is None:
        return _check(
            "reranker.runtime",
            "UNKNOWN",
            "Reranker health was not probed in this diagnostic context",
            read_only=True,
        )
    try:
        return context.reranker_probe()
    except Exception as exc:  # noqa: BLE001 -- external probe must not crash doctor.
        return _check(
            "reranker.runtime",
            "UNKNOWN",
            f"Reranker health is not sondable: {exc}",
            read_only=True,
        )


def _system_checks(context: DoctorContext) -> list[DiagnosticCheck]:
    version = context.python_version
    checks = [
        _check(
            "python.version",
            "OK" if version >= (3, 10, 0) else "FAIL",
            f"Python {'.'.join(map(str, version))}"
            + (" is supported" if version >= (3, 10, 0) else " is too old; require >= 3.10"),
            executable=context.python_exe,
            version=list(version),
            minimum=[3, 10],
        )
    ]
    for package in REQUIRED_PACKAGES:
        import_name = package.split("[")[0]
        try:
            available = context.package_finder(import_name) is not None
        except (ImportError, AttributeError, ValueError) as exc:
            checks.append(
                _check(
                    f"package.{import_name}",
                    "FAIL",
                    f"Could not inspect package {package}: {exc}",
                    package=package,
                )
            )
            continue
        checks.append(
            _check(
                f"package.{import_name}",
                "OK" if available else "FAIL",
                f"Package {package} is importable"
                if available
                else f"Package {package} is not importable",
                package=package,
            )
        )
    return checks


def _configuration_checks(
    context: DoctorContext,
) -> tuple[list[DiagnosticCheck], CortexUserConfig | None, bool]:
    checks: list[DiagnosticCheck] = []
    try:
        config = load_user_config(
            path=context.config_path,
            environ=context.environ,
            script_dir=context.script_dir,
        )
    except CortexConfigError as exc:
        checks.append(
            _check(
                "config.valid",
                "FAIL",
                str(exc),
                path=str(context.config_path),
            )
        )
        checks.extend(
            [
                _check("kb.configured", "SKIP", "Skipped because config is invalid"),
                _check("kb.accessible", "SKIP", "Skipped because config is invalid"),
            ]
        )
        return checks, None, False

    checks.append(
        _check(
            "config.valid",
            "OK",
            "User configuration is valid",
            path=str(context.config_path),
            schema_version=config.schema_version,
        )
    )
    if not config.kb_path:
        checks.extend(
            [
                _check(
                    "kb.configured",
                    "FAIL",
                    "kb_path is not configured; run `cortex setup`",
                ),
                _check("kb.accessible", "SKIP", "Skipped because kb_path is missing"),
            ]
        )
        return checks, config, False

    kb_path = Path(config.kb_path)
    checks.append(
        _check(
            "kb.configured",
            "OK",
            "kb_path is configured",
            path=str(kb_path),
        )
    )
    accessible = kb_path.is_dir()
    checks.append(
        _check(
            "kb.accessible",
            "OK" if accessible else "FAIL",
            "Knowledge base directory is accessible"
            if accessible
            else "Configured kb_path is not an accessible directory",
            path=str(kb_path),
        )
    )
    return checks, config, accessible


def _data_home_check(context: DoctorContext, config: CortexUserConfig) -> DiagnosticCheck:
    legacy = context.script_dir / "chroma_db"
    target = Path(config.chroma_path)
    state = migration_state(legacy, target)
    statuses = {
        "ready": "OK",
        "configured_legacy": "OK",
        "empty": "WARN",
        "required": "FAIL",
        "conflict": "FAIL",
    }
    messages = {
        "ready": "Configured data-home index is ready",
        "configured_legacy": "Legacy index path is an explicit configured override",
        "empty": "No Cortex index exists yet; run a sync when ready",
        "required": "Legacy index migration is required before search or sync",
        "conflict": "Legacy and configured indexes both exist; refusing ambiguity",
    }
    return _check(
        "data_home.migration",
        statuses[state],
        messages[state],
        state=state,
        legacy_path=str(legacy),
        target_path=str(target),
    )


class _MetadataCollection:
    """Minimal Chroma get() adapter backed by read-only SQLite metadata."""

    def __init__(self, metadatas: Sequence[dict[str, Any]]) -> None:
        self._metadatas = list(metadatas)

    def get(
        self,
        *,
        where: Mapping[str, Any] | None = None,
        limit: int = 5_000,
        offset: int = 0,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        rows = self._metadatas
        if where and "section" in where:
            rows = [item for item in rows if item.get("section") == where["section"]]
        return {"metadatas": rows[offset : offset + limit]}


def _metadata_value(row: Sequence[Any]) -> Any:
    for value in row:
        if value is not None:
            return value
    return None


def _open_index_read_only(sqlite_path: Path) -> sqlite3.Connection:
    uri = sqlite_path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _open_lexical_read_only(sqlite_path: Path) -> sqlite3.Connection:
    """Open read-only while allowing SQLite to observe an existing WAL file."""
    uri = sqlite_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _inspect_index(
    index_path: Path,
    contracts: RuntimeContracts,
) -> tuple[list[DiagnosticCheck], list[dict[str, Any]] | None]:
    checks: list[DiagnosticCheck] = []
    if not index_path.is_dir():
        return [
            _check(
                "index.present",
                "WARN",
                "Index directory is absent",
                path=str(index_path),
            ),
            _check("index.chunks", "SKIP", "Skipped because index is absent"),
            _check("index.fingerprint", "SKIP", "Skipped because index is absent"),
        ], None
    sqlite_path = index_path / "chroma.sqlite3"
    if not sqlite_path.is_file():
        return [
            _check(
                "index.present",
                "FAIL",
                "Index directory exists but chroma.sqlite3 is missing",
                path=str(index_path),
            ),
            _check("index.chunks", "SKIP", "Skipped because SQLite is missing"),
            _check("index.fingerprint", "SKIP", "Skipped because SQLite is missing"),
        ], None

    checks.append(
        _check(
            "index.present",
            "OK",
            "Chroma SQLite index is present",
            path=str(sqlite_path),
        )
    )
    try:
        with closing(_open_index_read_only(sqlite_path)) as connection:
            collection_row = connection.execute(
                "SELECT id FROM collections WHERE name = ?",
                (contracts.collection_name,),
            ).fetchone()
            if collection_row is None:
                checks.extend(
                    [
                        _check(
                            "index.chunks",
                            "FAIL",
                            f"Collection {contracts.collection_name!r} is missing",
                        ),
                        _check(
                            "index.fingerprint",
                            "SKIP",
                            "Skipped because collection is missing",
                        ),
                    ]
                )
                return checks, None
            collection_id = str(collection_row[0])
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM embeddings e "
                    "JOIN segments s ON s.id = e.segment_id "
                    "WHERE s.collection = ? AND s.scope = 'METADATA'",
                    (collection_id,),
                ).fetchone()[0]
            )
            checks.append(
                _check(
                    "index.chunks",
                    "OK" if count > 0 else "WARN",
                    f"Index contains {count} chunks",
                    count=count,
                )
            )
            stored_rows = connection.execute(
                "SELECT key, str_value, int_value, float_value, bool_value "
                "FROM collection_metadata WHERE collection_id = ?",
                (collection_id,),
            ).fetchall()
            stored = {
                str(row[0]): _metadata_value(row[1:])
                for row in stored_rows
                if row[0] in _FINGERPRINT_KEYS
            }
            differences = {
                key: {
                    "stored": stored.get(key, "<missing>"),
                    "runtime": runtime,
                }
                for key, runtime in contracts.fingerprint.items()
                if stored.get(key) != runtime
            }
            checks.append(
                _check(
                    "index.fingerprint",
                    "FAIL" if differences else "OK",
                    "Embedding fingerprint mismatch"
                    if differences
                    else "Embedding fingerprint matches the runtime",
                    stored=stored,
                    runtime=dict(contracts.fingerprint),
                    differences=differences,
                )
            )

            metadata_rows = connection.execute(
                "SELECT e.id, m.key, m.string_value, m.int_value, "
                "m.float_value, m.bool_value FROM embeddings e "
                "JOIN segments s ON s.id = e.segment_id "
                "JOIN embedding_metadata m ON m.id = e.id "
                "WHERE s.collection = ? AND s.scope = 'METADATA' "
                f"AND m.key IN ({','.join('?' for _ in _FRESHNESS_KEYS)}) "
                "ORDER BY e.id",
                (collection_id, *_FRESHNESS_KEYS),
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        checks.append(
            _check(
                "index.read",
                "FAIL",
                f"Could not inspect Chroma SQLite read-only: {exc}",
                path=str(sqlite_path),
            )
        )
        return checks, None

    by_id: dict[int, dict[str, Any]] = {}
    for embedding_id, key, *values in metadata_rows:
        by_id.setdefault(int(embedding_id), {})[str(key)] = _metadata_value(values)
    return checks, list(by_id.values())


def _freshness_check(
    config: CortexUserConfig,
    metadatas: Sequence[dict[str, Any]],
) -> DiagnosticCheck:
    import freshness

    report = freshness.cortex_freshness_report(
        _MetadataCollection(metadatas),
        include_entries=False,
        emit_log=False,
        scope=freshness.FreshnessScope(
            kb_path=config.kb_path,
            included_sections=config.included_sections,
            excluded_dirs=config.excluded_dirs,
            exclude_files=config.exclude_files,
            index_whole_folder=config.index_whole_folder,
        ),
    )
    summary = report.get("summary", {})
    bad = sum(int(summary.get(key, 0)) for key in ("stale", "missing", "error"))
    status = "WARN" if bad else "OK"
    return _check(
        "freshness.summary",
        status,
        f"Freshness summary: {json.dumps(summary, sort_keys=True)}",
        summary=summary,
        entries_included=False,
        read_only=True,
    )


def _inspect_lexical_index(
    path: Path,
    *,
    expected_contract_version: str,
    chroma_count: int | None,
) -> list[DiagnosticCheck]:
    """Inspect the derived FTS5 index without creating or repairing it."""
    if not path.is_file():
        return [
            _check(
                "lexical.index",
                "WARN",
                "Lexical index is absent; next sync will rebuild it",
                path=str(path),
                purge_scope=True,
            )
        ]
    try:
        with closing(_open_lexical_read_only(path)) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM meta"))
            count = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    except (OSError, sqlite3.Error) as exc:
        return [
            _check(
                "lexical.index",
                "FAIL",
                f"Could not inspect lexical index read-only: {exc}",
                path=str(path),
            )
        ]
    compatible = metadata.get("contract_version") == expected_contract_version
    synchronized = chroma_count is not None and count == chroma_count
    status = "OK" if compatible and synchronized else "WARN"
    return [
        _check(
            "lexical.index",
            status,
            "Lexical index matches Chroma"
            if status == "OK"
            else "Lexical index requires a sync rebuild",
            path=str(path),
            count=count,
            chroma_count=chroma_count,
            contract_version=metadata.get("contract_version", "<missing>"),
            expected_contract_version=expected_contract_version,
            compatible=compatible,
            synchronized=synchronized,
            read_only=True,
            purge_scope=True,
        )
    ]


def _default_lock_probe(path: Path) -> tuple[str, int | None, str | None]:
    if not path.exists():
        return "free", None, None
    pid: int | None = None
    try:
        text = path.read_text(encoding="ascii", errors="ignore").strip()
        if text.isdigit():
            pid = int(text)
    except OSError:
        pass
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError as exc:
        return "unknown", pid, str(exc)
    try:
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                return "held", pid, None
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - Windows is the supported deployment target
            import fcntl

            try:
                flock = getattr(fcntl, "flock")
                flock(fd, getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB"))
            except BlockingIOError:
                return "held", pid, None
            flock(fd, getattr(fcntl, "LOCK_UN"))
    finally:
        os.close(fd)
    return "stale", pid, None


def _write_lock_check(context: DoctorContext, path: Path) -> DiagnosticCheck:
    probe = context.lock_probe or _default_lock_probe
    state, pid, error = probe(path)
    statuses = {"free": "OK", "held": "WARN", "stale": "WARN", "unknown": "UNKNOWN"}
    messages = {
        "free": "Write lock is free; no lock file exists",
        "held": f"Write lock is currently held by PID {pid}"
        if pid is not None
        else "Write lock is currently held (PID unavailable)",
        "stale": "Lock file exists but is not held (stale marker)",
        "unknown": "Write lock state could not be determined",
    }
    return _check(
        "write_lock.state",
        statuses.get(state, "UNKNOWN"),
        messages.get(state, f"Unknown lock state: {state}"),
        state=state,
        path=str(path),
        pid=pid,
        error=error,
    )


def _log_error_check(log_dir: Path, limit: int) -> DiagnosticCheck:
    if not log_dir.is_dir():
        return _check(
            "logs.recent_errors",
            "INFO",
            "Log directory does not exist",
            path=str(log_dir),
            lines=[],
        )
    def rotation_order(path: Path) -> tuple[int, int, float]:
        if path.name == "cortex.log":
            return (2, 0, path.stat().st_mtime)
        suffix = path.name.removeprefix("cortex.log.")
        if suffix.isdigit():
            return (1, -int(suffix), path.stat().st_mtime)
        return (0, 0, path.stat().st_mtime)

    files = sorted(log_dir.glob("cortex.log*"), key=rotation_order)
    errors: list[str] = []
    try:
        for path in files:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if " ERROR " in line and "cortex.sync" in line:
                    errors.append(line)
    except OSError as exc:
        return _check(
            "logs.recent_errors",
            "UNKNOWN",
            f"Could not read rotated logs: {exc}",
            path=str(log_dir),
            lines=[],
        )
    recent = errors[-limit:]
    return _check(
        "logs.recent_errors",
        "WARN" if recent else "OK",
        f"Found {len(recent)} recent sync ERROR line(s)"
        if recent
        else "No sync ERROR lines found",
        path=str(log_dir),
        limit=limit,
        lines=recent,
    )


def _claude_desktop_binary(context: DoctorContext) -> Path | None:
    local = context.environ.get("LOCALAPPDATA")
    if not local:
        return None
    candidates = [
        Path(local) / "AnthropicClaude" / "claude.exe",
        Path(local) / "Programs" / "Claude" / "Claude.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _client_checks(context: DoctorContext) -> list[DiagnosticCheck]:
    import setup_config

    registry = setup_config.client_registry(
        context.python_exe,
        environ=context.environ,
        home=context.home,
        which=context.which,
    )
    checks: list[DiagnosticCheck] = []
    for name, target in registry.items():
        detected = setup_config._client_is_detected(target)
        binary = target.executable
        if name == "claude-desktop":
            desktop_binary = _claude_desktop_binary(context)
            binary = str(desktop_binary) if desktop_binary else None
        if binary:
            checks.append(
                _check(
                    f"client.{name}.binary",
                    "OK",
                    "Client binary is present",
                    executable=str(binary),
                )
            )
        elif detected:
            checks.append(
                _check(
                    f"client.{name}.binary",
                    "INFO",
                    "No reliable binary probe succeeded; client configuration footprint exists",
                )
            )
        else:
            checks.append(
                _check(f"client.{name}.binary", "SKIP", "Client is not installed")
            )

        if name == "gemini":
            extension_roots = [
                context.home / ".vscode" / "extensions",
                context.home / ".vscode-insiders" / "extensions",
            ]
            matches = [
                path
                for root in extension_roots
                if root.is_dir()
                for path in root.glob("google.geminicodeassist*")
                if path.is_dir()
            ]
            checks.append(
                _check(
                    "client.gemini.vscode_extension",
                    "INFO",
                    "Gemini Code Assist extension is installed"
                    if matches
                    else "Gemini Code Assist extension is absent (optional)",
                    installed=bool(matches),
                    matches=[str(path) for path in matches],
                )
            )

        if not detected:
            checks.extend(
                [
                    _check(f"client.{name}.entry", "SKIP", "Client is not installed"),
                    _check(f"client.{name}.paths", "SKIP", "Client is not installed"),
                    _check(f"client.{name}.auth", "SKIP", "Client is not installed"),
                ]
            )
            continue

        if name == "claude-code":
            if not target.executable:
                checks.extend(
                    [
                        _check("client.claude-code.entry", "FAIL", "Claude CLI is missing"),
                        _check("client.claude-code.paths", "SKIP", "Entry probe failed"),
                        _check(
                            "client.claude-code.auth",
                            "UNKNOWN",
                            "Run Claude Code and verify sign-in manually",
                        ),
                    ]
                )
                continue
            try:
                probe_env = dict(context.environ)
                probe_env["CORTEX_DOCTOR_READ_ONLY"] = "1"
                probe_env["PYTHONDONTWRITEBYTECODE"] = "1"
                result = context.runner(
                    [target.executable, "mcp", "get", "cortex"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=probe_env,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                result = subprocess.CompletedProcess([], 1, "", str(exc))
            combined = (result.stdout or "") + (result.stderr or "")
            entry_ok = result.returncode == 0
            expected = [str(target.entry["command"]), *map(str, target.entry["args"])]
            paths_ok = entry_ok and all(value in combined for value in expected)
            checks.extend(
                [
                    _check(
                        "client.claude-code.entry",
                        "OK" if entry_ok else "FAIL",
                        "User-scope Cortex entry is present"
                        if entry_ok
                        else "User-scope Cortex entry is missing or unreadable",
                    ),
                    _check(
                        "client.claude-code.paths",
                        "OK" if paths_ok else "FAIL",
                        "Stored command and server paths are valid"
                        if paths_ok
                        else "Stored command or server path is stale",
                    ),
                    _check(
                        "client.claude-code.auth",
                        "OK" if entry_ok else "UNKNOWN",
                        "Claude CLI responded to `claude mcp get cortex`"
                        if entry_ok
                        else "Authentication could not be inferred; run Claude Code manually",
                        probe="claude mcp get cortex",
                    ),
                ]
            )
            continue

        try:
            entry = setup_config._entry_from_file(target)
            entry_error = None
        except setup_config.ClientConfigError as exc:
            entry = None
            entry_error = str(exc)
        if entry is None:
            checks.extend(
                [
                    _check(
                        f"client.{name}.entry",
                        "FAIL",
                        entry_error or "Cortex MCP entry is missing",
                    ),
                    _check(f"client.{name}.paths", "SKIP", "Entry is missing"),
                ]
            )
        else:
            path_error = setup_config._validate_entry_paths(entry)
            checks.extend(
                [
                    _check(f"client.{name}.entry", "OK", "Cortex MCP entry is present"),
                    _check(
                        f"client.{name}.paths",
                        "FAIL" if path_error else "OK",
                        path_error or "Stored server command and arguments are valid",
                    ),
                ]
            )
        actions = {
            "claude-desktop": "Open Claude Desktop and confirm the signed-in profile manually",
            "codex": "Run Codex and confirm authentication manually",
            "gemini": "Run Gemini or Gemini Code Assist and complete the browser sign-in manually",
            "antigravity": "Open Antigravity and confirm the signed-in account manually",
            "lmstudio": "Open LM Studio and confirm the MCP integration is enabled manually",
            "cursor": "Open Cursor and confirm the signed-in account manually",
            "windsurf": "Open Windsurf and confirm the signed-in account manually",
            "vscode": "Open VS Code and confirm MCP server trust and sign-in manually",
        }
        checks.append(
            _check(
                f"client.{name}.auth",
                "UNKNOWN",
                actions[name],
                reliable_probe_available=False,
            )
        )
    return checks


def _read_initialize_response(stream: Any) -> dict[str, Any]:
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError("server.py closed stdout before initialize response")
        message = json.loads(line)
        if message.get("id") != 1:
            continue
        if "error" in message:
            raise RuntimeError(f"MCP initialize error: {message['error']}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("MCP initialize response has no result object")
        return result


def _stop_handshake_process(process: subprocess.Popen[str]) -> None:
    if process.stdin is not None and not process.stdin.closed:
        process.stdin.close()
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _default_handshake_probe(
    python_exe: str,
    server_path: Path,
    environ: Mapping[str, str],
    timeout: float,
) -> DiagnosticCheck:
    from mcp.types import LATEST_PROTOCOL_VERSION

    child_env = dict(environ)
    child_env["CORTEX_DOCTOR_READ_ONLY"] = "1"
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "cortex-doctor", "version": "1"},
        },
    }
    process: subprocess.Popen[str] | None = None
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        process = subprocess.Popen(
            [python_exe, str(server_path)],
            cwd=server_path.parent,
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
        )
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()
        result = executor.submit(_read_initialize_response, process.stdout).result(
            timeout=timeout
        )
        server_info = result.get("serverInfo") or {}
        details = {
            "server_name": server_info.get("name"),
            "server_version": server_info.get("version"),
            "protocol_version": result.get("protocolVersion"),
        }
    except FutureTimeoutError:
        return _check(
            "mcp.handshake",
            "FAIL",
            f"MCP initialize timed out after {timeout:g}s",
            timeout_seconds=timeout,
        )
    except Exception as exc:  # noqa: BLE001 -- diagnostic boundaries must report all failures.
        return _check(
            "mcp.handshake",
            "FAIL",
            f"MCP initialize failed: {exc}",
            timeout_seconds=timeout,
        )
    finally:
        if process is not None:
            _stop_handshake_process(process)
            if process.stdout is not None:
                process.stdout.close()
        executor.shutdown(wait=True, cancel_futures=True)
    return _check(
        "mcp.handshake",
        "OK",
        "Real server.py stdio initialize succeeded in read-only diagnostic mode",
        timeout_seconds=timeout,
        diagnostic_lifespan=True,
        **details,
    )


def _handshake_check(context: DoctorContext, allowed: bool) -> DiagnosticCheck:
    if not allowed:
        return _check(
            "mcp.handshake",
            "SKIP",
            "Skipped because a valid existing index is not safely available",
            timeout_seconds=context.handshake_timeout_seconds,
        )
    probe = context.handshake_probe or _default_handshake_probe
    return probe(
        context.python_exe,
        context.script_dir / "server.py",
        context.environ,
        context.handshake_timeout_seconds,
    )


def _section(section_id: str, title: str, checks: Sequence[DiagnosticCheck]) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": title,
        "checks": [check.as_dict() for check in checks],
    }


def run_doctor(context: DoctorContext | None = None) -> dict[str, Any]:
    """Run every diagnostic without creating, repairing or logging anything."""
    current = default_context() if context is None else context
    system = _system_checks(current)
    configuration, config, kb_accessible = _configuration_checks(current)
    data_checks: list[DiagnosticCheck] = []
    index_checks: list[DiagnosticCheck] = []
    operational: list[DiagnosticCheck] = []
    index_metadata: list[dict[str, Any]] | None = None

    if config is None:
        data_checks.append(
            _check("data_home.migration", "SKIP", "Skipped because config is invalid")
        )
        index_checks.extend(
            [
                _check("index.present", "SKIP", "Skipped because config is invalid"),
                _check("index.chunks", "SKIP", "Skipped because config is invalid"),
                _check("index.fingerprint", "SKIP", "Skipped because config is invalid"),
                _check("freshness.summary", "SKIP", "Skipped because config is invalid"),
                _check("lexical.index", "SKIP", "Skipped because config is invalid"),
            ]
        )
        operational.extend(
            [
                _check("write_lock.state", "SKIP", "Skipped because config is invalid"),
                _log_error_check(
                    local_data_home(current.environ) / "logs",
                    current.error_line_limit,
                ),
            ]
        )
    else:
        migration = _data_home_check(current, config)
        data_checks.append(migration)
        state = str(migration.details["state"])
        safe_location = state in {"ready", "configured_legacy"}
        contracts_provider = current.contracts_provider or _default_contracts
        if safe_location:
            try:
                contracts = contracts_provider()
                inspected, index_metadata = _inspect_index(Path(config.chroma_path), contracts)
                index_checks.extend(inspected)
                chunk_check = next(
                    (check for check in inspected if check.id == "index.chunks"),
                    None,
                )
                chroma_count = (
                    int(chunk_check.details["count"])
                    if chunk_check is not None and "count" in chunk_check.details
                    else None
                )
                index_checks.extend(
                    _inspect_lexical_index(
                        Path(config.chroma_path).parent / "lexical.db",
                        expected_contract_version=contracts.lexical_contract_version,
                        chroma_count=chroma_count,
                    )
                )
            except Exception as exc:  # noqa: BLE001 -- report a failed diagnostic, never crash.
                index_checks.extend(
                    [
                        _check("index.present", "FAIL", f"Index inspection failed: {exc}"),
                        _check("index.chunks", "SKIP", "Index inspection failed"),
                        _check("index.fingerprint", "SKIP", "Index inspection failed"),
                        _check("lexical.index", "SKIP", "Index inspection failed"),
                    ]
                )
        else:
            index_checks.extend(
                [
                    _check("index.present", "SKIP", f"Skipped: migration state is {state}"),
                    _check("index.chunks", "SKIP", f"Skipped: migration state is {state}"),
                    _check("index.fingerprint", "SKIP", f"Skipped: migration state is {state}"),
                    _check("lexical.index", "SKIP", f"Skipped: migration state is {state}"),
                ]
            )
        if kb_accessible and index_metadata is not None:
            try:
                index_checks.append(_freshness_check(config, index_metadata))
            except Exception as exc:  # noqa: BLE001 -- report a failed diagnostic, never crash.
                index_checks.append(
                    _check("freshness.summary", "FAIL", f"Freshness summary failed: {exc}")
                )
        else:
            reason = (
                "kb_path is inaccessible"
                if not kb_accessible
                else "index metadata unavailable"
            )
            index_checks.append(_check("freshness.summary", "SKIP", f"Skipped because {reason}"))
        operational.extend(
            [
                _write_lock_check(current, Path(config.write_lock_path)),
                _log_error_check(
                    local_data_home(current.environ) / "logs",
                    current.error_line_limit,
                ),
            ]
        )

    index_checks.append(_reranker_check(current))
    clients = _client_checks(current)
    handshake_allowed = Path(current.python_exe).is_file() and (
        current.script_dir / "server.py"
    ).is_file()
    handshake = [_handshake_check(current, handshake_allowed)]
    sections = [
        _section("system", "System", system),
        _section("configuration", "Configuration and knowledge base", configuration),
        _section("data", "Data home and migration", data_checks),
        _section("index", "Index and freshness", index_checks),
        _section("operations", "Write lock and recent errors", operational),
        _section("clients", "Client layers", clients),
        _section(
            "mcp",
            "Global MCP handshake (20s timeout; normal warmup may take ~15s)",
            handshake,
        ),
    ]
    all_checks = [check for section in sections for check in section["checks"]]
    counts = Counter(check["status"] for check in all_checks)
    summary = {
        "counts": {status: counts.get(status, 0) for status in DOCTOR_STATUSES},
        "failures": counts.get("FAIL", 0),
        "exit_code": 0 if counts.get("FAIL", 0) == 0 else 1,
    }
    return {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "tool": "cortex doctor",
        "version": __version__,
        "read_only": True,
        "generated_at_utc": current.now().astimezone(timezone.utc).isoformat(),
        "summary": summary,
        "sections": sections,
    }


def render_text(report: Mapping[str, Any]) -> str:
    """Render the stable report for copy/paste into a support ticket."""
    lines = [f"Cortex Doctor v{report['version']} (strictly read-only)", ""]
    for section in report["sections"]:
        lines.append(f"## {section['title']}")
        for check in section["checks"]:
            lines.append(f"[{check['status']}] {check['id']}: {check['message']}")
            if check["id"] == "logs.recent_errors":
                for error_line in check["details"].get("lines", []):
                    lines.append(f"    {error_line}")
        lines.append("")
    counts = report["summary"]["counts"]
    lines.append(
        "Summary: " + " ".join(f"{status}={counts[status]}" for status in DOCTOR_STATUSES)
    )
    lines.append(f"Exit code: {report['summary']['exit_code']}")
    return "\n".join(lines)


def render_json(report: Mapping[str, Any]) -> str:
    """Render the stable machine-readable schema."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone doctor command and return its support exit code."""
    parser = argparse.ArgumentParser(prog="cortex doctor")
    parser.add_argument("--json", action="store_true", help="Emit stable JSON")
    parser.add_argument("--python", default=None, help="Python executable to inspect")
    args = parser.parse_args(argv)
    report = run_doctor(default_context(python_exe=args.python))
    print(render_json(report) if args.json else render_text(report))
    return int(report["summary"]["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
