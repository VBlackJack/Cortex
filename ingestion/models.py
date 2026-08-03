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
"""Validated persisted and in-memory ingestion contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class DocumentStatus(str, Enum):
    """Published document freshness within a generation."""

    FRESH = "fresh"
    STALE = "stale"


class TombstoneKind(str, Enum):
    """Supported deletion scopes."""

    DOCUMENT = "document"
    SOURCE = "source"


class HealthStatus(str, Enum):
    """Health severity ordered from healthy to unavailable."""

    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


class StrictModel(BaseModel):  # type: ignore[misc]
    """Base contract that rejects unknown fields and mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentRecord(StrictModel):
    """One immutable document entry in a published generation."""

    source_uid: Annotated[str, Field(min_length=1)]
    path: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=_SHA256_PATTERN)]
    status: DocumentStatus
    last_success_at: datetime

    @field_validator("path")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        """Require a normalized relative POSIX path without traversal."""
        candidate = PurePosixPath(value)
        windows_candidate = PureWindowsPath(value)
        if (
            candidate.is_absolute()
            or windows_candidate.is_absolute()
            or bool(windows_candidate.drive)
            or value != candidate.as_posix()
            or value in {".", ".."}
            or ".." in candidate.parts
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError("path must be a normalized relative POSIX path")
        return value

    @field_validator("last_success_at")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_last_success_at(cls, value: datetime) -> datetime:
        """Require an offset-aware timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("last_success_at must include a UTC offset")
        return value


class TombstoneRecord(StrictModel):
    """A document or source disappearance recorded by a generation."""

    source_uid: Annotated[str, Field(min_length=1)]
    kind: TombstoneKind
    disappeared_at: datetime

    @field_validator("disappeared_at")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_disappeared_at(cls, value: datetime) -> datetime:
        """Require an offset-aware timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("disappeared_at must include a UTC offset")
        return value


class GenerationManifest(StrictModel):
    """Immutable inventory for one published generation."""

    schema_version: Literal[1]
    generation_id: Annotated[str, Field(min_length=1)]
    published_at: datetime
    documents: tuple[DocumentRecord, ...]
    tombstones: tuple[TombstoneRecord, ...]

    @field_validator("published_at")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_published_at(cls, value: datetime) -> datetime:
        """Require an offset-aware publication timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must include a UTC offset")
        return value


class HealthCounts(StrictModel):
    """Attempt counters exposed without document content."""

    seen: Annotated[int, Field(ge=0)] = 0
    converted: Annotated[int, Field(ge=0)] = 0
    failed: Annotated[int, Field(ge=0)] = 0
    carry_forward: Annotated[int, Field(ge=0)] = 0
    tombstones: Annotated[int, Field(ge=0)] = 0


class SourceHealth(StrictModel):
    """Atomic health snapshot for the most recent source attempt."""

    schema_version: Literal[1]
    source_kind: Annotated[str, Field(min_length=1)]
    last_attempt_at: datetime
    last_success_at: datetime | None
    remote_cursor: str | None
    auth_expires_at: datetime | None
    status: HealthStatus
    error_code: str | None
    action_required: str | None
    counts: HealthCounts

    @field_validator(  # type: ignore[untyped-decorator]
        "last_attempt_at", "last_success_at", "auth_expires_at"
    )
    @classmethod
    def validate_health_timestamp(cls, value: datetime | None) -> datetime | None:
        """Require offset-aware timestamps when present."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("health timestamps must include a UTC offset")
        return value


class CurrentGenerationPointer(StrictModel):
    """Small atomically replaced pointer to the served generation."""

    schema_version: Literal[1]
    generation_id: Annotated[str, Field(min_length=1)]


class CollectedDocument(StrictModel):
    """Successful source document provided to the generation engine."""

    source_uid: Annotated[str, Field(min_length=1)]
    path: Annotated[str, Field(min_length=1)]
    content: bytes

    @field_validator("path")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_collected_path(cls, value: str) -> str:
        """Reuse the persisted path containment contract."""
        return str(DocumentRecord.validate_relative_path(value))


class DocumentFailure(StrictModel):
    """A source document that could not produce a valid artifact."""

    source_uid: Annotated[str, Field(min_length=1)]
    error_code: Annotated[str, Field(min_length=1)]


class GenerationAttempt(StrictModel):
    """Source-agnostic inputs for one fail-closed generation attempt."""

    documents: tuple[CollectedDocument, ...] = ()
    failures: tuple[DocumentFailure, ...] = ()
    remote_seen_source_uids: frozenset[str] = frozenset()
    enumeration_complete: bool
    enumeration_succeeded: bool
    remote_cursor: str | None = None
    auth_expires_at: datetime | None = None
    global_error_code: str | None = None
    failure_threshold_exceeded: bool = False
    source_disabled: bool = False

    @field_validator("auth_expires_at")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_auth_expires_at(cls, value: datetime | None) -> datetime | None:
        """Require an offset-aware credential expiration timestamp."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("auth_expires_at must include a UTC offset")
        return value


class AttemptResult(StrictModel):
    """Outcome returned without exposing document contents."""

    published: bool
    generation_id: str | None
    health: SourceHealth


__all__ = [
    "AttemptResult",
    "CollectedDocument",
    "CurrentGenerationPointer",
    "DocumentFailure",
    "DocumentRecord",
    "DocumentStatus",
    "GenerationAttempt",
    "GenerationManifest",
    "HealthCounts",
    "HealthStatus",
    "SourceHealth",
    "TombstoneKind",
    "TombstoneRecord",
]
