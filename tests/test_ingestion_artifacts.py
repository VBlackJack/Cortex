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
"""Backward-compatible ingestion support for document-owned artifacts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingestion.engine import GenerationEngine
from ingestion.models import CollectedArtifact, CollectedDocument, GenerationAttempt
from ingestion.storage import IngestionStorage

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def test_document_artifacts_follow_carry_forward_and_tombstone(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path, "doc", retention_generations=3)
    engine = GenerationEngine(storage)
    first = engine.run(
        GenerationAttempt(
            documents=(
                CollectedDocument(
                    source_uid="1001",
                    path="space/markdown/1001.md",
                    content=b"page\n",
                    artifacts=(
                        CollectedArtifact(
                            path="space/_attachments/1001/diagram.png",
                            content=b"png fixture\n",
                        ),
                    ),
                ),
            ),
            remote_seen_source_uids=frozenset({"1001"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW,
    )
    assert first.published

    second = engine.run(
        GenerationAttempt(
            remote_seen_source_uids=frozenset({"1001"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=1),
    )
    assert second.published
    manifest = storage.load_current_manifest()
    assert manifest is not None
    document = manifest.documents[0]
    assert document.artifacts[0].path == "space/_attachments/1001/diagram.png"
    generation_id = storage.current_generation_id()
    assert generation_id is not None
    assert storage.document_path(generation_id, document.artifacts[0].path).read_bytes() == (
        b"png fixture\n"
    )

    third = engine.run(
        GenerationAttempt(
            remote_seen_source_uids=frozenset(),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=2),
    )
    assert third.published
    manifest = storage.load_current_manifest()
    assert manifest is not None
    assert manifest.documents == ()
    assert manifest.tombstones[0].source_uid == "1001"
