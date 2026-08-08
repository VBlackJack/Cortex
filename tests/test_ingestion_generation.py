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
"""Atomic generation and fail-closed ingestion tests."""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingestion.constants import ERROR_ATTEMPT_IN_PROGRESS
from ingestion.engine import GenerationEngine
from ingestion.models import (
    CollectedDocument,
    DocumentFailure,
    DocumentStatus,
    GenerationAttempt,
    HealthCounts,
    HealthStatus,
    SourceHealth,
    TombstoneKind,
)
from ingestion.storage import IngestionStorage

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
_WORKER = Path(__file__).parent / "fixtures" / "ingestion_publish_worker.py"


def _storage(tmp_path: Path, retention: int = 2) -> IngestionStorage:
    return IngestionStorage(tmp_path / "state", "fixture-source", retention)


def _document(source_uid: str, body: bytes | None = None) -> CollectedDocument:
    content = body if body is not None else f"content for {source_uid}\n".encode()
    return CollectedDocument(
        source_uid=source_uid,
        path=f"published/{source_uid}.md",
        content=content,
    )


def _publish_initial(storage: IngestionStorage) -> str:
    result = GenerationEngine(storage).run(
        GenerationAttempt(
            documents=(_document("document-1"), _document("document-2")),
            remote_seen_source_uids=frozenset({"document-1", "document-2"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW,
    )
    assert result.published
    assert result.generation_id is not None
    return result.generation_id


def _filesystem_name(path: Path) -> str:
    assert os.name == "nt"
    root = Path(path.resolve().anchor)
    filesystem = ctypes.create_unicode_buffer(32)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    success = kernel32.GetVolumeInformationW(
        str(root),
        None,
        0,
        None,
        None,
        None,
        filesystem,
        len(filesystem),
    )
    assert success
    return filesystem.value


@pytest.mark.skipif(
    os.name != "nt",
    reason="process-kill durability contract requires the Windows NTFS implementation",
)
def test_killed_process_preserves_served_generation_and_coherent_health(
    tmp_path: Path,
) -> None:
    assert _filesystem_name(tmp_path) == "NTFS"
    storage = _storage(tmp_path)
    original_id = _publish_initial(storage)
    original_manifest = storage.load_current_manifest()
    ready = tmp_path / "ready.txt"
    process = subprocess.Popen(
        [sys.executable, str(_WORKER), str(storage.root), str(ready)],
        cwd=Path(__file__).parents[1],
    )
    deadline = time.monotonic() + 10.0
    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ready.exists()
    process.kill()
    assert process.wait(timeout=10.0) != 0

    assert storage.current_generation_id() == original_id
    assert storage.load_current_manifest() == original_manifest
    health = storage.load_health()
    assert health is not None
    assert health.status is HealthStatus.DEGRADED
    assert health.error_code == ERROR_ATTEMPT_IN_PROGRESS


def test_existing_failure_is_carried_forward_stale_and_new_failure_is_absent(
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    initial_id = _publish_initial(storage)
    original = storage.document_path(initial_id, "published/document-1.md").read_bytes()

    result = GenerationEngine(storage).run(
        GenerationAttempt(
            documents=(_document("document-2", b"updated\n"),),
            failures=(
                DocumentFailure(source_uid="document-1", error_code="conversion_failed"),
                DocumentFailure(source_uid="document-new", error_code="conversion_failed"),
            ),
            remote_seen_source_uids=frozenset(
                {"document-1", "document-2", "document-new"}
            ),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=1),
    )

    assert result.generation_id is not None
    manifest = storage.load_current_manifest()
    assert manifest is not None
    by_uid = {document.source_uid: document for document in manifest.documents}
    assert by_uid["document-1"].status is DocumentStatus.STALE
    assert "document-new" not in by_uid
    assert (
        storage.document_path(
            result.generation_id,
            "published/document-1.md",
        ).read_bytes()
        == original
    )
    assert result.health.counts == HealthCounts(
        seen=3,
        converted=1,
        failed=2,
        carry_forward=1,
        tombstones=0,
    )


def test_partial_enumeration_creates_zero_tombstones_and_preserves_documents(
    tmp_path: Path,
) -> None:
    storage = _storage(tmp_path)
    _publish_initial(storage)

    GenerationEngine(storage).run(
        GenerationAttempt(
            documents=(_document("document-2", b"updated\n"),),
            remote_seen_source_uids=frozenset({"document-2"}),
            enumeration_complete=False,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=1),
    )

    manifest = storage.load_current_manifest()
    health = storage.load_health()
    assert manifest is not None
    assert health is not None
    assert manifest.tombstones == ()
    assert {document.source_uid for document in manifest.documents} == {
        "document-1",
        "document-2",
    }
    assert health.counts.tombstones == 0


def test_reappearing_document_supersedes_its_tombstone(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _publish_initial(storage)
    engine = GenerationEngine(storage)
    engine.run(
        GenerationAttempt(
            remote_seen_source_uids=frozenset({"document-2"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=1),
    )
    deleted = storage.load_current_manifest()
    assert deleted is not None
    assert any(
        item.source_uid == "document-1" and item.kind is TombstoneKind.DOCUMENT
        for item in deleted.tombstones
    )

    engine.run(
        GenerationAttempt(
            documents=(_document("document-1", b"restored\n"),),
            remote_seen_source_uids=frozenset({"document-1", "document-2"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=2),
    )
    restored = storage.load_current_manifest()
    assert restored is not None
    assert {item.source_uid for item in restored.documents} == {
        "document-1",
        "document-2",
    }
    assert all(item.source_uid != "document-1" for item in restored.tombstones)


def test_failed_or_threshold_attempt_preserves_pointer_and_manifest(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    initial_id = _publish_initial(storage)
    manifest_path = storage.generation_path(initial_id) / "manifest.json"
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    result = GenerationEngine(storage).run(
        GenerationAttempt(
            enumeration_complete=False,
            enumeration_succeeded=True,
            failure_threshold_exceeded=True,
        ),
        now=_NOW + timedelta(hours=1),
    )

    assert not result.published
    assert storage.current_generation_id() == initial_id
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == manifest_hash
    assert result.health.status is HealthStatus.ERROR


def test_source_tombstone_blocks_documents_while_disabled(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    _publish_initial(storage)
    engine = GenerationEngine(storage)
    engine.run(
        GenerationAttempt(
            documents=(_document("document-1", b"ignored\n"),),
            remote_seen_source_uids=frozenset({"document-1"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
            source_disabled=True,
        ),
        now=_NOW + timedelta(hours=1),
    )
    disabled = storage.load_current_manifest()
    assert disabled is not None
    assert disabled.documents == ()
    assert len(disabled.tombstones) == 1
    assert disabled.tombstones[0].kind is TombstoneKind.SOURCE

    engine.run(
        GenerationAttempt(
            documents=(_document("document-1", b"restored\n"),),
            remote_seen_source_uids=frozenset({"document-1"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=_NOW + timedelta(hours=2),
    )
    enabled = storage.load_current_manifest()
    assert enabled is not None
    assert [document.source_uid for document in enabled.documents] == ["document-1"]
    assert enabled.tombstones == ()


def test_retention_runs_only_after_successful_publication(tmp_path: Path) -> None:
    storage = _storage(tmp_path, retention=2)
    engine = GenerationEngine(storage)
    for index in range(3):
        engine.run(
            GenerationAttempt(
                documents=(_document("document-1", f"version {index}\n".encode()),),
                remote_seen_source_uids=frozenset({"document-1"}),
                enumeration_complete=True,
                enumeration_succeeded=True,
            ),
            now=_NOW + timedelta(hours=index),
        )
        time.sleep(0.01)
    retained = [
        path
        for path in storage.generations_root.iterdir()
        if path.is_dir() and not path.name.startswith(".pending-")
    ]
    assert len(retained) == 2


def test_health_is_independent_from_immutable_manifest(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    generation_id = _publish_initial(storage)
    manifest_path = storage.generation_path(generation_id) / "manifest.json"
    before = manifest_path.read_bytes()
    storage.write_health(
        SourceHealth(
            schema_version=1,
            source_kind="fixture-source",
            last_attempt_at=_NOW + timedelta(days=1),
            last_success_at=_NOW,
            remote_cursor=None,
            auth_expires_at=None,
            status=HealthStatus.ERROR,
            error_code="remote_unavailable",
            action_required=None,
            counts=HealthCounts(),
        )
    )
    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize(
    "path",
    ["C:/escape.md", "C:" + chr(92) + "escape.md", "../escape.md"],
)
def test_collected_document_rejects_windows_absolute_or_traversal_paths(path: str) -> None:
    with pytest.raises(ValueError, match="normalized relative POSIX path"):
        CollectedDocument(source_uid="document-1", path=path, content=b"fixture\n")
