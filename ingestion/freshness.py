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
"""Combine remote-source health with the existing content-hash report."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingestion.constants import HEALTH_FILE_NAME
from ingestion.models import DocumentStatus, HealthStatus
from ingestion.storage import IngestionStorage, IngestionStorageError

_SEVERITY = {
    HealthStatus.OK.value: 0,
    HealthStatus.DEGRADED.value: 1,
    HealthStatus.ERROR.value: 2,
}


def _index_status(report: dict[str, Any]) -> HealthStatus:
    summary = report.get("summary", {})
    if not isinstance(summary, dict) or "error" in report:
        return HealthStatus.ERROR
    if int(summary.get("error", 0)) > 0:
        return HealthStatus.ERROR
    degraded_labels = {"stale", "missing", "unknown", "unindexed"}
    if any(int(summary.get(label, 0)) > 0 for label in degraded_labels):
        return HealthStatus.DEGRADED
    return HealthStatus.OK


def _source_directories(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / HEALTH_FILE_NAME).is_file()
    )


def augment_freshness_report(
    report: dict[str, Any],
    *,
    ingestion_root: Path,
    include_entries: bool,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Add the worst of remote health and content-hash freshness when available."""
    directories = _source_directories(Path(ingestion_root))
    if not directories:
        return report
    observed_at = datetime.now(timezone.utc) if checked_at is None else checked_at
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("checked_at must include a UTC offset")

    sources: list[dict[str, Any]] = []
    carry_forward_documents: list[dict[str, str]] = []
    source_status = HealthStatus.OK
    for directory in directories:
        storage = IngestionStorage(ingestion_root, directory.name, retention_generations=1)
        try:
            health = storage.load_health()
            manifest = storage.load_current_manifest()
        except IngestionStorageError:
            sources.append(
                {
                    "source_kind": directory.name,
                    "status": HealthStatus.ERROR.value,
                    "last_attempt_at": None,
                    "last_success_at": None,
                    "error_code": "invalid_source_state",
                }
            )
            source_status = HealthStatus.ERROR
            continue
        if health is None:
            continue
        if _SEVERITY[health.status.value] > _SEVERITY[source_status.value]:
            source_status = health.status
        sources.append(
            {
                "source_kind": health.source_kind,
                "status": health.status.value,
                "last_attempt_at": health.last_attempt_at.isoformat(),
                "last_success_at": (
                    None
                    if health.last_success_at is None
                    else health.last_success_at.isoformat()
                ),
                "auth_expires_at": (
                    None
                    if health.auth_expires_at is None
                    else health.auth_expires_at.isoformat()
                ),
                "error_code": health.error_code,
                "carry_forward": health.counts.carry_forward,
            }
        )
        if manifest is not None:
            carry_forward_documents.extend(
                {
                    "source_kind": health.source_kind,
                    "source_uid": document.source_uid,
                    "path": document.path,
                    "status": document.status.value,
                    "last_success_at": document.last_success_at.isoformat(),
                }
                for document in manifest.documents
                if document.status is DocumentStatus.STALE
            )

    index_status = _index_status(report)
    worst = (
        source_status
        if _SEVERITY[source_status.value] >= _SEVERITY[index_status.value]
        else index_status
    )
    combined: dict[str, Any] = {
        "schema_version": 1,
        "status": worst.value,
        "source_stage": {
            "status": source_status.value,
            "sources": sources,
        },
        "index_stage": {
            "status": index_status.value,
            "checked_at": observed_at.isoformat(),
        },
        "carry_forward": {
            "count": len(carry_forward_documents),
        },
    }
    if include_entries:
        combined["carry_forward"]["documents"] = carry_forward_documents
    return {**report, "two_stage_freshness": combined}


__all__ = ["augment_freshness_report"]
