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
"""End-to-end unit tests for incremental conversion and fail-closed publication."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import confluence_writer.converter as converter_module
import confluence_writer.writer as writer_module
from confluence_writer.config import ConfluenceSettings, PageSelection, SpaceMapping
from confluence_writer.converter import ConsoleConverter, ConverterContractError
from confluence_writer.frontmatter import parse_frontmatter
from confluence_writer.models import RemoteAttachment, RemotePage, RemotePageContent
from confluence_writer.rest import ConfluenceRestError
from confluence_writer.writer import ConfluenceWriter
from cortex_logging import configure_logging
from ingestion.credentials import SecretValue
from ingestion.engine import GenerationEngine, _degraded_error_code
from ingestion.models import DocumentStatus, GenerationAttempt, HealthStatus, TombstoneKind
from ingestion.storage import IngestionStorage

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
_FAKE_SECRET = "fixture-only-fake-secret-confluence-writer-f37c"
_RESOURCES = Path(__file__).parents[1] / "confluence_writer" / "resources"


def test_startup_sweep_removes_old_orphan_and_preserves_recent_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = tmp_path / "cortex-confluence-old"
    recent = tmp_path / "cortex-confluence-recent"
    unrelated = tmp_path / "other-workspace"
    for directory in (old, recent, unrelated):
        directory.mkdir()
    now = 2_000_000_000.0
    os.utime(old, (now - 90_000, now - 90_000))
    os.utime(recent, (now - 60, now - 60))
    monkeypatch.setattr(writer_module.tempfile, "gettempdir", lambda: str(tmp_path))

    removed = writer_module._sweep_orphaned_workspaces(now=now)

    assert removed == (old,)
    assert not old.exists()
    assert recent.is_dir()
    assert unrelated.is_dir()


class FakeRestClient:
    """Mock REST source with explicit enumeration, content, and download counters."""

    def __init__(
        self,
        pages: list[RemotePage],
        *,
        include_attachments: bool = True,
        xhtml: str | None = None,
        attachments: tuple[RemoteAttachment, ...] | None = None,
        descendants: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.pages = pages
        self.include_attachments = include_attachments
        self.xhtml = xhtml
        self.attachments = attachments
        self.descendants = descendants or {}
        self.enumeration_calls: list[str] = []
        self.subtree_calls: list[tuple[str, str]] = []
        self.page_calls: list[tuple[str, str]] = []
        self.content_calls: list[str] = []
        self.download_calls: list[str] = []

    def enumerate_pages(self, space_key: str) -> tuple[RemotePage, ...]:
        self.enumeration_calls.append(space_key)
        return tuple(page for page in self.pages if page.space_key == space_key)

    def enumerate_subtree(self, root_id: str, expected_space: str) -> tuple[RemotePage, ...]:
        self.subtree_calls.append((root_id, expected_space))
        wanted = self.descendants.get(root_id, ())
        return tuple(page for page in self.pages if page.page_id in wanted)

    def get_page(self, page_id: str, expected_space: str) -> RemotePage:
        self.page_calls.append((page_id, expected_space))
        page = next((item for item in self.pages if item.page_id == page_id), None)
        if page is None:
            raise ConfluenceRestError("Selected Confluence page was not found.")
        if page.space_key != expected_space:
            raise ConfluenceRestError("Confluence returned a page from another space.")
        return page

    def page_content(self, page_id: str) -> RemotePageContent:
        self.content_calls.append(page_id)
        if self.xhtml is not None:
            return RemotePageContent(xhtml=self.xhtml, attachments=self.attachments or ())
        if not self.include_attachments:
            return RemotePageContent(
                xhtml=f"<p>Crème brûlée {page_id}</p>",
                attachments=(),
            )
        if self.attachments is not None:
            return RemotePageContent(
                xhtml=f"<p>Crème brûlée {page_id}</p>",
                attachments=self.attachments,
            )
        attachment = RemoteAttachment(
            attachment_id=f"attachment-{page_id}",
            file_name=f"pièce-{page_id}.txt",
            media_type="text/plain",
            file_size=24,
            download_uri=f"https://confluence.example.test/download/{page_id}",
            is_drawio_source=False,
        )
        return RemotePageContent(
            xhtml=f"<p>Crème brûlée {page_id}</p>",
            attachments=(attachment,),
        )

    def download_attachment(
        self,
        attachment: RemoteAttachment,
        *,
        maximum_bytes: int,
    ) -> bytes:
        self.download_calls.append(attachment.attachment_id)
        return f"attachment payload {attachment.attachment_id}\n".encode()


class FakeConsole:
    """Frozen-contract console substitute that can leave failed-page artifacts."""

    def __init__(self, *, write_artifacts: bool = True) -> None:
        self.write_artifacts = write_artifacts
        self.failed_ids: set[str] = set()
        self.jobs: list[list[str]] = []
        self.job_payloads: list[dict[str, object]] = []
        self.xhtml_payloads: dict[str, bytes] = {}
        self.attachment_payloads: dict[str, bytes] = {}
        self.working_directories: list[Path] = []

    def __call__(self, console_path: Path, working_directory: Path) -> int:
        job = json.loads((working_directory / "job.json").read_text(encoding="utf-8"))
        self.job_payloads.append(job)
        page_ids = [page["page_id"] for page in job["pages"]]
        for page in job["pages"]:
            relative_path = Path(*page["xhtml_path"].split("/"))
            self.xhtml_payloads[page["page_id"]] = (working_directory / relative_path).read_bytes()
            for attachment in page["attachments"]:
                attachment_path = Path(*attachment["path"].split("/"))
                self.attachment_payloads[attachment["path"]] = (
                    working_directory / attachment_path
                ).read_bytes()
        self.jobs.append(page_ids)
        self.working_directories.append(working_directory)
        results: list[dict[str, object]] = []
        for page_id in page_ids:
            if page_id in self.failed_ids:
                if self.write_artifacts:
                    attachment_root = working_directory / "_attachments" / page_id
                    attachment_root.mkdir(parents=True, exist_ok=True)
                    (attachment_root / "failed-only.txt").write_text(
                        "must not publish\n",
                        encoding="utf-8",
                    )
                    failed_markdown = working_directory / "markdown" / f"{page_id}-failed.md"
                    failed_markdown.parent.mkdir(parents=True, exist_ok=True)
                    failed_markdown.write_text("must not publish\n", encoding="utf-8")
                results.append(
                    {
                        "page_id": page_id,
                        "status": "failed",
                        "error_code": "conversion_failed",
                    }
                )
                continue
            markdown = working_directory / "markdown" / f"{page_id}.md"
            markdown.parent.mkdir(parents=True, exist_ok=True)
            markdown.write_text(f"# Café résumé {page_id}\n\nCrème brûlée.\n", encoding="utf-8")
            if self.write_artifacts:
                attachment_root = working_directory / "_attachments" / page_id
                attachment_root.mkdir(parents=True, exist_ok=True)
                (attachment_root / "converted-only.txt").write_text(
                    f"converted {page_id}\n",
                    encoding="utf-8",
                )
            results.append(
                {
                    "page_id": page_id,
                    "status": "converted",
                    "markdown_paths": [f"markdown/{page_id}.md"],
                }
            )
        (working_directory / "result.json").write_text(
            json.dumps(
                {"schema_version": 1, "tool_version": "1.0.0", "pages": results},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 2 if self.failed_ids.intersection(page_ids) else 0


def _page(page_id: str, updated_at: datetime) -> RemotePage:
    return RemotePage(
        page_id=page_id,
        title=f"Café résumé {page_id}",
        space_key="DOC",
        version_number=2,
        version_when=updated_at,
        last_updated=updated_at,
        author="Élodie",
        occurred_at=_NOW - timedelta(days=30),
        canonical_uri=f"https://confluence.example.test/display/DOC/{page_id}",
    )


def _settings(tmp_path: Path, *, threshold: float = 0.10) -> ConfluenceSettings:
    return ConfluenceSettings(
        base_url="https://confluence.example.test",
        auth_expires_at=_NOW + timedelta(days=90),
        console_path=tmp_path / "fixture-console.exe",
        failure_threshold=threshold,
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="knowledge/confluence",
                classification="perso-non-sensible",
            ),
        ),
    )


def _page_settings(
    tmp_path: Path,
    page_ids: tuple[str, ...],
    *,
    threshold: float = 0.10,
) -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=2,
        base_url="https://confluence.example.test",
        auth_expires_at=_NOW + timedelta(days=90),
        console_path=tmp_path / "fixture-console.exe",
        failure_threshold=threshold,
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="knowledge/confluence",
                classification="perso-non-sensible",
                selection="pages",
                pages=tuple(PageSelection(page_id=page_id) for page_id in page_ids),
            ),
        ),
    )


def _subtree_settings(
    tmp_path: Path,
    root_ids: tuple[str, ...],
    *,
    threshold: float = 0.10,
) -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=3,
        base_url="https://confluence.example.test",
        auth_expires_at=_NOW + timedelta(days=90),
        console_path=tmp_path / "fixture-console.exe",
        failure_threshold=threshold,
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="knowledge/confluence",
                classification="perso-non-sensible",
                selection="subtree",
                pages=tuple(PageSelection(page_id=root_id) for root_id in root_ids),
            ),
        ),
    )


def _run(
    storage: IngestionStorage,
    settings: ConfluenceSettings,
    client: FakeRestClient,
    console: FakeConsole,
    now: datetime,
) -> object:
    attempt = _collect(storage, settings, client, console, now)
    return GenerationEngine(storage).run(attempt, now=now)


def _collect(
    storage: IngestionStorage,
    settings: ConfluenceSettings,
    client: FakeRestClient,
    console: FakeConsole,
    now: datetime,
) -> GenerationAttempt:
    writer = ConfluenceWriter(
        settings,
        storage,
        client_factory=lambda _secret: client,  # type: ignore[arg-type]
        converter_runner=console,
    )
    return writer.collect(SecretValue(_FAKE_SECRET), captured_at=now)


def _bulk_pages(count: int) -> list[RemotePage]:
    return [_page(str(index), _NOW) for index in range(1, count + 1)]


def test_failed_conversion_removes_its_owned_temporary_workspace(tmp_path: Path) -> None:
    workspaces: list[Path] = []

    def no_result(_console_path: Path, working_directory: Path) -> int:
        workspaces.append(working_directory)
        return 0

    writer = ConfluenceWriter(
        _page_settings(tmp_path, ("1001",)),
        IngestionStorage(tmp_path / "state", "doc", retention_generations=2),
        client_factory=lambda _secret: FakeRestClient([_page("1001", _NOW)]),
        converter_runner=no_result,
    )

    with pytest.raises(ConverterContractError, match="result.json"):
        writer.collect(SecretValue(_FAKE_SECRET), captured_at=_NOW)

    assert workspaces
    assert all(not workspace.exists() for workspace in workspaces)


def test_console_converter_rejects_a_gui_without_the_capability_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(converter_module.subprocess, "run", fake_run)
    gui_path = tmp_path / "ConfluenceRAGBuilder.exe"

    with pytest.raises(ConverterContractError, match="not a compatible"):
        ConsoleConverter(gui_path)

    assert commands == [[str(gui_path), "--probe"]]


def _large_job_page(page_id: str, attachments: list[dict[str, object]]) -> dict[str, object]:
    return {
        "page_id": page_id,
        "title": f"Page {page_id}",
        "space_key": "DOC",
        "version": 1,
        "updated_at": "2026-08-03T12:00:00Z",
        "author": "Fixture Author",
        "canonical_url": f"https://confluence.example.test/pages/{page_id}",
        "xhtml_path": f"input/pages/{page_id}.xhtml",
        "attachments": attachments,
    }


def test_empty_page_selection_publishes_without_space_enumeration(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    client = FakeRestClient([])
    console = FakeConsole()

    result = _run(
        storage,
        _page_settings(tmp_path, ()),
        client,
        console,
        _NOW,
    )

    assert result.published  # type: ignore[attr-defined]
    assert client.enumeration_calls == []
    assert client.page_calls == []
    assert console.jobs == []
    manifest = storage.load_current_manifest()
    assert manifest is not None
    assert [item.source_uid for item in manifest.documents] == ["zone:DOC"]


def test_empty_page_selection_degrades_health_and_names_the_space(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    client = FakeRestClient([])
    console = FakeConsole()

    with caplog.at_level(logging.WARNING):
        result = _run(
            storage,
            _page_settings(tmp_path, ()),
            client,
            console,
            _NOW,
        )

    assert result.published  # type: ignore[attr-defined]
    assert result.health.status is HealthStatus.DEGRADED  # type: ignore[attr-defined]
    assert result.health.error_code == "space_selection_empty"  # type: ignore[attr-defined]
    assert result.health.scope_summaries[0].selected_page_count == 0  # type: ignore[attr-defined]
    assert any(
        "space_selection_empty space_key=DOC" in record.getMessage()
        for record in caplog.records
    )


def test_a_space_that_collects_pages_stays_healthy(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    client = FakeRestClient([_page("1001", _NOW)])
    console = FakeConsole()

    result = _run(
        storage,
        _page_settings(tmp_path, ("1001",)),
        client,
        console,
        _NOW,
    )

    assert result.health.status is HealthStatus.OK  # type: ignore[attr-defined]
    assert result.health.error_code is None  # type: ignore[attr-defined]


def test_real_failures_outrank_an_empty_selection_in_the_health_code() -> None:
    assert _degraded_error_code(True, ("DOC",)) == "partial_failure"
    assert _degraded_error_code(False, ("DOC",)) == "space_selection_empty"
    assert _degraded_error_code(False, ()) is None


def test_page_selection_collects_only_configured_pages(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    client = FakeRestClient(
        [_page("1001", _NOW), _page("1002", _NOW), _page("1003", _NOW)],
        descendants={"1001": ("1003",)},
    )
    console = FakeConsole()

    result = _run(
        storage,
        _page_settings(tmp_path, ("1002", "1001")),
        client,
        console,
        _NOW,
    )

    assert result.published  # type: ignore[attr-defined]
    assert client.enumeration_calls == []
    assert client.page_calls == [("1002", "DOC"), ("1001", "DOC")]
    assert client.subtree_calls == [("1002", "DOC"), ("1001", "DOC")]
    assert client.content_calls == ["1002", "1001"]
    assert console.jobs == [["1002", "1001"]]
    manifest = storage.load_current_manifest()
    assert manifest is not None
    assert {item.source_uid for item in manifest.documents} == {
        "1001",
        "1002",
        "zone:DOC",
    }
    assert result.health.scope_summaries[0].selected_page_count == 2  # type: ignore[attr-defined]
    assert result.health.scope_summaries[0].available_page_count == 3  # type: ignore[attr-defined]
    assert result.health.scope_summaries[0].excluded_descendant_count == 1  # type: ignore[attr-defined]


def test_subtree_selection_collects_each_root_with_its_descendants(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    client = FakeRestClient(
        [_page(page_id, _NOW) for page_id in ("1001", "1002", "1003", "1004")],
        descendants={"1001": ("1002", "1003")},
    )
    console = FakeConsole()

    result = _run(storage, _subtree_settings(tmp_path, ("1001",)), client, console, _NOW)

    assert result.published  # type: ignore[attr-defined]
    assert client.enumeration_calls == []
    assert client.subtree_calls == [("1001", "DOC")]
    manifest = storage.load_current_manifest()
    assert manifest is not None
    assert {item.source_uid for item in manifest.documents} == {
        "1001",
        "1002",
        "1003",
        "zone:DOC",
    }


def test_overlapping_subtree_roots_collect_each_page_exactly_once(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    client = FakeRestClient(
        [_page(page_id, _NOW) for page_id in ("1001", "1002", "1003")],
        descendants={"1001": ("1002", "1003"), "1002": ("1003",)},
    )
    console = FakeConsole()

    result = _run(storage, _subtree_settings(tmp_path, ("1001", "1002")), client, console, _NOW)

    assert result.published  # type: ignore[attr-defined]
    assert sorted(client.content_calls) == ["1001", "1002", "1003"]
    manifest = storage.load_current_manifest()
    assert manifest is not None
    assert {item.source_uid for item in manifest.documents} == {
        "1001",
        "1002",
        "1003",
        "zone:DOC",
    }


def test_wrong_space_page_fails_before_staging_and_preserves_previous_document(
    tmp_path: Path,
) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=3)
    settings = _page_settings(tmp_path, ("1001",), threshold=1.0)
    console = FakeConsole()
    first = _run(
        storage,
        settings,
        FakeRestClient([_page("1001", _NOW)]),
        console,
        _NOW,
    )
    assert first.published  # type: ignore[attr-defined]
    first_generation = storage.current_generation_id()
    assert first_generation is not None
    first_manifest = storage.load_current_manifest()
    assert first_manifest is not None
    first_page = next(item for item in first_manifest.documents if item.source_uid == "1001")
    first_bytes = storage.document_path(first_generation, first_page.path).read_bytes()
    wrong_space = replace(_page("1001", _NOW + timedelta(hours=1)), space_key="OTHER")
    client = FakeRestClient([wrong_space])

    result = _run(
        storage,
        settings,
        client,
        console,
        _NOW + timedelta(hours=1),
    )

    assert result.published  # type: ignore[attr-defined]
    assert result.health.status is HealthStatus.DEGRADED  # type: ignore[attr-defined]
    assert result.health.counts.failed == 1  # type: ignore[attr-defined]
    assert result.health.counts.carry_forward == 1  # type: ignore[attr-defined]
    assert client.content_calls == []
    assert console.jobs == [["1001"]]
    current_generation = storage.current_generation_id()
    manifest = storage.load_current_manifest()
    assert current_generation is not None and manifest is not None
    current_page = next(item for item in manifest.documents if item.source_uid == "1001")
    assert current_page.status is DocumentStatus.STALE
    assert storage.document_path(current_generation, current_page.path).read_bytes() == first_bytes


def test_page_scope_reduction_creates_document_tombstone(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=3)
    console = FakeConsole()
    first = _run(
        storage,
        _page_settings(tmp_path, ("1001", "1002")),
        FakeRestClient([_page("1001", _NOW), _page("1002", _NOW)]),
        console,
        _NOW,
    )
    assert first.published  # type: ignore[attr-defined]

    second = _run(
        storage,
        _page_settings(tmp_path, ("1001",)),
        FakeRestClient([_page("1001", _NOW)]),
        console,
        _NOW + timedelta(hours=1),
    )

    assert second.published  # type: ignore[attr-defined]
    manifest = storage.load_current_manifest()
    assert manifest is not None
    assert {item.source_uid for item in manifest.documents} == {"1001", "zone:DOC"}
    assert any(
        item.source_uid == "1002" and item.kind is TombstoneKind.DOCUMENT
        for item in manifest.tombstones
    )


def test_1001_pages_use_two_isolated_console_jobs_in_stable_order(
    tmp_path: Path,
) -> None:
    pages = _bulk_pages(1001)
    page_ids = [page.page_id for page in pages]
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    console = FakeConsole(write_artifacts=False)

    attempt = _collect(
        storage,
        _settings(tmp_path),
        FakeRestClient(pages, include_attachments=False),
        console,
        _NOW,
    )

    assert [len(job) for job in console.jobs] == [1000, 1]
    assert [page_id for job in console.jobs for page_id in job] == page_ids
    assert [document.source_uid for document in attempt.documents[1:]] == page_ids
    assert len(set(console.working_directories)) == 2
    assert [path.name for path in console.working_directories] == ["batch-0001", "batch-0002"]
    assert all(
        path.parent == console.working_directories[0].parent
        for path in console.working_directories
    )


def test_exactly_1000_pages_use_one_console_job(tmp_path: Path) -> None:
    pages = _bulk_pages(1000)
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    console = FakeConsole(write_artifacts=False)

    _collect(
        storage,
        _settings(tmp_path),
        FakeRestClient(pages, include_attachments=False),
        console,
        _NOW,
    )

    assert [len(job) for job in console.jobs] == [1000]


def test_job_byte_limit_splits_large_page_records_before_count_limit(
    tmp_path: Path,
) -> None:
    converter = ConsoleConverter(tmp_path / "fixture-console.exe", runner=FakeConsole())
    file_name = "x" * 251 + ".txt"
    attachments: list[dict[str, object]] = [
        {
            "attachment_id": "a" * 128,
            "file_name": file_name,
            "media_type": "m" * 255,
            "path": f"input/attachments/fixture/{file_name}",
            "is_drawio_source": False,
        }
        for _index in range(1000)
    ]
    pages = [_large_job_page(str(index), attachments) for index in range(1, 13)]

    plan = converter.plan_job_pages(pages)

    assert converter.job_limits.maximum_pages == 1000
    assert converter.job_limits.maximum_bytes == 8388608
    assert len(plan.batches) > 1
    assert [page["page_id"] for batch in plan.batches for page in batch] == [
        page["page_id"] for page in pages
    ]
    assert all(
        converter.serialized_job_size({"schema_version": 1, "pages": list(batch)})
        <= converter.job_limits.maximum_bytes
        for batch in plan.batches
    )


def test_single_page_over_job_byte_limit_fails_page_and_continues_generation(
    tmp_path: Path,
) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    settings = _settings(tmp_path, threshold=1.0)
    converter = ConsoleConverter(settings.console_path or Path(), runner=FakeConsole())
    oversized = replace(
        _page("oversized", _NOW),
        title="x" * (converter.job_limits.maximum_bytes + 1),
    )
    console = FakeConsole(write_artifacts=False)

    attempt = _collect(
        storage,
        settings,
        FakeRestClient([oversized], include_attachments=False),
        console,
        _NOW,
    )
    result = GenerationEngine(storage).run(attempt, now=_NOW)

    assert result.published
    assert console.jobs == []
    assert [(failure.source_uid, failure.error_code) for failure in attempt.failures] == [
        ("oversized", "job_payload_too_large")
    ]
    assert not attempt.failure_threshold_exceeded


def test_failure_threshold_is_global_across_console_jobs(tmp_path: Path) -> None:
    pages = _bulk_pages(1001)
    settings = _settings(tmp_path, threshold=0.002)

    below_storage = IngestionStorage(
        tmp_path / "below-state",
        "doc",
        retention_generations=2,
    )
    below_console = FakeConsole(write_artifacts=False)
    below_console.failed_ids = {"1", "1001"}
    below_attempt = _collect(
        below_storage,
        settings,
        FakeRestClient(pages, include_attachments=False),
        below_console,
        _NOW,
    )
    below = GenerationEngine(below_storage).run(below_attempt, now=_NOW)

    above_storage = IngestionStorage(
        tmp_path / "above-state",
        "doc",
        retention_generations=2,
    )
    above_console = FakeConsole(write_artifacts=False)
    above_console.failed_ids = {"1", "2", "1001"}
    above_attempt = _collect(
        above_storage,
        settings,
        FakeRestClient(pages, include_attachments=False),
        above_console,
        _NOW,
    )
    above = GenerationEngine(above_storage).run(above_attempt, now=_NOW)

    assert [len(job) for job in below_console.jobs] == [1000, 1]
    assert [len(job) for job in above_console.jobs] == [1000, 1]
    assert not below_attempt.failure_threshold_exceeded
    assert below.published
    assert above_attempt.failure_threshold_exceeded
    assert not above.published
    assert above.health.action_required is not None
    assert "3/1001" in above.health.action_required
    assert "previous generation remains active" in above.health.action_required.casefold()
    assert "increase failure_threshold" in above.health.action_required


def test_empty_page_body_traverses_valid_job_and_is_published(tmp_path: Path) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    console = FakeConsole(write_artifacts=False)

    result = _run(
        storage,
        _settings(tmp_path),
        FakeRestClient(
            [_page("1001", _NOW)],
            include_attachments=False,
            xhtml="",
        ),
        console,
        _NOW,
    )

    assert result.published  # type: ignore[attr-defined]
    assert console.jobs == [["1001"]]
    assert console.xhtml_payloads == {"1001": b""}
    job_schema = json.loads((_RESOURCES / "job.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(job_schema, format_checker=FormatChecker()).validate(
        console.job_payloads[0]
    )
    manifest = storage.load_current_manifest()
    generation_id = storage.current_generation_id()
    assert manifest is not None and generation_id is not None
    document = next(item for item in manifest.documents if item.source_uid == "1001")
    assert document.status is DocumentStatus.FRESH
    assert storage.document_path(generation_id, document.path).is_file()


def test_hostile_windows_attachment_names_stage_distinct_valid_job_and_publish(
    tmp_path: Path,
) -> None:
    file_names = (
        "Spreadsheet-2023-03-13T13:40:03.render",
        "Spreadsheet-2023-03-13T13-40-03.render",
        "collision:name.txt",
        "collision?name.txt",
        "CON.txt",
        "rapport.",
        f"{'x' * 248}.render",
    )
    attachments = tuple(
        RemoteAttachment(
            attachment_id=str(5001 + index),
            file_name=file_name,
            media_type="application/octet-stream",
            file_size=24,
            download_uri=f"https://confluence.example.test/download/{5001 + index}",
            is_drawio_source=False,
        )
        for index, file_name in enumerate(file_names)
    )
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
    console = FakeConsole(write_artifacts=False)

    result = _run(
        storage,
        _settings(tmp_path),
        FakeRestClient([_page("574050555", _NOW)], attachments=attachments),
        console,
        _NOW,
    )

    assert result.published  # type: ignore[attr-defined]
    job = console.job_payloads[0]
    job_schema = json.loads((_RESOURCES / "job.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(job_schema, format_checker=FormatChecker()).validate(job)
    job_attachments = job["pages"][0]["attachments"]  # type: ignore[index]
    assert [attachment["file_name"] for attachment in job_attachments] == list(file_names)  # type: ignore[index]
    staged_paths = [attachment["path"] for attachment in job_attachments]  # type: ignore[index]
    staged_names = [Path(path).name for path in staged_paths]
    assert staged_names[:6] == [
        "5001-Spreadsheet-2023-03-13T13_40_03.render",
        "5002-Spreadsheet-2023-03-13T13-40-03.render",
        "5003-collision_name.txt",
        "5004-collision_name.txt",
        "5005-_CON.txt",
        "5006-rapport",
    ]
    assert len(staged_names[6]) == 255
    assert staged_names[6].endswith(".render")
    assert len({name.casefold() for name in staged_names}) == len(staged_names)
    assert set(console.attachment_payloads) == set(staged_paths)
    assert all(console.attachment_payloads[path] for path in staged_paths)


def test_incremental_skips_unchanged_page_and_reprocesses_modified_page(
    tmp_path: Path,
) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=3)
    settings = _settings(tmp_path)
    console = FakeConsole()
    first_client = FakeRestClient([_page("1001", _NOW), _page("1002", _NOW)])
    first = _run(storage, settings, first_client, console, _NOW)
    assert first.published  # type: ignore[attr-defined]

    second_client = FakeRestClient([_page("1001", _NOW), _page("1002", _NOW + timedelta(hours=1))])
    second = _run(storage, settings, second_client, console, _NOW + timedelta(hours=1))

    assert second.published  # type: ignore[attr-defined]
    assert second_client.content_calls == ["1002"]
    assert second_client.download_calls == ["attachment-1002"]
    assert console.jobs == [["1001", "1002"], ["1002"]]
    manifest = storage.load_current_manifest()
    assert manifest is not None
    assert {item.source_uid: item.status for item in manifest.documents}["1001"] is (
        DocumentStatus.FRESH
    )


def test_incremental_compares_both_remote_timestamps_even_when_max_is_unchanged(
    tmp_path: Path,
) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=3)
    settings = _settings(tmp_path)
    console = FakeConsole()
    initial = replace(
        _page("1001", _NOW),
        version_when=_NOW + timedelta(hours=2),
        last_updated=_NOW,
    )
    assert _run(storage, settings, FakeRestClient([initial]), console, _NOW).published  # type: ignore[attr-defined]
    changed = replace(initial, last_updated=_NOW + timedelta(hours=1))
    client = FakeRestClient([changed])

    result = _run(storage, settings, client, console, _NOW + timedelta(hours=3))

    assert result.published  # type: ignore[attr-defined]
    assert initial.updated_at == changed.updated_at
    assert client.content_calls == ["1001"]
    assert console.jobs == [["1001"], ["1001"]]


def test_failed_conversion_carries_forward_without_failed_page_artifacts(
    tmp_path: Path,
) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=3)
    settings = _settings(tmp_path, threshold=1.0)
    console = FakeConsole()
    assert _run(storage, settings, FakeRestClient([_page("1001", _NOW)]), console, _NOW).published  # type: ignore[attr-defined]
    previous_pointer = storage.current_generation_id()
    console.failed_ids = {"1001"}

    result = _run(
        storage,
        settings,
        FakeRestClient([_page("1001", _NOW + timedelta(hours=1))]),
        console,
        _NOW + timedelta(hours=1),
    )

    assert result.published  # type: ignore[attr-defined]
    assert result.health.status is HealthStatus.DEGRADED  # type: ignore[attr-defined]
    assert storage.current_generation_id() != previous_pointer
    manifest = storage.load_current_manifest()
    assert manifest is not None
    page = next(item for item in manifest.documents if item.source_uid == "1001")
    assert page.status is DocumentStatus.STALE
    assert [artifact.path for artifact in page.artifacts] == [
        "knowledge/confluence/_attachments/1001/converted-only.txt"
    ]
    current = storage.current_generation_id()
    assert current is not None
    published_files = {
        path.relative_to(storage.generation_path(current)).as_posix()
        for path in storage.generation_path(current).rglob("*")
        if path.is_file()
    }
    assert not any("failed-only" in path or "1001-failed" in path for path in published_files)


def test_failure_threshold_publishes_below_and_abandons_above(
    tmp_path: Path,
) -> None:
    storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=4)
    settings = _settings(tmp_path)
    console = FakeConsole()
    pages = [_page(str(1000 + index), _NOW) for index in range(1, 12)]
    assert _run(storage, settings, FakeRestClient(pages), console, _NOW).published  # type: ignore[attr-defined]

    console.failed_ids = {"1001"}
    below_pages = [
        _page(page.page_id, _NOW + timedelta(hours=1) if page.page_id == "1001" else _NOW)
        for page in pages
    ]
    below = _run(
        storage,
        settings,
        FakeRestClient(below_pages),
        console,
        _NOW + timedelta(hours=1),
    )
    assert below.published  # type: ignore[attr-defined]
    assert below.health.status is HealthStatus.DEGRADED  # type: ignore[attr-defined]
    pointer = storage.current_generation_id()

    console.failed_ids = {"1001", "1002"}
    above_pages = [
        _page(
            page.page_id,
            _NOW + timedelta(hours=2) if page.page_id in console.failed_ids else _NOW,
        )
        for page in pages
    ]
    above = _run(
        storage,
        settings,
        FakeRestClient(above_pages),
        console,
        _NOW + timedelta(hours=2),
    )
    assert not above.published  # type: ignore[attr-defined]
    assert above.health.status is HealthStatus.ERROR  # type: ignore[attr-defined]
    assert storage.current_generation_id() == pointer


def test_frontmatter_is_complete_utf8_and_fake_secret_never_persists(
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    target = logging.getLogger("cortex")
    previous_level = target.level
    previous_propagate = target.propagate
    previous_handlers = list(target.handlers)
    logger = configure_logging(log_dir=logs, logger_name="cortex")
    try:
        storage = IngestionStorage(tmp_path / "state", "doc", retention_generations=2)
        result = _run(
            storage,
            _settings(tmp_path),
            FakeRestClient([_page("1001", _NOW)]),
            FakeConsole(),
            _NOW,
        )
        assert result.published  # type: ignore[attr-defined]
        for handler in logger.handlers:
            handler.flush()
        manifest = storage.load_current_manifest()
        current = storage.current_generation_id()
        assert manifest is not None and current is not None
        page = next(item for item in manifest.documents if item.source_uid == "1001")
        payload = storage.document_path(current, page.path).read_bytes()
        assert "Café résumé" in payload.decode("utf-8")
        metadata = parse_frontmatter(payload)
        assert set(metadata) == {
            "schema_version",
            "source_kind",
            "source_system",
            "source_uid",
            "container_uid",
            "title",
            "author",
            "occurred_at",
            "updated_at",
            "canonical_uri",
            "path",
            "section",
            "captured_at",
            "content_hash",
            "chunk_index",
        }
        assert metadata["source_kind"] == "doc"
        assert metadata["author"] == "Élodie"
        generated = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
        assert _FAKE_SECRET.encode() not in generated
    finally:
        for handler in list(logger.handlers):
            if handler not in previous_handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


@pytest.mark.parametrize(
    "base_url",
    [
        "https://confluence.example.test",
        "https://confluence.example.test:8443/wiki",
        "http://localhost:8090",
        "http://127.0.0.1:8090",
        "http://[::1]:8090",
    ],
)
def test_base_url_accepts_tls_and_loopback_origins(base_url: str) -> None:
    assert ConfluenceSettings(base_url=base_url).base_url == base_url.rstrip("/")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://confluence.example.test",
        "http://10.0.0.5:8090",
        "http://confluence.example.test:8080/wiki",
    ],
)
def test_base_url_refuses_cleartext_remote_origins(base_url: str) -> None:
    """The PAT is a bearer header on every request; a cleartext origin leaks it."""
    with pytest.raises(ValueError, match="must use https"):
        ConfluenceSettings(base_url=base_url)
