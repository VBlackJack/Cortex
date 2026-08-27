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
"""Atomic compare-and-swap mutation for the Confluence TOML configuration."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import filelock

from confluence_writer.config import (
    ConfluenceSettings,
    parse_confluence_settings_bytes,
)
from confluence_writer.constants import (
    CONFIG_BACKUP_SUFFIX,
    CONFIG_MUTATION_LOCK_SUFFIX,
    DEFAULT_CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS,
)

_LOG = logging.getLogger("cortex.confluence_writer.config_mutation")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ConfluenceConfigMutationError(RuntimeError):
    """Raised when a validated configuration cannot be safely persisted."""


class ConfluenceConfigConflictError(ConfluenceConfigMutationError):
    """Raised when the current file no longer matches the caller snapshot."""


class ConfluenceConfigLockedError(ConfluenceConfigMutationError):
    """Raised when another process owns the configuration mutation lock."""


@dataclass(frozen=True)
class ConfluenceConfigSnapshot:
    """Exact file bytes, their CAS hash, and the model validated from those bytes."""

    content: bytes
    content_hash: str
    settings: ConfluenceSettings


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_datetime(value: datetime) -> str:
    return _toml_string(value.isoformat())


def render_confluence_settings(settings: ConfluenceSettings) -> bytes:
    """Serialize validated schema v1, v2, or v3 settings as deterministic UTF-8 TOML."""
    lines = [f"schema_version = {settings.schema_version}"]
    if settings.base_url is not None:
        lines.append(f"base_url = {_toml_string(settings.base_url)}")
    lines.append(f"credential_target = {_toml_string(settings.credential_target)}")
    if settings.auth_expires_at is not None:
        lines.append(f"auth_expires_at = {_toml_datetime(settings.auth_expires_at)}")
    if settings.console_path is not None:
        lines.append(f"console_path = {_toml_string(str(settings.console_path))}")
    lines.extend(
        (
            f"max_attachment_size_mb = {settings.max_attachment_size_mb}",
            f"failure_threshold = {settings.failure_threshold!r}",
        )
    )
    for mapping in settings.spaces:
        lines.extend(
            (
                "",
                "[[spaces]]",
                f"space_key = {_toml_string(mapping.space_key)}",
                f"target = {_toml_string(mapping.target)}",
                f"classification = {_toml_string(mapping.classification)}",
            )
        )
        if settings.schema_version == 1:
            continue
        lines.append(f"selection = {_toml_string(mapping.effective_selection)}")
        if mapping.effective_selection not in {"pages", "subtree"}:
            continue
        if not mapping.selected_page_ids:
            lines.append("pages = []")
            continue
        for page_id in mapping.selected_page_ids:
            lines.extend(("", "[[spaces.pages]]", f"page_id = {_toml_string(page_id)}"))
    return ("\n".join(lines) + "\n").encode("utf-8")


def read_confluence_config_snapshot(path: Path) -> ConfluenceConfigSnapshot:
    """Read once and derive both the raw-byte CAS hash and validated settings."""
    source = Path(path)
    content = source.read_bytes()
    return _snapshot(content, source=source)


def confluence_config_mutation_lock_path(path: Path) -> Path:
    """Return the dedicated inter-process mutation lock beside the TOML file."""
    target = Path(path)
    return target.with_name(target.name + CONFIG_MUTATION_LOCK_SUFFIX)


def confluence_config_backup_path(path: Path) -> Path:
    """Return the exact previous-byte backup path beside the TOML file."""
    target = Path(path)
    return target.with_name(target.name + CONFIG_BACKUP_SUFFIX)


def _snapshot(content: bytes, *, source: Path) -> ConfluenceConfigSnapshot:
    return ConfluenceConfigSnapshot(
        content=content,
        content_hash=hashlib.sha256(content).hexdigest(),
        settings=parse_confluence_settings_bytes(content, source=source),
    )


def _validate_expected_hash(expected_hash: str | None) -> None:
    if expected_hash is not None and not _SHA256.fullmatch(expected_hash):
        raise ValueError("expected_hash must be a lowercase SHA-256 hexadecimal value")


def _validate_timeout(timeout_seconds: float) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0.0:
        raise ValueError("timeout_seconds must be a finite non-negative value")


def _write_temporary(path: Path, content: bytes, *, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{path.name}.",
        suffix=suffix,
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary_path


def _assert_cas(current: bytes | None, expected_hash: str | None) -> None:
    if expected_hash is None:
        if current is not None:
            raise ConfluenceConfigConflictError(
                "Confluence configuration appeared after the caller snapshot."
            )
        return
    if current is None:
        raise ConfluenceConfigConflictError(
            "Confluence configuration disappeared after the caller snapshot."
        )
    if hashlib.sha256(current).hexdigest() != expected_hash:
        raise ConfluenceConfigConflictError(
            "Confluence configuration changed after the caller snapshot."
        )


def write_confluence_config_cas(
    path: Path,
    settings: ConfluenceSettings,
    *,
    expected_hash: str | None,
    timeout_seconds: float = DEFAULT_CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS,
) -> ConfluenceConfigSnapshot:
    """Atomically create or replace a config when its exact bytes still match."""
    _validate_expected_hash(expected_hash)
    _validate_timeout(timeout_seconds)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = confluence_config_mutation_lock_path(target)
    lock = filelock.FileLock(lock_path, timeout=timeout_seconds)
    config_temporary: Path | None = None
    backup_temporary: Path | None = None
    try:
        with lock.acquire(timeout=timeout_seconds):
            current = target.read_bytes() if target.exists() else None
            _assert_cas(current, expected_hash)
            rendered = render_confluence_settings(settings)
            config_temporary = _write_temporary(target, rendered, suffix=".tmp")
            validated = _snapshot(config_temporary.read_bytes(), source=config_temporary)
            if validated.settings != settings:
                raise ConfluenceConfigMutationError(
                    "Canonical Confluence TOML did not round-trip to the requested settings."
                )
            if current is not None:
                backup = confluence_config_backup_path(target)
                backup_temporary = _write_temporary(backup, current, suffix=".tmp")
                os.replace(backup_temporary, backup)
                backup_temporary = None
            os.replace(config_temporary, target)
            config_temporary = None
            _LOG.info(
                "confluence_config_committed path=%s operation=%s",
                target,
                "create" if current is None else "update",
            )
            return validated
    except filelock.Timeout as exc:
        _LOG.warning(
            "confluence_config_lock_timeout path=%s timeout_s=%s",
            target,
            timeout_seconds,
        )
        raise ConfluenceConfigLockedError(
            "Another process is mutating the Confluence configuration."
        ) from exc
    finally:
        for temporary_path in (config_temporary, backup_temporary):
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


__all__ = [
    "ConfluenceConfigConflictError",
    "ConfluenceConfigLockedError",
    "ConfluenceConfigMutationError",
    "ConfluenceConfigSnapshot",
    "confluence_config_backup_path",
    "confluence_config_mutation_lock_path",
    "read_confluence_config_snapshot",
    "render_confluence_settings",
    "write_confluence_config_cas",
]
