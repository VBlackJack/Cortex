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
"""Atomic compare-and-swap mutation for the Cortex user TOML configuration."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import filelock

from confluence_writer.constants import (
    CONFIG_BACKUP_SUFFIX,
    CONFIG_MUTATION_LOCK_SUFFIX,
    DEFAULT_CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS,
)
from user_config import (
    CortexConfigError,
    CortexUserConfig,
    load_user_config,
    render_user_config,
)

_LOG = logging.getLogger("cortex.user_config_mutation")
_LOG.addHandler(logging.NullHandler())
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONFIG_ENV_PREFIX = "CORTEX_"


class UserConfigMutationError(RuntimeError):
    """Raised when a validated user configuration cannot be safely persisted."""


class UserConfigConflictError(UserConfigMutationError):
    """Raised when current bytes no longer match the caller snapshot."""


class UserConfigLockedError(UserConfigMutationError):
    """Raised when another process owns the user configuration mutation lock."""


class UserConfigValidationError(UserConfigMutationError):
    """Raised when canonical TOML does not round-trip to the requested values."""


@dataclass(frozen=True)
class UserConfigSnapshot:
    """Exact bytes, raw CAS hash, and configuration validity for one read."""

    present: bool
    content: bytes | None
    content_hash: str | None
    config: CortexUserConfig | None
    error: CortexConfigError | None


@dataclass(frozen=True)
class UserConfigMutationResult:
    """Before and after snapshots plus exact mutation side effects."""

    previous: UserConfigSnapshot
    current: UserConfigSnapshot
    changed: bool
    backup_written: bool
    rebuilt_from_defaults: bool


def user_config_mutation_lock_path(path: Path) -> Path:
    """Return the dedicated inter-process mutation lock beside the TOML file."""
    target = Path(path)
    return target.with_name(target.name + CONFIG_MUTATION_LOCK_SUFFIX)


def user_config_backup_path(path: Path) -> Path:
    """Return the exact previous-byte backup path beside the TOML file."""
    target = Path(path)
    return target.with_name(target.name + CONFIG_BACKUP_SUFFIX)


def _file_environment(environ: Mapping[str, str] | None) -> dict[str, str]:
    values = dict(os.environ if environ is None else environ)
    return {key: value for key, value in values.items() if not key.startswith(_CONFIG_ENV_PREFIX)}


def read_user_config_snapshot(
    path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> UserConfigSnapshot:
    """Read raw bytes and resolve file values without runtime Cortex overrides."""
    source = Path(path)
    values = _file_environment(environ)
    if not source.exists():
        return UserConfigSnapshot(
            present=False,
            content=None,
            content_hash=None,
            config=load_user_config(path=source, environ=values),
            error=None,
        )
    content = source.read_bytes()
    try:
        config = load_user_config(path=source, environ=values)
    except CortexConfigError as exc:
        return UserConfigSnapshot(
            present=True,
            content=content,
            content_hash=hashlib.sha256(content).hexdigest(),
            config=None,
            error=exc,
        )
    return UserConfigSnapshot(
        present=True,
        content=content,
        content_hash=hashlib.sha256(content).hexdigest(),
        config=config,
        error=None,
    )


def _validate_expected_hash(expected_hash: str | None) -> None:
    if expected_hash is not None and not _SHA256.fullmatch(expected_hash):
        raise ValueError("expected_hash must be a lowercase SHA-256 hexadecimal value")


def _validate_timeout(timeout_seconds: float) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0.0:
        raise ValueError("timeout_seconds must be a finite non-negative value")


def _validate_kb_path(kb_path: str) -> str:
    normalized = kb_path.strip()
    if not normalized:
        raise ValueError("kb_path must not be empty")
    return normalized


def _assert_cas(current: bytes | None, expected_hash: str | None) -> None:
    if expected_hash is None:
        if current is not None:
            raise UserConfigConflictError("User configuration appeared after the caller snapshot.")
        return
    if current is None:
        raise UserConfigConflictError("User configuration disappeared after the caller snapshot.")
    if hashlib.sha256(current).hexdigest() != expected_hash:
        raise UserConfigConflictError("User configuration changed after the caller snapshot.")


def _load_defaults(environ: Mapping[str, str]) -> CortexUserConfig:
    with tempfile.TemporaryDirectory(prefix="cortex-user-config-defaults-") as directory:
        return load_user_config(
            path=Path(directory) / "config.toml",
            environ=environ,
        )


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


def _validate_rendered(
    path: Path,
    requested: CortexUserConfig,
    *,
    environ: Mapping[str, str],
) -> None:
    try:
        reloaded = load_user_config(path=path, environ=environ)
    except CortexConfigError as exc:
        raise UserConfigValidationError("Canonical user TOML could not be reloaded.") from exc
    if reloaded != requested:
        raise UserConfigValidationError(
            "Canonical user TOML did not round-trip to the requested configuration."
        )


def write_user_config_cas(
    path: Path,
    *,
    kb_path: str,
    expected_hash: str | None,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS,
) -> UserConfigMutationResult:
    """Create or replace user config when its exact bytes match the caller snapshot."""
    _validate_expected_hash(expected_hash)
    _validate_timeout(timeout_seconds)
    normalized_kb_path = _validate_kb_path(kb_path)
    values = _file_environment(environ)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = filelock.FileLock(
        user_config_mutation_lock_path(target),
        timeout=timeout_seconds,
    )
    config_temporary: Path | None = None
    backup_temporary: Path | None = None
    try:
        with lock.acquire(timeout=timeout_seconds):
            previous = read_user_config_snapshot(target, environ=values)
            _assert_cas(previous.content, expected_hash)
            rebuilt_from_defaults = previous.present and previous.config is None
            base = previous.config or _load_defaults(values)
            requested = replace(base, kb_path=normalized_kb_path)
            rendered = render_user_config(requested).encode("utf-8")
            if previous.content == rendered:
                return UserConfigMutationResult(
                    previous=previous,
                    current=previous,
                    changed=False,
                    backup_written=False,
                    rebuilt_from_defaults=False,
                )

            config_temporary = _write_temporary(target, rendered, suffix=".tmp")
            _validate_rendered(config_temporary, requested, environ=values)
            backup_written = previous.content is not None
            if previous.content is not None:
                backup = user_config_backup_path(target)
                backup_temporary = _write_temporary(
                    backup,
                    previous.content,
                    suffix=".tmp",
                )
                os.replace(backup_temporary, backup)
                backup_temporary = None
            os.replace(config_temporary, target)
            config_temporary = None
            current = read_user_config_snapshot(target, environ=values)
            if current.content != rendered or current.config != requested:
                raise UserConfigValidationError(
                    "Persisted user TOML did not match the validated temporary file."
                )
            _LOG.info(
                "user_config_committed path=%s operation=%s rebuilt=%s",
                target,
                "create" if previous.content is None else "update",
                rebuilt_from_defaults,
            )
            return UserConfigMutationResult(
                previous=previous,
                current=current,
                changed=True,
                backup_written=backup_written,
                rebuilt_from_defaults=rebuilt_from_defaults,
            )
    except filelock.Timeout as exc:
        _LOG.warning(
            "user_config_lock_timeout path=%s timeout_s=%s",
            target,
            timeout_seconds,
        )
        raise UserConfigLockedError("Another process is mutating the user configuration.") from exc
    finally:
        for temporary_path in (config_temporary, backup_temporary):
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


__all__ = [
    "UserConfigConflictError",
    "UserConfigLockedError",
    "UserConfigMutationError",
    "UserConfigMutationResult",
    "UserConfigSnapshot",
    "UserConfigValidationError",
    "read_user_config_snapshot",
    "user_config_backup_path",
    "user_config_mutation_lock_path",
    "write_user_config_cas",
]
