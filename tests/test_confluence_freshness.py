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
"""MCP freshness proof for the concrete Confluence `doc` source kind."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingestion.engine import GenerationEngine
from ingestion.freshness import augment_freshness_report
from ingestion.models import CollectedDocument, DocumentFailure, GenerationAttempt
from ingestion.storage import IngestionStorage

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def test_doc_source_is_worst_stage_and_exposes_stale_carry_forward(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path, "doc", retention_generations=2)
    engine = GenerationEngine(storage)
    engine.run(
        GenerationAttempt(
            documents=(
                CollectedDocument(
                    source_uid="1001",
                    path="knowledge/confluence/markdown/1001.md",
                    content=b"fixture\n",
                ),
            ),
            remote_seen_source_uids=frozenset({"1001"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW,
    )
    engine.run(
        GenerationAttempt(
            failures=(DocumentFailure(source_uid="1001", error_code="conversion_failed"),),
            remote_seen_source_uids=frozenset({"1001"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=1),
    )

    report = augment_freshness_report(
        {"summary": {"fresh": 1}},
        ingestion_root=tmp_path,
        include_entries=True,
        checked_at=_NOW + timedelta(hours=2),
    )

    combined = report["two_stage_freshness"]
    assert combined["status"] == "degraded"
    assert combined["source_stage"]["sources"][0]["source_kind"] == "doc"
    assert combined["index_stage"]["status"] == "ok"
    assert combined["carry_forward"]["documents"][0]["status"] == "stale"
