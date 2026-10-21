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
from typing import Literal

from pydantic import BaseModel, ConfigDict

SYNC_CLI_CONTRACT_VERSION: Literal[1] = 1
SYNC_ERROR_SAMPLE_LIMIT = 50
SyncRecommendation = Literal[
    "retry_sync", "repair_lexical", "check_sources", "fix_configuration", "none"
]
SyncErrorKind = Literal["source", "configuration", "index"]
# Errors raised by an unreadable source file. They never damage either index,
# so a sync whose only errors are these is partial, not failed.
SOURCE_ERROR_CODES = frozenset({"extraction_failed"})
# Errors raised by a configured location or setting that does not resolve.
# They leave both indexes untouched and no retry can fix them; only the
# configuration can.
CONFIGURATION_ERROR_CODES = frozenset(
    {"invalid_configuration", "invalid_section", "section_unavailable", "vault_unavailable"}
)
# One sentence per recommendation for the human-mode console.
SYNC_RECOMMENDATION_ADVICE: Mapping[SyncRecommendation, str] = {
    "retry_sync": "Run the sync again once the reported index error is resolved.",
    "repair_lexical": "Repair the lexical index by running the sync again.",
    "check_sources": "Check the listed source files: Cortex could not read them.",
    "fix_configuration": (
        "Fix the configured knowledge-base path, section root or setting listed in the errors."
    ),
    "none": "No action is needed.",
}


def classify_sync_error(code: str) -> SyncErrorKind:
    """Return the internal kind of one sync error code.

    Unknown codes are treated as index errors, the conservative reading: it
    keeps the historical status and recommends a retry.
    """
    if code in SOURCE_ERROR_CODES:
        return "source"
    if code in CONFIGURATION_ERROR_CODES:
        return "configuration"
    return "index"


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
    empty_files: int
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
            empty_files=stats["empty_files"],
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
            "empty_files": self.empty_files,
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

    contract_version: Literal[1] = SYNC_CLI_CONTRACT_VERSION
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
    recommendation: SyncRecommendation


def build_sync_report(
    *,
    counters: Mapping[str, int],
    scope: SyncScope,
    ingestion: SyncIngestion,
    indexes: SyncIndexes,
    errors: list[SyncError],
) -> SyncReport:
    """Derive status and recommendations from exact synchronization facts.

    Each error code has one kind (see ``classify_sync_error``), and the most
    serious kind present decides: index over configuration over source.

    - Index kind, or any index reported unhealthy: ``failed`` when nothing was
      published or removed, otherwise ``partial``; ``repair_lexical`` when the
      lexical index is unhealthy, otherwise ``retry_sync``.
    - Configuration kind (no index error, both indexes ``ok``): ``partial`` and
      ``fix_configuration``; retrying cannot resolve a missing root.
    - Source kind only (both indexes ``ok``): ``partial`` and ``check_sources``.
    - No error and both indexes ``ok``: ``succeeded`` and ``none``.
    """
    counter_model = SyncCounters.from_stats(counters)
    changed = (
        counter_model.published_files
        + counter_model.removed_files
        + counter_model.added_chunks
        + counter_model.deleted_chunks
        > 0
    )
    successful_mutations = counter_model.published_files + counter_model.removed_files
    # Error samples are bounded, as is the index health derived from them; an
    # unsampled index error would already have marked an index unhealthy.
    kinds = {classify_sync_error(error.code) for error in errors}
    indexes_healthy = indexes.chroma == "ok" and indexes.lexical == "ok"
    non_index_errors_only = (
        counter_model.errors > 0 and bool(errors) and "index" not in kinds and indexes_healthy
    )
    status: Literal["succeeded", "partial", "failed"]
    recommendation: SyncRecommendation
    if non_index_errors_only:
        status = "partial"
    elif successful_mutations == 0 and counter_model.errors > 0:
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
    elif non_index_errors_only and "configuration" in kinds:
        recommendation = "fix_configuration"
    elif non_index_errors_only:
        # The error samples name the unreadable sources; retrying cannot help.
        recommendation = "check_sources"
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
            empty_files=0,
            errors=1,
        ),
        indexes=SyncIndexes(chroma=index_status, lexical=index_status),
        errors=(error,),
        errors_truncated=False,
        recommendation=recommendation,
    )


__all__ = [
    "CONFIGURATION_ERROR_CODES",
    "SOURCE_ERROR_CODES",
    "SYNC_CLI_CONTRACT_VERSION",
    "SYNC_ERROR_SAMPLE_LIMIT",
    "SYNC_RECOMMENDATION_ADVICE",
    "SyncErrorKind",
    "SyncRecommendation",
    "SyncCounters",
    "SyncError",
    "SyncIndexes",
    "SyncIngestion",
    "SyncReport",
    "SyncScope",
    "build_sync_failure_report",
    "build_sync_report",
    "classify_sync_error",
]
