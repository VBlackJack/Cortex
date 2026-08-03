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
"""Fail-closed per-document generation assembly and publication."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from ingestion.constants import (
    ACTION_ATTEMPT_IN_PROGRESS,
    DOCUMENTS_DIRECTORY_NAME,
    ERROR_ATTEMPT_IN_PROGRESS,
    ERROR_PARTIAL_FAILURE,
    ERROR_RUN_FAILED,
    ERROR_THRESHOLD_EXCEEDED,
    SCHEMA_VERSION,
)
from ingestion.models import (
    AttemptResult,
    CollectedDocument,
    DocumentRecord,
    DocumentStatus,
    GenerationAttempt,
    GenerationManifest,
    HealthCounts,
    HealthStatus,
    SourceHealth,
    TombstoneKind,
    TombstoneRecord,
)
from ingestion.storage import IngestionStorage

_LOG = logging.getLogger("cortex.ingestion.engine")


class GenerationContractError(RuntimeError):
    """Raised before publication when an attempt violates the input contract."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_document(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _copy_document(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


class GenerationEngine:
    """Build and publish source-agnostic immutable generations."""

    def __init__(self, storage: IngestionStorage) -> None:
        """Bind the engine to one source-kind storage boundary."""
        self.storage = storage

    def run(
        self,
        attempt: GenerationAttempt,
        *,
        now: datetime | None = None,
        before_pointer_switch: Callable[[], None] | None = None,
    ) -> AttemptResult:
        """Execute one attempt while preserving the previous served generation."""
        attempted_at = _utc_now() if now is None else now
        if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
            raise ValueError("now must include a UTC offset")
        previous_health = self.storage.load_health()
        previous_success = (
            previous_health.last_success_at if previous_health is not None else None
        )
        initial_counts = HealthCounts(
            seen=len(attempt.remote_seen_source_uids),
            converted=len(attempt.documents),
            failed=len(attempt.failures),
        )
        in_progress = SourceHealth(
            schema_version=SCHEMA_VERSION,
            source_kind=self.storage.source_kind,
            last_attempt_at=attempted_at,
            last_success_at=previous_success,
            remote_cursor=attempt.remote_cursor,
            auth_expires_at=attempt.auth_expires_at,
            status=HealthStatus.DEGRADED,
            error_code=ERROR_ATTEMPT_IN_PROGRESS,
            action_required=ACTION_ATTEMPT_IN_PROGRESS,
            counts=initial_counts,
        )
        self.storage.write_health(in_progress)

        failure_code = self._global_failure_code(attempt)
        if failure_code is not None:
            health = in_progress.model_copy(
                update={
                    "status": HealthStatus.ERROR,
                    "error_code": failure_code,
                    "action_required": None,
                }
            )
            self.storage.write_health(health)
            _LOG.error(
                "ingestion_attempt_refused source_kind=%s error_code=%s",
                self.storage.source_kind,
                failure_code,
            )
            return AttemptResult(published=False, generation_id=None, health=health)

        generation_id = uuid.uuid4().hex
        pending = self.storage.create_pending_generation(generation_id)
        try:
            manifest, counts = self._assemble(
                attempt,
                generation_id=generation_id,
                pending=pending,
                published_at=attempted_at,
            )
            self.storage.publish_pending_generation(
                generation_id,
                manifest,
                before_pointer_switch=before_pointer_switch,
            )
        except Exception as exc:
            self.storage.discard_pending_generation(generation_id)
            health = in_progress.model_copy(
                update={
                    "status": HealthStatus.ERROR,
                    "error_code": ERROR_RUN_FAILED,
                    "action_required": None,
                }
            )
            self.storage.write_health(health)
            _LOG.error(
                "ingestion_attempt_failed source_kind=%s generation_id=%s error_type=%s",
                self.storage.source_kind,
                generation_id,
                type(exc).__name__,
            )
            raise

        degraded = counts.failed > 0 or counts.carry_forward > 0
        health = SourceHealth(
            schema_version=SCHEMA_VERSION,
            source_kind=self.storage.source_kind,
            last_attempt_at=attempted_at,
            last_success_at=attempted_at,
            remote_cursor=attempt.remote_cursor,
            auth_expires_at=attempt.auth_expires_at,
            status=HealthStatus.DEGRADED if degraded else HealthStatus.OK,
            error_code=ERROR_PARTIAL_FAILURE if degraded else None,
            action_required=None,
            counts=counts,
        )
        self.storage.write_health(health)
        return AttemptResult(
            published=True,
            generation_id=generation_id,
            health=health,
        )

    @staticmethod
    def _global_failure_code(attempt: GenerationAttempt) -> str | None:
        if attempt.failure_threshold_exceeded:
            return ERROR_THRESHOLD_EXCEEDED
        if attempt.global_error_code is not None:
            return attempt.global_error_code
        if not attempt.enumeration_succeeded:
            return ERROR_RUN_FAILED
        if attempt.enumeration_complete and not attempt.enumeration_succeeded:
            return ERROR_RUN_FAILED
        return None

    def _assemble(
        self,
        attempt: GenerationAttempt,
        *,
        generation_id: str,
        pending: Path,
        published_at: datetime,
    ) -> tuple[GenerationManifest, HealthCounts]:
        current_id = self.storage.current_generation_id()
        current_manifest = self.storage.load_current_manifest()
        current_documents = {
            item.source_uid: item
            for item in (() if current_manifest is None else current_manifest.documents)
        }
        current_tombstones = {
            (item.kind, item.source_uid): item
            for item in (() if current_manifest is None else current_manifest.tombstones)
        }
        successful = self._unique_documents(attempt.documents)
        failed_ids = self._unique_failures(attempt)
        if set(successful) & failed_ids:
            raise GenerationContractError(
                "a source_uid cannot be both successful and failed in one attempt"
            )
        unknown_seen = (
            set(successful) | failed_ids
        ) - set(attempt.remote_seen_source_uids)
        if unknown_seen:
            raise GenerationContractError(
                "successful and failed source_uids must be present in remote_seen_source_uids"
            )

        documents: list[DocumentRecord] = []
        tombstones: list[TombstoneRecord] = []
        carry_forward = 0
        destination_root = pending / DOCUMENTS_DIRECTORY_NAME

        if attempt.source_disabled:
            prior = current_tombstones.get(
                (TombstoneKind.SOURCE, self.storage.source_kind)
            )
            tombstones.append(
                prior
                if prior is not None
                else TombstoneRecord(
                    source_uid=self.storage.source_kind,
                    kind=TombstoneKind.SOURCE,
                    disappeared_at=published_at,
                )
            )
        else:
            for source_uid, collected in sorted(successful.items()):
                content_hash = hashlib.sha256(collected.content).hexdigest()
                _write_document(destination_root / collected.path, collected.content)
                documents.append(
                    DocumentRecord(
                        source_uid=source_uid,
                        path=collected.path,
                        content_hash=content_hash,
                        status=DocumentStatus.FRESH,
                        last_success_at=published_at,
                    )
                )

            for source_uid, previous in sorted(current_documents.items()):
                if source_uid in successful:
                    continue
                if (
                    attempt.enumeration_complete
                    and source_uid not in attempt.remote_seen_source_uids
                ):
                    tombstones.append(
                        TombstoneRecord(
                            source_uid=source_uid,
                            kind=TombstoneKind.DOCUMENT,
                            disappeared_at=published_at,
                        )
                    )
                    continue
                if current_id is None:
                    raise GenerationContractError(
                        "current manifest exists without a current generation pointer"
                    )
                next_status = previous.status
                if source_uid in failed_ids or not attempt.enumeration_complete:
                    next_status = DocumentStatus.STALE
                if next_status is DocumentStatus.STALE:
                    carry_forward += 1
                _copy_document(
                    self.storage.document_path(current_id, previous.path),
                    destination_root / previous.path,
                )
                documents.append(previous.model_copy(update={"status": next_status}))

            for key, previous in sorted(
                current_tombstones.items(),
                key=lambda item: (item[0][0].value, item[0][1]),
            ):
                kind, source_uid = key
                if kind is TombstoneKind.SOURCE:
                    continue
                if source_uid in attempt.remote_seen_source_uids:
                    continue
                tombstones.append(previous)

            known_existing = set(current_documents)
            unhandled_new = (
                set(attempt.remote_seen_source_uids)
                - known_existing
                - set(successful)
                - failed_ids
            )
            if unhandled_new:
                raise GenerationContractError(
                    "new remote source_uids must be successful or failed"
                )

        documents.sort(key=lambda item: item.source_uid)
        tombstones.sort(key=lambda item: (item.kind.value, item.source_uid))
        counts = HealthCounts(
            seen=len(attempt.remote_seen_source_uids),
            converted=len(successful),
            failed=len(failed_ids),
            carry_forward=carry_forward,
            tombstones=len(tombstones),
        )
        return (
            GenerationManifest(
                schema_version=SCHEMA_VERSION,
                generation_id=generation_id,
                published_at=published_at,
                documents=tuple(documents),
                tombstones=tuple(tombstones),
            ),
            counts,
        )

    @staticmethod
    def _unique_documents(
        documents: tuple[CollectedDocument, ...],
    ) -> dict[str, CollectedDocument]:
        by_uid: dict[str, CollectedDocument] = {}
        paths: set[str] = set()
        for document in documents:
            if document.source_uid in by_uid:
                raise GenerationContractError("duplicate successful source_uid")
            if document.path in paths:
                raise GenerationContractError("duplicate successful document path")
            by_uid[document.source_uid] = document
            paths.add(document.path)
        return by_uid

    @staticmethod
    def _unique_failures(attempt: GenerationAttempt) -> set[str]:
        source_uids = {failure.source_uid for failure in attempt.failures}
        if len(source_uids) != len(attempt.failures):
            raise GenerationContractError("duplicate failed source_uid")
        return source_uids


__all__ = ["GenerationContractError", "GenerationEngine"]
