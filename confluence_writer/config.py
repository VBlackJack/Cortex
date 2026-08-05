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
"""Strict Confluence settings with environment over TOML over defaults."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from confluence_writer.constants import (
    CONFIG_FILE_NAME,
    CONFIG_SCHEMA_VERSION,
    DEFAULT_ATTACHMENT_SIZE_MB,
    DEFAULT_CREDENTIAL_TARGET,
    DEFAULT_FAILURE_THRESHOLD,
    SUPPORTED_CONFIG_SCHEMA_VERSIONS,
)
from user_config import user_config_path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

_SPACE_KEY = re.compile(r"^[A-Za-z0-9._-]+$")
_PAGE_ID = re.compile(r"^[0-9]+$")
_SETTING_FIELDS = {
    "schema_version",
    "base_url",
    "credential_target",
    "auth_expires_at",
    "console_path",
    "max_attachment_size_mb",
    "failure_threshold",
    "spaces",
}
_ENVIRONMENT_FIELDS = {
    "CORTEX_CONFLUENCE_BASE_URL": "base_url",
    "CORTEX_CONFLUENCE_CREDENTIAL_TARGET": "credential_target",
    "CORTEX_CONFLUENCE_AUTH_EXPIRES_AT": "auth_expires_at",
    "CORTEX_CONFLUENCE_CONSOLE_PATH": "console_path",
    "CORTEX_CONFLUENCE_MAX_ATTACHMENT_SIZE_MB": "max_attachment_size_mb",
    "CORTEX_CONFLUENCE_FAILURE_THRESHOLD": "failure_threshold",
}


class ConfluenceConfigError(RuntimeError):
    """Raised when Confluence settings are missing, unsafe, or invalid."""


class PageSelection(BaseModel):  # type: ignore[misc]
    """One explicitly selected Confluence page identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_id: str

    @field_validator("page_id", mode="before")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_page_id(cls, value: object) -> str:
        """Require a non-empty numeric string without coercion."""
        if not isinstance(value, str) or not _PAGE_ID.fullmatch(value):
            raise ValueError("page_id must be a non-empty numeric string")
        return value


class SpaceMapping(BaseModel):  # type: ignore[misc]
    """One explicitly allowlisted Confluence space and local target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    space_key: str
    target: str
    classification: Literal["perso-non-sensible", "pro-confidentiel"]
    selection: Literal["whole_space", "pages"] | None = None
    pages: tuple[PageSelection, ...] | None = None

    @field_validator("space_key")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_space_key(cls, value: str) -> str:
        """Require a safe REST and identity component."""
        if not _SPACE_KEY.fullmatch(value):
            raise ValueError(
                "space_key must contain only letters, digits, dot, dash, or underscore"
            )
        return value

    @field_validator("target")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_target(cls, value: str) -> str:
        """Require a normalized relative POSIX target directory."""
        candidate = PurePosixPath(value)
        windows_candidate = PureWindowsPath(value)
        if (
            not value
            or value in {".", ".."}
            or candidate.is_absolute()
            or windows_candidate.is_absolute()
            or bool(windows_candidate.drive)
            or value != candidate.as_posix()
            or ".." in candidate.parts
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError("target must be a normalized relative POSIX directory")
        return value

    @model_validator(mode="after")  # type: ignore[untyped-decorator]
    def validate_page_selection(self) -> SpaceMapping:
        """Reject ambiguous whole-space configuration and duplicate page IDs."""
        if self.selection == "whole_space" and self.pages is not None:
            raise ValueError("selection='whole_space' must not include a pages table")
        if self.pages is not None:
            page_ids = [page.page_id for page in self.pages]
            if len(page_ids) != len(set(page_ids)):
                raise ValueError("pages must not contain duplicate page_id values")
        return self

    @property
    def effective_selection(self) -> Literal["whole_space", "pages"]:
        """Resolve legacy schema v1 mappings to whole-space collection."""
        return "whole_space" if self.selection is None else self.selection

    @property
    def selected_page_ids(self) -> tuple[str, ...]:
        """Return configured page IDs, including the legal empty selection."""
        return () if self.pages is None else tuple(page.page_id for page in self.pages)


class ConfluenceSettings(BaseModel):  # type: ignore[misc]
    """Resolved writer settings without secret material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2] = 1
    base_url: str | None = None
    credential_target: str = DEFAULT_CREDENTIAL_TARGET
    auth_expires_at: datetime | None = None
    console_path: Path | None = None
    max_attachment_size_mb: int = Field(default=DEFAULT_ATTACHMENT_SIZE_MB, ge=1)
    failure_threshold: float = Field(default=DEFAULT_FAILURE_THRESHOLD, ge=0.0, le=1.0)
    spaces: tuple[SpaceMapping, ...] = ()

    @field_validator("base_url")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        """Require an HTTP origin without credentials, query, or fragment."""
        if value is None:
            return None
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) URL without credentials or query")
        return normalized

    @field_validator("credential_target")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_credential_target(cls, value: str) -> str:
        """Reject empty or control-character target names."""
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("credential_target must be a non-empty printable value")
        return value

    @field_validator("auth_expires_at")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_auth_expiry(cls, value: datetime | None) -> datetime | None:
        """Require a timezone-aware declared expiration."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("auth_expires_at must include a UTC offset")
        return value

    @field_validator("spaces")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_unique_spaces(
        cls,
        value: tuple[SpaceMapping, ...],
    ) -> tuple[SpaceMapping, ...]:
        """Prevent duplicate sources or overlapping publication roots."""
        keys = [item.space_key.casefold() for item in value]
        targets = [item.target.casefold() for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("spaces must not contain duplicate space_key values")
        if len(targets) != len(set(targets)):
            raise ValueError("spaces must not contain duplicate target values")
        return value

    @model_validator(mode="after")  # type: ignore[untyped-decorator]
    def validate_schema_contract(self) -> ConfluenceSettings:
        """Keep schema v1 legacy-only and require explicit selection in schema v2."""
        if self.schema_version == 1:
            if any(
                mapping.selection is not None or mapping.pages is not None
                for mapping in self.spaces
            ):
                raise ValueError("schema_version=1 spaces must use the legacy whole-space shape")
            return self
        if any(mapping.selection is None for mapping in self.spaces):
            raise ValueError("schema_version=2 requires selection for every space")
        return self


def confluence_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the separate per-user Confluence configuration path."""
    values = os.environ if environ is None else environ
    configured = values.get("CORTEX_CONFLUENCE_CONFIG_PATH")
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
        raise ConfluenceConfigError(f"Could not read valid Confluence TOML at '{path}'.") from exc
    unknown = sorted(set(raw) - _SETTING_FIELDS)
    if unknown:
        raise ConfluenceConfigError(
            f"Unknown Confluence configuration key(s): {', '.join(unknown)}."
        )
    version = raw.get("schema_version", CONFIG_SCHEMA_VERSION)
    if type(version) is not int or version not in SUPPORTED_CONFIG_SCHEMA_VERSIONS:
        supported = ", ".join(str(item) for item in sorted(SUPPORTED_CONFIG_SCHEMA_VERSIONS))
        raise ConfluenceConfigError(
            f"Unsupported Confluence schema_version={version!r}; expected one of: {supported}."
        )
    return cast(dict[str, Any], raw)


def _parse_environment_value(field: str, value: str) -> object:
    if field == "console_path":
        return Path(value)
    if field == "max_attachment_size_mb":
        return int(value)
    if field == "failure_threshold":
        return float(value)
    return value


def load_confluence_settings(
    *,
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ConfluenceSettings:
    """Load writer settings using environment, TOML, then safe defaults."""
    values = dict(os.environ if environ is None else environ)
    config_path = confluence_config_path(values) if path is None else Path(path)
    allowed_environment_names = set(_ENVIRONMENT_FIELDS) | {"CORTEX_CONFLUENCE_CONFIG_PATH"}
    unknown_environment_names = sorted(
        name
        for name in values
        if name.startswith("CORTEX_CONFLUENCE_") and name not in allowed_environment_names
    )
    if unknown_environment_names:
        raise ConfluenceConfigError(
            "Unknown Confluence environment variable(s): " + ", ".join(unknown_environment_names)
        )
    merged: dict[str, object] = {"schema_version": CONFIG_SCHEMA_VERSION}
    merged.update(_read_toml(config_path))
    for environment_name, field in _ENVIRONMENT_FIELDS.items():
        raw = values.get(environment_name)
        if raw is None or not raw.strip():
            continue
        try:
            merged[field] = _parse_environment_value(field, raw.strip())
        except ValueError as exc:
            raise ConfluenceConfigError(
                f"Environment variable {environment_name} has an invalid value."
            ) from exc
    try:
        return cast(ConfluenceSettings, ConfluenceSettings.model_validate(merged))
    except ValidationError as exc:
        raise ConfluenceConfigError(
            f"Invalid Confluence configuration at '{config_path}': {exc}"
        ) from exc


def require_sync_settings(settings: ConfluenceSettings) -> None:
    """Fail closed before a sync when required source settings are absent."""
    missing: list[str] = []
    if settings.base_url is None:
        missing.append("base_url")
    if settings.auth_expires_at is None:
        missing.append("auth_expires_at")
    if settings.console_path is None:
        missing.append("console_path")
    if not settings.spaces:
        missing.append("spaces allowlist")
    if missing:
        raise ConfluenceConfigError("Confluence sync requires: " + ", ".join(missing))


__all__ = [
    "ConfluenceConfigError",
    "ConfluenceSettings",
    "PageSelection",
    "SpaceMapping",
    "confluence_config_path",
    "load_confluence_settings",
    "require_sync_settings",
]
