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
"""Incremental Confluence collection assembled for the common generation engine."""

from __future__ import annotations

import logging
import re
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from confluence_writer.config import ConfluenceSettings, SpaceMapping, require_sync_settings
from confluence_writer.converter import ConsoleConverter, Runner
from confluence_writer.frontmatter import previous_updated_at, render_document
from confluence_writer.models import RemotePage, RemotePageContent
from confluence_writer.rest import (
    ConfluenceRestClient,
    ConfluenceRestError,
    HttpTransport,
)
from ingestion.credentials import SecretValue
from ingestion.models import (
    CollectedArtifact,
    CollectedDocument,
    DocumentFailure,
    GenerationAttempt,
)
from ingestion.storage import IngestionStorage

_LOG = logging.getLogger("cortex.confluence_writer.writer")
_UNKNOWN_AUTHOR = "Unknown"
_ZONE_UID_PREFIX = "zone:"
_BATCH_DIRECTORY_PREFIX = "batch-"
_STAGING_DIRECTORY_NAME = "staging"
_OVERSIZED_JOB_ERROR_CODE = "job_payload_too_large"
_WINDOWS_FILE_NAME_LIMIT = 255
_WINDOWS_INVALID_FILE_NAME_CHARACTERS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_FILE_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_STAGED_FILE_NAME_FALLBACK = "file"
_PAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ConfluenceWriterError(RuntimeError):
    """Raised when source data cannot be safely represented by the writer contract."""


ClientFactory = Callable[[SecretValue], ConfluenceRestClient]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ConfluenceWriterError("Confluence source timestamp lacks a UTC offset.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_file_name(value: str) -> bool:
    return (
        bool(value)
        and value not in {".", ".."}
        and len(value) <= 255
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
    )


def _staged_attachment_file_name(attachment_id: str, file_name: str) -> str:
    sanitized = "".join(
        "_"
        if ord(character) < 0x20 or character in _WINDOWS_INVALID_FILE_NAME_CHARACTERS
        else character
        for character in file_name
    ).rstrip(" .")
    if not sanitized:
        sanitized = _STAGED_FILE_NAME_FALLBACK
    if sanitized.split(".", maxsplit=1)[0].casefold() in _WINDOWS_RESERVED_FILE_NAMES:
        sanitized = f"_{sanitized}"

    prefix = f"{attachment_id}-"
    maximum_name_length = _WINDOWS_FILE_NAME_LIMIT - len(prefix)
    extension = Path(sanitized).suffix
    maximum_stem_length = maximum_name_length - len(extension)
    if maximum_stem_length < 1:
        raise ConfluenceRestError("Attachment file extension is too long for staging.")
    stem = sanitized[: -len(extension)] if extension else sanitized
    return f"{prefix}{stem[:maximum_stem_length]}{extension}"


def _source_revision(page: RemotePage) -> str:
    version_when = "null" if page.version_when is None else _rfc3339(page.version_when)
    last_updated = "null" if page.last_updated is None else _rfc3339(page.last_updated)
    return f"version.when={version_when};history.lastUpdated={last_updated}"


class ConfluenceWriter:
    """Collect complete remote state and emit one fail-closed generation attempt."""

    def __init__(
        self,
        settings: ConfluenceSettings,
        storage: IngestionStorage,
        *,
        transport: HttpTransport | None = None,
        converter_runner: Runner | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        """Bind config and common storage without reading credentials."""
        require_sync_settings(settings)
        self._settings = settings
        self._storage = storage
        self._converter_runner = converter_runner
        if client_factory is not None:
            self._client_factory = client_factory
        else:
            base_url = settings.base_url
            if base_url is None:  # narrowed by require_sync_settings
                raise ConfluenceWriterError("base_url is required")
            self._client_factory = lambda secret: ConfluenceRestClient(
                base_url,
                secret,
                transport=transport,
            )

    def collect(
        self,
        secret: SecretValue,
        *,
        captured_at: datetime | None = None,
    ) -> GenerationAttempt:
        """Enumerate, download, convert sequential batches, and return engine inputs."""
        observed_at = _utc_now() if captured_at is None else captured_at
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("captured_at must include a UTC offset")
        client = self._client_factory(secret)
        mappings = {item.space_key: item for item in self._settings.spaces}
        pages: list[RemotePage] = []
        for mapping in self._settings.spaces:
            pages.extend(client.enumerate_pages(mapping.space_key))
        by_id = {page.page_id: page for page in pages}
        if len(by_id) != len(pages):
            raise ConfluenceWriterError("Confluence enumeration returned duplicate page IDs.")
        if any(
            not _PAGE_ID.fullmatch(page.page_id) or page.space_key not in mappings
            for page in pages
        ):
            raise ConfluenceWriterError("Confluence enumeration returned an unsafe page identity.")

        previous_revisions, current_ids = self._previous_state()
        changed = [
            page
            for page in pages
            if page.page_id not in previous_revisions
            or previous_revisions[page.page_id] != _source_revision(page)
        ]
        remote_seen = set(by_id)
        documents: list[CollectedDocument] = []
        failures: list[DocumentFailure] = []

        for mapping in self._settings.spaces:
            zone_uid = self._zone_uid(mapping)
            remote_seen.add(zone_uid)
            if zone_uid not in current_ids:
                documents.append(self._zone_readme(mapping, observed_at))

        if changed:
            converted_documents, conversion_failures = self._convert_changed(
                client,
                changed,
                mappings,
                observed_at,
            )
            documents.extend(converted_documents)
            failures.extend(conversion_failures)

        failed_ids = {failure.source_uid for failure in failures}
        for page in changed:
            if page.page_id not in failed_ids and all(
                document.source_uid != page.page_id for document in documents
            ):
                raise ConfluenceWriterError("Changed page was neither converted nor failed.")

        failure_rate = len(failures) / len(pages) if pages else 0.0
        remote_cursor = max(
            (_rfc3339(page.updated_at) for page in pages if page.updated_at is not None),
            default=None,
        )
        _LOG.info(
            "confluence_generation_collected spaces=%d pages=%d changed=%d failed=%d",
            len(self._settings.spaces),
            len(pages),
            len(changed),
            len(failures),
        )
        return GenerationAttempt(
            documents=tuple(documents),
            failures=tuple(failures),
            remote_seen_source_uids=frozenset(remote_seen),
            enumeration_complete=True,
            enumeration_succeeded=True,
            remote_cursor=remote_cursor,
            auth_expires_at=self._settings.auth_expires_at,
            failure_threshold_exceeded=failure_rate > self._settings.failure_threshold,
        )

    def _previous_state(self) -> tuple[dict[str, str | None], set[str]]:
        manifest = self._storage.load_current_manifest()
        generation_id = self._storage.current_generation_id()
        if manifest is None or generation_id is None:
            return {}, set()
        revisions: dict[str, str | None] = {}
        current_ids: set[str] = set()
        for document in manifest.documents:
            current_ids.add(document.source_uid)
            if document.source_uid.startswith(_ZONE_UID_PREFIX):
                continue
            if document.source_revision is not None:
                revisions[document.source_uid] = document.source_revision
                continue
            path = self._storage.document_path(generation_id, document.path)
            legacy_updated_at = previous_updated_at(path.read_bytes())
            revisions[document.source_uid] = (
                None
                if legacy_updated_at is None
                else f"legacy.updated_at={_rfc3339(legacy_updated_at)}"
            )
        return revisions, current_ids

    def _convert_changed(
        self,
        client: ConfluenceRestClient,
        pages: list[RemotePage],
        mappings: dict[str, SpaceMapping],
        observed_at: datetime,
    ) -> tuple[list[CollectedDocument], list[DocumentFailure]]:
        console_path = self._settings.console_path
        if console_path is None:  # narrowed by require_sync_settings
            raise ConfluenceWriterError("console_path is required")
        maximum_bytes = self._settings.max_attachment_size_mb * 1024 * 1024
        failures: list[DocumentFailure] = []
        staged_pages: list[RemotePage] = []
        with tempfile.TemporaryDirectory(prefix="cortex-confluence-") as temporary:
            root = Path(temporary)
            staging_root = root / _STAGING_DIRECTORY_NAME
            job_pages: list[dict[str, object]] = []
            for page in pages:
                try:
                    content = client.page_content(page.page_id)
                    job_pages.append(
                        self._stage_page(staging_root, client, page, content, maximum_bytes)
                    )
                    staged_pages.append(page)
                except (
                    ConfluenceRestError,
                    ConfluenceWriterError,
                    OSError,
                    UnicodeError,
                ) as exc:
                    failures.append(
                        DocumentFailure(source_uid=page.page_id, error_code="source_page_failed")
                    )
                    _LOG.warning(
                        "confluence_page_staging_failed page_id=%s error_type=%s",
                        page.page_id,
                        type(exc).__name__,
                    )
            if not staged_pages:
                return [], failures
            converter = ConsoleConverter(console_path, runner=self._converter_runner)
            plan = converter.plan_job_pages(job_pages)
            failures.extend(
                DocumentFailure(
                    source_uid=page_id,
                    error_code=_OVERSIZED_JOB_ERROR_CODE,
                )
                for page_id in plan.oversized_page_ids
            )
            pages_by_id = {page.page_id: page for page in staged_pages}
            documents: list[CollectedDocument] = []
            for batch_index, job_batch in enumerate(plan.batches, start=1):
                batch_root = root / f"{_BATCH_DIRECTORY_PREFIX}{batch_index:04d}"
                self._move_batch_inputs(staging_root, batch_root, job_batch)
                batch = converter.convert(
                    batch_root,
                    {"schema_version": 1, "pages": list(job_batch)},
                    requested_page_ids=frozenset(
                        cast(str, job_page["page_id"]) for job_page in job_batch
                    ),
                )
                for converted in batch.converted:
                    page = pages_by_id[converted.page_id]
                    mapping = mappings[page.space_key]
                    path = f"{mapping.target}/markdown/{page.page_id}.md"
                    artifacts = tuple(
                        CollectedArtifact(
                            path=f"{mapping.target}/{relative_path}",
                            content=content,
                        )
                        for relative_path, content in converted.artifacts
                    )
                    documents.append(
                        CollectedDocument(
                            source_uid=page.page_id,
                            path=path,
                            content=render_document(
                                page,
                                path=path,
                                body=converted.markdown,
                                captured_at=observed_at,
                            ),
                            artifacts=artifacts,
                            source_revision=_source_revision(page),
                        )
                    )
                failures.extend(
                    DocumentFailure(source_uid=failed.page_id, error_code=failed.error_code)
                    for failed in batch.failed
                )
            return documents, failures

    @staticmethod
    def _move_batch_inputs(
        staging_root: Path,
        batch_root: Path,
        job_pages: tuple[dict[str, object], ...],
    ) -> None:
        for job_page in job_pages:
            relative_paths = [cast(str, job_page["xhtml_path"])]
            attachments = cast(list[dict[str, object]], job_page["attachments"])
            relative_paths.extend(cast(str, attachment["path"]) for attachment in attachments)
            for relative_path in relative_paths:
                source = staging_root.joinpath(*relative_path.split("/"))
                target = batch_root.joinpath(*relative_path.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                source.replace(target)

    @staticmethod
    def _stage_page(
        root: Path,
        client: ConfluenceRestClient,
        page: RemotePage,
        content: RemotePageContent,
        maximum_bytes: int,
    ) -> dict[str, object]:
        if page.updated_at is None:
            raise ConfluenceWriterError("Confluence page has no incremental timestamp.")
        xhtml_path = root / "input" / "pages" / f"{page.page_id}.xhtml"
        xhtml_path.parent.mkdir(parents=True, exist_ok=True)
        xhtml_path.write_text(content.xhtml, encoding="utf-8", newline="\n")
        attachments: list[dict[str, object]] = []
        seen_names: set[str] = set()
        for attachment in content.attachments:
            if not _safe_file_name(attachment.file_name):
                raise ConfluenceRestError("Attachment file name is unsafe.")
            if not _PAGE_ID.fullmatch(attachment.attachment_id):
                raise ConfluenceRestError("Attachment ID is unsafe for staging.")
            normalized_name = attachment.file_name.casefold()
            if normalized_name in seen_names:
                raise ConfluenceRestError("Attachment file names collide case-insensitively.")
            seen_names.add(normalized_name)
            payload = client.download_attachment(attachment, maximum_bytes=maximum_bytes)
            staged_file_name = _staged_attachment_file_name(
                attachment.attachment_id,
                attachment.file_name,
            )
            relative = Path("input") / "attachments" / page.page_id / staged_file_name
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            attachments.append(
                {
                    "attachment_id": attachment.attachment_id,
                    "file_name": attachment.file_name,
                    "media_type": attachment.media_type,
                    "path": relative.as_posix(),
                    "is_drawio_source": attachment.is_drawio_source,
                }
            )
        return {
            "page_id": page.page_id,
            "title": page.title,
            "space_key": page.space_key,
            "version": page.version_number,
            "updated_at": _rfc3339(page.updated_at),
            "author": page.author or _UNKNOWN_AUTHOR,
            "canonical_url": page.canonical_uri,
            "xhtml_path": xhtml_path.relative_to(root).as_posix(),
            "attachments": attachments,
        }

    @staticmethod
    def _zone_uid(mapping: SpaceMapping) -> str:
        return _ZONE_UID_PREFIX + mapping.space_key

    def _zone_readme(self, mapping: SpaceMapping, observed_at: datetime) -> CollectedDocument:
        source_uid = self._zone_uid(mapping)
        base_url = self._settings.base_url
        if base_url is None:  # narrowed by require_sync_settings
            raise ConfluenceWriterError("base_url is required")
        path = f"{mapping.target}/README.md"
        page = RemotePage(
            page_id=source_uid,
            title=f"Managed Confluence zone {mapping.space_key}",
            space_key=mapping.space_key,
            version_number=1,
            version_when=observed_at,
            last_updated=observed_at,
            author=None,
            occurred_at=observed_at,
            canonical_uri=base_url,
        )
        body = (
            "# Managed Confluence zone\n\n"
            "This directory is read-only for humans. Cortex replaces manual edits during "
            "the next successful generation.\n\n"
            f"Classification: `{mapping.classification}`.\n"
        )
        return CollectedDocument(
            source_uid=source_uid,
            path=path,
            content=render_document(page, path=path, body=body, captured_at=observed_at),
        )


__all__ = ["ClientFactory", "ConfluenceWriter", "ConfluenceWriterError"]
