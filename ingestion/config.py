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
"""Strict ingestion settings with environment over TOML over defaults."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ingestion.constants import (
    CONFIG_FILE_NAME,
    CONFIG_SCHEMA_VERSION,
    DEFAULT_AUTH_EXPIRY_WARNING_DAYS,
    DEFAULT_BACKOFF_INITIAL_SECONDS,
    DEFAULT_BACKOFF_JITTER_RATIO,
    DEFAULT_BACKOFF_MAX_SECONDS,
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    DEFAULT_RETENTION_GENERATIONS,
    DEFAULT_RETRY_ATTEMPTS,
    DEFAULT_SCHEDULE_INTERVAL_SECONDS,
    INGESTION_DIRECTORY_NAME,
)
from user_config import local_data_home, user_config_path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

_SETTING_FIELDS = {
    "schema_version",
    "data_root",
    "retention_generations",
    "auth_expiry_warning_days",
    "lock_timeout_seconds",
    "retry_attempts",
    "backoff_initial_seconds",
    "backoff_max_seconds",
    "backoff_multiplier",
    "backoff_jitter_ratio",
    "schedule_interval_seconds",
}

_ENVIRONMENT_FIELDS = {
    "CORTEX_INGESTION_DATA_ROOT": "data_root",
    "CORTEX_INGESTION_RETENTION_GENERATIONS": "retention_generations",
    "CORTEX_INGESTION_AUTH_EXPIRY_WARNING_DAYS": "auth_expiry_warning_days",
    "CORTEX_INGESTION_LOCK_TIMEOUT_SECONDS": "lock_timeout_seconds",
    "CORTEX_INGESTION_RETRY_ATTEMPTS": "retry_attempts",
    "CORTEX_INGESTION_BACKOFF_INITIAL_SECONDS": "backoff_initial_seconds",
    "CORTEX_INGESTION_BACKOFF_MAX_SECONDS": "backoff_max_seconds",
    "CORTEX_INGESTION_BACKOFF_MULTIPLIER": "backoff_multiplier",
    "CORTEX_INGESTION_BACKOFF_JITTER_RATIO": "backoff_jitter_ratio",
    "CORTEX_INGESTION_SCHEDULE_INTERVAL_SECONDS": "schedule_interval_seconds",
}


class IngestionConfigError(RuntimeError):
    """Raised when ingestion settings are unsafe or invalid."""


class IngestionSettings(BaseModel):  # type: ignore[misc]
    """Resolved source-agnostic ingestion settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    data_root: Path
    retention_generations: int = Field(default=DEFAULT_RETENTION_GENERATIONS, ge=1)
    auth_expiry_warning_days: int = Field(
        default=DEFAULT_AUTH_EXPIRY_WARNING_DAYS,
        ge=1,
    )
    lock_timeout_seconds: float = Field(default=DEFAULT_LOCK_TIMEOUT_SECONDS, ge=0.0)
    retry_attempts: int = Field(default=DEFAULT_RETRY_ATTEMPTS, ge=1)
    backoff_initial_seconds: float = Field(
        default=DEFAULT_BACKOFF_INITIAL_SECONDS,
        gt=0.0,
    )
    backoff_max_seconds: float = Field(default=DEFAULT_BACKOFF_MAX_SECONDS, gt=0.0)
    backoff_multiplier: float = Field(default=DEFAULT_BACKOFF_MULTIPLIER, ge=1.0)
    backoff_jitter_ratio: float = Field(
        default=DEFAULT_BACKOFF_JITTER_RATIO,
        ge=0.0,
        le=1.0,
    )
    schedule_interval_seconds: float = Field(
        default=DEFAULT_SCHEDULE_INTERVAL_SECONDS,
        gt=0.0,
    )


def ingestion_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the separate per-user ingestion configuration path."""
    values = os.environ if environ is None else environ
    configured = values.get("CORTEX_INGESTION_CONFIG_PATH")
    if configured and configured.strip():
        return Path(configured.strip())
    return user_config_path(values).with_name(CONFIG_FILE_NAME)


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise IngestionConfigError(
            f"Could not read valid ingestion TOML at '{path}': {exc}"
        ) from exc
    unknown = sorted(set(raw) - _SETTING_FIELDS)
    if unknown:
        raise IngestionConfigError(
            f"Unknown ingestion configuration key(s): {', '.join(unknown)}. "
            f"Configuration file: '{path}'."
        )
    version = raw.get("schema_version", CONFIG_SCHEMA_VERSION)
    if type(version) is not int or version != CONFIG_SCHEMA_VERSION:
        raise IngestionConfigError(
            f"Unsupported ingestion schema_version={version!r}; expected "
            f"{CONFIG_SCHEMA_VERSION}. Configuration file: '{path}'."
        )
    return cast(dict[str, Any], raw)


def _parse_environment_value(field: str, value: str) -> object:
    if field in {"data_root"}:
        return Path(value)
    if field in {"retention_generations", "auth_expiry_warning_days", "retry_attempts"}:
        return int(value)
    return float(value)


def load_ingestion_settings(
    *,
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> IngestionSettings:
    """Load ingestion settings using environment, TOML, then defaults."""
    values = dict(os.environ if environ is None else environ)
    config_path = ingestion_config_path(values) if path is None else Path(path)
    allowed_environment_names = set(_ENVIRONMENT_FIELDS) | {
        "CORTEX_INGESTION_CONFIG_PATH"
    }
    unknown_environment_names = sorted(
        name
        for name in values
        if name.startswith("CORTEX_INGESTION_")
        and name not in allowed_environment_names
    )
    if unknown_environment_names:
        raise IngestionConfigError(
            "Unknown ingestion environment variable(s): "
            + ", ".join(unknown_environment_names)
        )
    merged: dict[str, object] = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "data_root": local_data_home(values) / INGESTION_DIRECTORY_NAME,
    }
    merged.update(_read_toml(config_path))
    for environment_name, field in _ENVIRONMENT_FIELDS.items():
        raw = values.get(environment_name)
        if raw is None or not raw.strip():
            continue
        try:
            merged[field] = _parse_environment_value(field, raw.strip())
        except ValueError as exc:
            raise IngestionConfigError(
                f"Environment variable {environment_name} has an invalid value."
            ) from exc
    try:
        settings = cast(IngestionSettings, IngestionSettings.model_validate(merged))
    except ValidationError as exc:
        raise IngestionConfigError(
            f"Invalid ingestion configuration at '{config_path}': {exc}"
        ) from exc
    if settings.backoff_max_seconds < settings.backoff_initial_seconds:
        raise IngestionConfigError(
            "backoff_max_seconds must be greater than or equal to "
            "backoff_initial_seconds."
        )
    return settings


__all__ = [
    "IngestionConfigError",
    "IngestionSettings",
    "ingestion_config_path",
    "load_ingestion_settings",
]
