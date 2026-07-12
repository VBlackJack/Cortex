# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Strict per-user configuration loading and atomic initialization."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

SCHEMA_VERSION = 1
DEFAULT_INCLUDED_SECTIONS = frozenset(
    {"knowledge", "operations", "projects", "sources", "_memory", "_drafts"}
)
DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".datacron",
        "_archive",
        "_trash",
        "_attachments",
        "zzz_Corbeille",
        "_inbox",
        "_journal",
    }
)
DEFAULT_EXCLUDE_FILES = frozenset({"00_INDEX.md"})
DEFAULT_MAX_MARKDOWN_FILE_SIZE_BYTES = 1_000_000
DEFAULT_MAX_PDF_SIZE_BYTES = 50_000_000
DEFAULT_WRITE_LOCK_TIMEOUT_SECONDS = 30.0

_ALLOWED_KEYS = {
    "schema_version",
    "kb_path",
    "chroma_path",
    "included_sections",
    "excluded_dirs",
    "exclude_files",
    "max_markdown_file_size_bytes",
    "max_pdf_size_bytes",
    "write_lock_path",
    "write_lock_timeout_seconds",
}


class CortexConfigError(RuntimeError):
    """Raised when user configuration is missing, invalid or unsupported."""


@dataclass(frozen=True)
class CortexUserConfig:
    """Resolved configuration after defaults, TOML and environment overrides."""

    schema_version: int
    kb_path: str | None
    chroma_path: str
    included_sections: frozenset[str]
    excluded_dirs: frozenset[str]
    exclude_files: frozenset[str]
    max_markdown_file_size_bytes: int
    max_pdf_size_bytes: int
    write_lock_path: str
    write_lock_timeout_seconds: float


def user_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the platform user configuration path."""
    values = os.environ if environ is None else environ
    appdata = values.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "Cortex" / "config.toml"


def local_data_home(environ: Mapping[str, str] | None = None) -> Path:
    """Return the non-roaming per-user home for Cortex's generated data."""
    values = os.environ if environ is None else environ
    local_appdata = values.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "Cortex"
    user_profile = values.get("USERPROFILE")
    if os.name == "nt" and user_profile:
        return Path(user_profile) / "AppData" / "Local" / "Cortex"
    xdg_data_home = values.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "Cortex"
    home = Path(values["HOME"]) if values.get("HOME") else Path.home()
    return home / ".local" / "share" / "Cortex"


def _error(message: str, path: Path) -> CortexConfigError:
    return CortexConfigError(f"{message} Configuration file: '{path}'.")


def _require_exact_type(
    data: dict[str, Any], key: str, expected: type, path: Path
) -> Any:
    value = data[key]
    if type(value) is not expected:
        raise _error(
            f"Invalid type for '{key}': expected {expected.__name__}, "
            f"got {type(value).__name__}.",
            path,
        )
    return value


def _string_list(data: dict[str, Any], key: str, path: Path) -> frozenset[str]:
    value = _require_exact_type(data, key, list, path)
    if any(type(item) is not str or not item for item in value):
        raise _error(f"'{key}' must contain only non-empty strings.", path)
    return frozenset(value)


def _positive_int(data: dict[str, Any], key: str, path: Path) -> int:
    value = _require_exact_type(data, key, int, path)
    if value <= 0:
        raise _error(f"'{key}' must be greater than zero.", path)
    return value


def _positive_number(data: dict[str, Any], key: str, path: Path) -> float:
    value = data[key]
    if type(value) not in {int, float} or value <= 0:
        raise _error(f"'{key}' must be a positive number.", path)
    return float(value)


def _non_empty_string(data: dict[str, Any], key: str, path: Path) -> str:
    value = _require_exact_type(data, key, str, path).strip()
    if not value:
        raise _error(f"'{key}' must not be empty.", path)
    return value


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise _error(f"Could not read valid TOML: {exc}", path) from exc
    unknown = sorted(set(data) - _ALLOWED_KEYS)
    if unknown:
        raise _error(f"Unknown configuration key(s): {', '.join(unknown)}.", path)
    if "schema_version" not in data:
        raise _error("Missing required 'schema_version'.", path)
    version = _require_exact_type(data, "schema_version", int, path)
    if version > SCHEMA_VERSION:
        raise _error(
            f"Unsupported future schema_version={version}; this Cortex supports "
            f"schema_version={SCHEMA_VERSION}. Upgrade Cortex before continuing.",
            path,
        )
    if version != SCHEMA_VERSION:
        raise _error(
            f"Unsupported schema_version={version}; expected {SCHEMA_VERSION}.", path
        )
    return data


def _environment_int(
    environ: Mapping[str, str], key: str, path: Path
) -> int | None:
    raw = environ.get(key)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise _error(f"Environment variable {key} must be an integer.", path) from exc
    if value <= 0:
        raise _error(f"Environment variable {key} must be greater than zero.", path)
    return value


def _environment_float(
    environ: Mapping[str, str], key: str, path: Path
) -> float | None:
    raw = environ.get(key)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise _error(f"Environment variable {key} must be a number.", path) from exc
    if value <= 0:
        raise _error(f"Environment variable {key} must be greater than zero.", path)
    return value


def load_user_config(
    *,
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    script_dir: Path | None = None,
) -> CortexUserConfig:
    """Load strict TOML with environment > file > default precedence."""
    values = dict(os.environ if environ is None else environ)
    config_path = user_config_path(values) if path is None else Path(path)
    data = _read_toml(config_path)
    data_home = local_data_home(values)

    kb_path = (
        _non_empty_string(data, "kb_path", config_path) if "kb_path" in data else None
    )
    chroma_path = (
        _non_empty_string(data, "chroma_path", config_path)
        if "chroma_path" in data
        else str(data_home / "chroma_db")
    )
    included_sections = (
        _string_list(data, "included_sections", config_path)
        if "included_sections" in data
        else DEFAULT_INCLUDED_SECTIONS
    )
    excluded_dirs = (
        _string_list(data, "excluded_dirs", config_path)
        if "excluded_dirs" in data
        else DEFAULT_EXCLUDED_DIRS
    )
    exclude_files = (
        _string_list(data, "exclude_files", config_path)
        if "exclude_files" in data
        else DEFAULT_EXCLUDE_FILES
    )
    max_markdown = (
        _positive_int(data, "max_markdown_file_size_bytes", config_path)
        if "max_markdown_file_size_bytes" in data
        else DEFAULT_MAX_MARKDOWN_FILE_SIZE_BYTES
    )
    max_pdf = (
        _positive_int(data, "max_pdf_size_bytes", config_path)
        if "max_pdf_size_bytes" in data
        else DEFAULT_MAX_PDF_SIZE_BYTES
    )
    write_lock_path = str(data_home / "chroma_db.write.lock")
    if "write_lock_path" in data:
        write_lock_path = _non_empty_string(data, "write_lock_path", config_path)
    write_lock_timeout = (
        _positive_number(data, "write_lock_timeout_seconds", config_path)
        if "write_lock_timeout_seconds" in data
        else DEFAULT_WRITE_LOCK_TIMEOUT_SECONDS
    )

    env_kb_path = values.get("CORTEX_KB_PATH", "").strip().strip('"')
    if env_kb_path:
        kb_path = env_kb_path
    env_lock_path = values.get("CORTEX_WRITE_LOCK_PATH", "").strip().strip('"')
    if env_lock_path:
        write_lock_path = env_lock_path
    env_max_markdown = _environment_int(
        values,
        "CORTEX_MAX_MARKDOWN_FILE_SIZE_BYTES",
        config_path,
    )
    if env_max_markdown is not None:
        max_markdown = env_max_markdown
    env_lock_timeout = _environment_float(
        values, "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS", config_path
    )
    if env_lock_timeout is not None:
        write_lock_timeout = env_lock_timeout

    return CortexUserConfig(
        schema_version=SCHEMA_VERSION,
        kb_path=kb_path,
        chroma_path=chroma_path,
        included_sections=included_sections,
        excluded_dirs=excluded_dirs,
        exclude_files=exclude_files,
        max_markdown_file_size_bytes=max_markdown,
        max_pdf_size_bytes=max_pdf,
        write_lock_path=write_lock_path,
        write_lock_timeout_seconds=write_lock_timeout,
    )


def require_kb_path(value: str | None, *, config_path: Path | None = None) -> str:
    """Return a configured KB path or raise an actionable typed error."""
    if value:
        return value
    path = user_config_path() if config_path is None else config_path
    raise _error(
        "Missing required 'kb_path'. Set CORTEX_KB_PATH or run "
        "`python setup_config.py --init`.",
        path,
    )


def render_user_config(config: CortexUserConfig) -> str:
    """Serialize schema v1 using TOML-compatible JSON string/list literals."""
    lines = [
        f"schema_version = {SCHEMA_VERSION}",
        f"kb_path = {json.dumps(require_kb_path(config.kb_path))}",
        f"chroma_path = {json.dumps(config.chroma_path)}",
        "included_sections = " + json.dumps(sorted(config.included_sections)),
        "excluded_dirs = " + json.dumps(sorted(config.excluded_dirs)),
        "exclude_files = " + json.dumps(sorted(config.exclude_files)),
        f"max_markdown_file_size_bytes = {config.max_markdown_file_size_bytes}",
        f"max_pdf_size_bytes = {config.max_pdf_size_bytes}",
        f"write_lock_path = {json.dumps(config.write_lock_path)}",
        f"write_lock_timeout_seconds = {config.write_lock_timeout_seconds:g}",
    ]
    return "\n".join(lines) + "\n"


def write_user_config_atomic(path: Path, config: CortexUserConfig) -> bool:
    """Create config atomically; return False without writing when it exists."""
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(render_user_config(config))
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            return False
        os.replace(temporary_path, path)
        return True
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
