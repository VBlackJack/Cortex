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
"""Versioned machine contract for Cortex synchronization results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from config import SYNC_CLI_CONTRACT_VERSION

SYNC_ERROR_SAMPLE_LIMIT = 50


class SyncContractModel(BaseModel):  # type: ignore[misc]
    """Strict immutable base for synchronization contract models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SyncError(SyncContractModel):
    """One structured synchronization error sample."""

    code: str
    phase: str
    path: str | None


class SyncCounters(SyncContractModel):
    """Exact synchronization counters retained for backward compatibility."""

    published_files: int
    added_chunks: int
    deleted_chunks: int
    removed_files: int
    skipped_files: int
    errors: int

    @classmethod
    def from_stats(cls, stats: Mapping[str, int]) -> SyncCounters:
        """Build counters from the historical dictionary representation."""
        return cls(
            published_files=stats["published_files"],
            added_chunks=stats["added_chunks"],
            deleted_chunks=stats["deleted_chunks"],
            removed_files=stats["removed_files"],
            skipped_files=stats["skipped_files"],
            errors=stats["errors"],
        )

    def to_stats(self) -> dict[str, int]:
        """Return the historical dictionary representation."""
        return {
            "published_files": self.published_files,
            "added_chunks": self.added_chunks,
            "deleted_chunks": self.deleted_chunks,
            "removed_files": self.removed_files,
            "skipped_files": self.skipped_files,
            "errors": self.errors,
        }


class SyncIndexes(SyncContractModel):
    """Health of the vector and lexical indexes after one sync attempt."""

    chroma: Literal["ok", "degraded", "failed"]
    lexical: Literal["ok", "degraded", "failed"]


class SyncScope(SyncContractModel):
    """Resolved scope exercised by one synchronization attempt."""

    requested_section: str | None
    resolved_sections: tuple[str, ...]
    index_whole_folder: bool
    included_ingestion_documents: bool


class SyncIngestion(SyncContractModel):
    """Published ingestion generation selected by one synchronization attempt."""

    source_kind: str
    indexed_generation_id: str | None


class SyncReport(SyncContractModel):
    """Complete versioned result consumed by machine clients."""

    contract_version: Literal[1] = cast(Literal[1], SYNC_CLI_CONTRACT_VERSION)
    operation: Literal["sync"] = "sync"
    status: Literal["succeeded", "partial", "failed", "locked"]
    changed: bool
    scope: SyncScope
    ingestion: SyncIngestion
    counters: SyncCounters
    indexes: SyncIndexes
    errors: tuple[SyncError, ...]
    errors_truncated: bool
    restart_required: Literal[False] = False
    recommendation: Literal["retry_sync", "repair_lexical", "none"]


def build_sync_report(
    *,
    counters: Mapping[str, int],
    scope: SyncScope,
    ingestion: SyncIngestion,
    indexes: SyncIndexes,
    errors: list[SyncError],
) -> SyncReport:
    """Derive status and recommendations from exact synchronization facts."""
    counter_model = SyncCounters.from_stats(counters)
    changed = (
        counter_model.published_files
        + counter_model.removed_files
        + counter_model.added_chunks
        + counter_model.deleted_chunks
        > 0
    )
    successful_mutations = counter_model.published_files + counter_model.removed_files
    if successful_mutations == 0 and counter_model.errors > 0:
        status = "failed"
    elif successful_mutations > 0 and (
        counter_model.errors > 0 or indexes.chroma != "ok" or indexes.lexical != "ok"
    ):
        status = "partial"
    elif counter_model.errors == 0 and indexes.chroma == "ok" and indexes.lexical == "ok":
        status = "succeeded"
    else:
        status = "failed"

    if indexes.lexical != "ok":
        recommendation = "repair_lexical"
    elif counter_model.errors > 0:
        recommendation = "retry_sync"
    else:
        recommendation = "none"

    sampled_errors = tuple(errors[:SYNC_ERROR_SAMPLE_LIMIT])
    return SyncReport(
        status=status,
        changed=changed,
        scope=scope,
        ingestion=ingestion,
        counters=counter_model,
        indexes=indexes,
        errors=sampled_errors,
        errors_truncated=counter_model.errors > len(sampled_errors),
        recommendation=recommendation,
    )


def build_sync_failure_report(
    *,
    requested_section: str | None,
    index_whole_folder: bool,
    included_ingestion_documents: bool,
    error: SyncError,
    status: Literal["failed", "locked"],
    recommendation: Literal["retry_sync", "none"],
) -> SyncReport:
    """Build a no-mutation report for validation, lock, or exception failures."""
    index_status: Literal["ok", "failed"] = "ok" if status == "locked" else "failed"
    return SyncReport(
        status=status,
        changed=False,
        scope=SyncScope(
            requested_section=requested_section,
            resolved_sections=(),
            index_whole_folder=index_whole_folder,
            included_ingestion_documents=included_ingestion_documents,
        ),
        ingestion=SyncIngestion(source_kind="doc", indexed_generation_id=None),
        counters=SyncCounters(
            published_files=0,
            added_chunks=0,
            deleted_chunks=0,
            removed_files=0,
            skipped_files=0,
            errors=1,
        ),
        indexes=SyncIndexes(chroma=index_status, lexical=index_status),
        errors=(error,),
        errors_truncated=False,
        recommendation=recommendation,
    )


__all__ = [
    "SYNC_ERROR_SAMPLE_LIMIT",
    "SyncCounters",
    "SyncError",
    "SyncIndexes",
    "SyncIngestion",
    "SyncReport",
    "SyncScope",
    "build_sync_failure_report",
    "build_sync_report",
]
