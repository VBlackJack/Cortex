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
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from confluence_writer.config import ConfluenceSettings, SpaceMapping
from confluence_writer.converter import ConsoleConverter
from confluence_writer.frontmatter import parse_frontmatter
from confluence_writer.models import RemoteAttachment, RemotePage, RemotePageContent
from confluence_writer.writer import ConfluenceWriter
from cortex_logging import configure_logging
from ingestion.credentials import SecretValue
from ingestion.engine import GenerationEngine
from ingestion.models import DocumentStatus, GenerationAttempt, HealthStatus
from ingestion.storage import IngestionStorage

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
_FAKE_SECRET = "fixture-only-fake-secret-confluence-writer-f37c"


class FakeRestClient:
    """Mock REST source with explicit enumeration, content, and download counters."""

    def __init__(self, pages: list[RemotePage], *, include_attachments: bool = True) -> None:
        self.pages = pages
        self.include_attachments = include_attachments
        self.content_calls: list[str] = []
        self.download_calls: list[str] = []

    def enumerate_pages(self, space_key: str) -> tuple[RemotePage, ...]:
        return tuple(page for page in self.pages if page.space_key == space_key)

    def page_content(self, page_id: str) -> RemotePageContent:
        self.content_calls.append(page_id)
        if not self.include_attachments:
            return RemotePageContent(
                xhtml=f"<p>Crème brûlée {page_id}</p>",
                attachments=(),
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
        self.working_directories: list[Path] = []

    def __call__(self, console_path: Path, working_directory: Path) -> int:
        job = json.loads((working_directory / "job.json").read_text(encoding="utf-8"))
        page_ids = [page["page_id"] for page in job["pages"]]
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
