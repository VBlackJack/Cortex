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
"""MCP proof for worst-of-two-stage freshness with source dates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import server
from ingestion.config import IngestionSettings
from ingestion.engine import GenerationEngine
from ingestion.models import (
    CollectedDocument,
    DocumentFailure,
    GenerationAttempt,
    HealthCounts,
    HealthStatus,
    SourceHealth,
)
from ingestion.storage import IngestionStorage

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _prepare_stale_source(root: Path) -> IngestionStorage:
    storage = IngestionStorage(root, "doc", retention_generations=2)
    engine = GenerationEngine(storage)
    engine.run(
        GenerationAttempt(
            documents=(
                CollectedDocument(
                    source_uid="document-1",
                    path="published/document-1.md",
                    content=b"fixture content\n",
                ),
            ),
            remote_seen_source_uids=frozenset({"document-1"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW,
    )
    engine.run(
        GenerationAttempt(
            failures=(DocumentFailure(source_uid="document-1", error_code="conversion_failed"),),
            remote_seen_source_uids=frozenset({"document-1"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=1),
    )
    return storage


def test_mcp_exposes_worst_stage_dates_and_carry_forward(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _prepare_stale_source(root)
    settings = IngestionSettings(data_root=root)
    monkeypatch.setattr(server, "load_ingestion_settings", lambda: settings)
    monkeypatch.setattr(server, "get_collection", object)
    monkeypatch.setattr(
        server,
        "cortex_ingestion_index_freshness_report",
        lambda *_args, **_kwargs: {"status": "unavailable"},
    )
    monkeypatch.setattr(
        server,
        "cortex_freshness_report",
        lambda *_args, **_kwargs: {"summary": {"fresh": 1}},
    )

    response = server.cortex_freshness(include_entries=True)

    combined = response["two_stage_freshness"]
    assert combined["status"] == "degraded"
    assert combined["source_stage"]["status"] == "degraded"
    assert combined["index_stage"]["status"] == "ok"
    assert combined["index_stage"]["checked_at"]
    assert combined["source_stage"]["sources"][0]["last_attempt_at"]
    assert combined["source_stage"]["sources"][0]["last_success_at"]
    assert combined["carry_forward"]["count"] == 1
    assert combined["carry_forward"]["documents"] == [
        {
            "source_kind": "doc",
            "source_uid": "document-1",
            "path": "published/document-1.md",
            "status": "stale",
            "last_success_at": _NOW.isoformat(),
        }
    ]


def test_mcp_selects_source_error_over_degraded_hash_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    storage = _prepare_stale_source(root)
    storage.write_health(
        SourceHealth(
            schema_version=1,
            source_kind="doc",
            last_attempt_at=_NOW + timedelta(hours=2),
            last_success_at=_NOW + timedelta(hours=1),
            remote_cursor=None,
            auth_expires_at=None,
            status=HealthStatus.ERROR,
            error_code="remote_unavailable",
            action_required=None,
            counts=HealthCounts(),
        )
    )
    monkeypatch.setattr(
        server,
        "load_ingestion_settings",
        lambda: IngestionSettings(data_root=root),
    )
    monkeypatch.setattr(server, "get_collection", object)
    monkeypatch.setattr(
        server,
        "cortex_ingestion_index_freshness_report",
        lambda *_args, **_kwargs: {"status": "unavailable"},
    )
    monkeypatch.setattr(
        server,
        "cortex_freshness_report",
        lambda *_args, **_kwargs: {"summary": {"stale": 1}},
    )

    response = server.cortex_freshness()

    combined = response["two_stage_freshness"]
    assert combined["status"] == "error"
    assert combined["source_stage"]["status"] == "error"
    assert combined["index_stage"]["status"] == "degraded"


def test_mcp_exposes_dedicated_document_generation_index_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _prepare_stale_source(root)
    monkeypatch.setattr(
        server,
        "load_ingestion_settings",
        lambda: IngestionSettings(data_root=root),
    )
    monkeypatch.setattr(server, "get_collection", object)
    monkeypatch.setattr(
        server,
        "cortex_freshness_report",
        lambda *_args, **_kwargs: {"summary": {"fresh": 1}},
    )
    monkeypatch.setattr(
        server,
        "cortex_ingestion_index_freshness_report",
        lambda *_args, **_kwargs: {
            "source_kind": "doc",
            "generation_id": "generation-current",
            "status": "degraded",
            "summary": {"unindexed": 2},
            "read_only": True,
        },
    )

    response = server.cortex_freshness()

    assert response["ingestion_index"]["generation_id"] == "generation-current"
    assert response["two_stage_freshness"]["index_stage"]["ingestion_sources"] == [
        {
            "source_kind": "doc",
            "generation_id": "generation-current",
            "status": "degraded",
            "summary": {"unindexed": 2},
        }
    ]
    assert response["two_stage_freshness"]["index_stage"]["status"] == "degraded"
