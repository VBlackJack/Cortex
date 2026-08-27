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
"""Machine-facing Confluence CLI contract tests for GUI consumers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import confluence_writer.cli as confluence_cli
from confluence_writer.config import (
    ConfluenceSettings,
    PageSelection,
    SpaceMapping,
)
from confluence_writer.constants import (
    EXIT_AUTH,
    EXIT_ERROR,
    EXIT_INVALID_INPUT,
    EXIT_LOCKED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_OUTSIDE_ALLOWLIST,
    EXIT_REMOTE,
    SOURCE_KIND,
)
from confluence_writer.frontmatter import render_document
from confluence_writer.models import RemotePage
from confluence_writer.rest import ConfluenceRestClient
from ingestion.config import IngestionSettings
from ingestion.credentials import CredentialReadError, SecretValue
from ingestion.locking import source_sync_lock
from ingestion.models import (
    AttemptResult,
    DocumentRecord,
    DocumentStatus,
    GenerationManifest,
    HealthCounts,
    HealthStatus,
    SourceHealth,
)
from ingestion.scheduling import TransientIngestionError
from ingestion.storage import IngestionStorage

_FAKE_SECRET = "fixture-only-fake-secret-confluence-surface-19a2"
_NOW = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)


class QueueTransport:
    """Mock transport with explicit JSON and Location queues."""

    def __init__(
        self,
        responses: list[dict[str, Any] | Exception],
        *,
        locations: list[str] | None = None,
    ) -> None:
        self.responses = responses
        self.locations = [] if locations is None else locations
        self.json_calls: list[str] = []
        self.redirect_calls: list[str] = []

    def get_json(self, uri: str, headers: Mapping[str, str]) -> dict[str, Any]:
        self.json_calls.append(uri)
        assert headers["Authorization"] == f"Bearer {_FAKE_SECRET}"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get_bytes(
        self,
        uri: str,
        headers: Mapping[str, str],
        *,
        maximum_bytes: int,
    ) -> bytes:
        raise AssertionError("resolve must not download page or attachment bytes")

    def get_redirect(self, uri: str, headers: Mapping[str, str]) -> str:
        self.redirect_calls.append(uri)
        assert headers["Authorization"] == f"Bearer {_FAKE_SECRET}"
        return self.locations.pop(0)


class FakeCredentialReader:
    """Return only a synthetic in-memory secret."""

    def read(self, target_name: str) -> SecretValue:
        assert target_name == "cortex-spike"
        return SecretValue(_FAKE_SECRET)


def _page(
    page_id: str = "1001", *, space_key: str = "DOC", title: str = "Run Book"
) -> dict[str, Any]:
    return {
        "id": page_id,
        "title": title,
        "space": {"key": space_key},
        "version": {"number": 3, "when": "2026-08-05T09:00:00Z"},
        "history": {
            "createdDate": "2026-08-01T09:00:00Z",
            "lastUpdated": {"when": "2026-08-05T09:00:00Z"},
        },
        "_links": {"webui": f"/display/{space_key}/Run+Book"},
    }


def _settings(*, pages: tuple[str, ...] | None = None) -> ConfluenceSettings:
    selection = "whole_space" if pages is None else "pages"
    configured_pages = None
    if pages is not None:
        configured_pages = tuple(PageSelection(page_id=page_id) for page_id in pages)
    return ConfluenceSettings(
        schema_version=2,
        base_url="https://kazan.example.test",
        credential_target="cortex-spike",
        auth_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        console_path=Path("fixture-console.exe"),
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="knowledge/doc",
                classification="perso-non-sensible",
                selection=selection,
                pages=configured_pages,
            ),
        ),
    )


def _ingestion_settings(root: Path, *, lock_timeout_seconds: float = 0.0) -> IngestionSettings:
    return IngestionSettings(data_root=root, lock_timeout_seconds=lock_timeout_seconds)


def _prepare_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    settings: ConfluenceSettings,
    transport: QueueTransport,
) -> None:
    ingestion_settings = _ingestion_settings(tmp_path / "ingestion")
    client = ConfluenceRestClient(
        "https://kazan.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )
    monkeypatch.setattr(confluence_cli, "load_confluence_settings", lambda **_kwargs: settings)
    monkeypatch.setattr(
        confluence_cli,
        "load_ingestion_settings",
        lambda **_kwargs: ingestion_settings,
    )
    monkeypatch.setattr(confluence_cli, "WindowsCredentialReader", FakeCredentialReader)
    monkeypatch.setattr(confluence_cli, "ConfluenceRestClient", lambda *_args: client)
    monkeypatch.setattr("cortex_logging.configure_logging", lambda: None)


@pytest.mark.parametrize(
    ("reference", "responses", "locations"),
    [
        pytest.param("1001", [_page()], [], id="numeric-id"),
        pytest.param(
            "https://kazan.example.test/pages/viewpage.action?pageId=1001",
            [_page()],
            [],
            id="viewpage",
        ),
        pytest.param(
            "https://kazan.example.test/display/DOC/Run+Book",
            [{"results": [_page()]}],
            [],
            id="display",
        ),
        pytest.param(
            "https://kazan.example.test/spaces/DOC/pages/1001/Run+Book",
            [_page()],
            [],
            id="spaces-path",
        ),
        pytest.param(
            "https://kazan.example.test/spaces/DOC/pages/1001",
            [_page()],
            [],
            id="spaces-path-without-slug",
        ),
        pytest.param(
            "https://kazan.example.test/wiki/spaces/DOC/pages/1001/Run+Book",
            [_page()],
            [],
            id="spaces-path-with-wiki-prefix",
        ),
        pytest.param(
            "https://kazan.example.test/x/AbC",
            [_page()],
            ["/pages/viewpage.action?pageId=1001"],
            id="tiny-link",
        ),
    ],
)
def test_resolve_accepts_all_kazan_forms_as_clean_versioned_json(
    reference: str,
    responses: list[dict[str, Any]],
    locations: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = QueueTransport(responses, locations=locations)
    _prepare_cli(monkeypatch, tmp_path, _settings(), transport)

    exit_code = confluence_cli.main(["resolve", reference, "--json"])
    captured = capsys.readouterr()

    assert exit_code == EXIT_OK
    assert json.loads(captured.out) == {
        "contract_version": 1,
        "page_id": "1001",
        "title": "Run Book",
        "space_key": "DOC",
        "configured": True,
    }
    assert captured.err == ""
    if "/x/" in reference:
        assert transport.redirect_calls == [reference]


@pytest.mark.parametrize(
    ("configured_pages", "expected"),
    [
        pytest.param(("1001",), True, id="already-listed"),
        pytest.param(("1002",), False, id="not-listed"),
    ],
)
def test_resolve_reports_page_configuration_in_pages_mode(
    configured_pages: tuple[str, ...],
    expected: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = QueueTransport([_page()])
    _prepare_cli(monkeypatch, tmp_path, _settings(pages=configured_pages), transport)

    assert confluence_cli.main(["resolve", "1001", "--json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["configured"] is expected


@pytest.mark.parametrize(
    ("reference", "responses", "expected_code"),
    [
        pytest.param(
            "https://kazan.example.test/display/DOC/Missing",
            [{"results": []}],
            EXIT_NOT_FOUND,
            id="not-found",
        ),
        pytest.param("not-a-page", [], EXIT_INVALID_INPUT, id="invalid-input"),
        pytest.param(
            "https://kazan.example.test/spaces/DOC/overview",
            [],
            EXIT_INVALID_INPUT,
            id="spaces-overview-is-not-a-page",
        ),
        pytest.param(
            "https://kazan.example.test/spaces/DOC/pages/not-numeric",
            [],
            EXIT_INVALID_INPUT,
            id="spaces-non-numeric-page-id",
        ),
        pytest.param("1001", [_page(space_key="OTHER")], EXIT_OUTSIDE_ALLOWLIST, id="outside"),
        pytest.param(
            "1001",
            [TransientIngestionError("fixture transport failure")],
            EXIT_REMOTE,
            id="transport",
        ),
    ],
)
def test_resolve_failures_have_exact_codes_and_no_json_stdout(
    reference: str,
    responses: list[dict[str, Any] | Exception],
    expected_code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_cli(monkeypatch, tmp_path, _settings(), QueueTransport(responses))

    assert confluence_cli.main(["resolve", reference, "--json"]) == expected_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Cortex Confluence error:")


def test_resolve_missing_credential_has_auth_code_and_no_secret_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = QueueTransport([])
    _prepare_cli(monkeypatch, tmp_path, _settings(), transport)

    class MissingCredentialReader:
        def read(self, target_name: str) -> SecretValue:
            raise CredentialReadError(f"missing {target_name} {_FAKE_SECRET}")

    monkeypatch.setattr(confluence_cli, "WindowsCredentialReader", MissingCredentialReader)

    assert confluence_cli.main(["resolve", "1001", "--json"]) == EXIT_AUTH
    captured = capsys.readouterr()
    assert captured.out == ""
    assert _FAKE_SECRET not in captured.err
    assert transport.json_calls == []


def _publish_known_page(storage: IngestionStorage) -> None:
    generation_id = "20260805T100000Z-a3"
    pending = storage.create_pending_generation(generation_id)
    remote = RemotePage(
        page_id="2001",
        title="Known title",
        space_key="RUN",
        version_number=1,
        version_when=_NOW,
        last_updated=_NOW,
        author=None,
        occurred_at=_NOW,
        canonical_uri="https://kazan.example.test/pages/2001",
    )
    content = render_document(remote, path="run/known.md", body="# Known", captured_at=_NOW)
    document_path = pending / "documents" / "run" / "known.md"
    document_path.parent.mkdir(parents=True)
    document_path.write_bytes(content)
    storage.publish_pending_generation(
        generation_id,
        GenerationManifest(
            schema_version=1,
            generation_id=generation_id,
            published_at=_NOW,
            documents=(
                DocumentRecord(
                    source_uid="2001",
                    path="run/known.md",
                    content_hash=hashlib.sha256(content).hexdigest(),
                    status=DocumentStatus.FRESH,
                    last_success_at=_NOW,
                ),
            ),
            tombstones=(),
        ),
    )
    storage.write_health(
        SourceHealth(
            schema_version=1,
            source_kind=SOURCE_KIND,
            last_attempt_at=_NOW,
            last_success_at=_NOW,
            remote_cursor=None,
            auth_expires_at=None,
            status=HealthStatus.DEGRADED,
            error_code="partial_failure",
            action_required=None,
            counts=HealthCounts(seen=2, converted=1, failed=1),
        )
    )


def _mixed_settings() -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=2,
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target="knowledge/doc",
                classification="perso-non-sensible",
                selection="whole_space",
            ),
            SpaceMapping(
                space_key="RUN",
                target="knowledge/run",
                classification="pro-confidentiel",
                selection="pages",
                pages=(PageSelection(page_id="2001"), PageSelection(page_id="2002")),
            ),
        ),
    )


def _prepare_local_pages_cli(
    monkeypatch: pytest.MonkeyPatch,
    settings: ConfluenceSettings,
    ingestion_settings: IngestionSettings,
) -> None:
    def forbidden_boundary(*_args: object, **_kwargs: object) -> None:
        pytest.fail("pages --json crossed a credential or network boundary")

    monkeypatch.setattr(confluence_cli, "load_confluence_settings", lambda **_kwargs: settings)
    monkeypatch.setattr(
        confluence_cli,
        "load_ingestion_settings",
        lambda **_kwargs: ingestion_settings,
    )
    monkeypatch.setattr(confluence_cli, "WindowsCredentialReader", forbidden_boundary)
    monkeypatch.setattr(confluence_cli, "ConfluenceRestClient", forbidden_boundary)
    monkeypatch.setattr("cortex_logging.configure_logging", lambda: None)


def test_pages_json_golden_mixed_config_uses_only_local_manifest_and_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ingestion_settings = _ingestion_settings(tmp_path / "ingestion")
    storage = IngestionStorage(ingestion_settings.data_root, SOURCE_KIND, 2)
    _publish_known_page(storage)
    _prepare_local_pages_cli(monkeypatch, _mixed_settings(), ingestion_settings)

    assert confluence_cli.main(["pages", "--json"]) == EXIT_OK
    captured = capsys.readouterr()

    assert json.loads(captured.out) == {
        "contract_version": 1,
        "spaces": [
            {
                "space_key": "DOC",
                "selection": "whole_space",
                "target": "knowledge/doc",
                "classification": "perso-non-sensible",
                "pages": None,
            },
            {
                "space_key": "RUN",
                "selection": "pages",
                "target": "knowledge/run",
                "classification": "pro-confidentiel",
                "pages": [
                    {"page_id": "2001", "title": "Known title"},
                    {"page_id": "2002", "title": None},
                ],
            },
        ],
        "last_sync": {
            "last_success_at": "2026-08-05T10:00:00Z",
            "status": "degraded",
            "error_code": "partial_failure",
        },
    }
    assert captured.err == ""


def test_pages_json_without_manifest_or_health_keeps_valid_null_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ingestion_settings = _ingestion_settings(tmp_path / "absent")
    _prepare_local_pages_cli(monkeypatch, _mixed_settings(), ingestion_settings)

    assert confluence_cli.main(["pages", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)

    assert payload["contract_version"] == 1
    assert payload["spaces"][1]["pages"] == [
        {"page_id": "2001", "title": None},
        {"page_id": "2002", "title": None},
    ]
    assert payload["last_sync"] == {
        "last_success_at": None,
        "status": None,
        "error_code": None,
    }


def test_sync_lock_contention_has_dedicated_code_and_never_collects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings()
    ingestion_settings = _ingestion_settings(tmp_path / "ingestion", lock_timeout_seconds=0.0)
    storage = IngestionStorage(ingestion_settings.data_root, SOURCE_KIND, 2)
    collect_calls = 0

    class ForbiddenWriter:
        def __init__(self, *_args: object) -> None:
            pass

        def collect(self, _secret: SecretValue) -> None:
            nonlocal collect_calls
            collect_calls += 1
            pytest.fail("lock contention must stop before collection")

    monkeypatch.setattr(confluence_cli, "load_confluence_settings", lambda **_kwargs: settings)
    monkeypatch.setattr(
        confluence_cli,
        "load_ingestion_settings",
        lambda **_kwargs: ingestion_settings,
    )
    monkeypatch.setattr(confluence_cli, "ConfluenceWriter", ForbiddenWriter)
    monkeypatch.setattr(confluence_cli, "_rechunk_v2_ready", lambda: True)
    monkeypatch.setattr("cortex_logging.configure_logging", lambda: None)

    with source_sync_lock(storage, timeout_seconds=0.0):
        exit_code = confluence_cli.main(["sync", "--force"])
    captured = capsys.readouterr()

    assert exit_code == EXIT_LOCKED
    assert json.loads(captured.out)["health"]["error_code"] == "sync_already_running"
    assert collect_calls == 0


@pytest.mark.parametrize(
    ("published", "error_code", "expected_code"),
    [
        pytest.param(True, None, EXIT_OK, id="success"),
        pytest.param(False, "sync_already_running", EXIT_LOCKED, id="lock"),
        pytest.param(False, "credential_unavailable", EXIT_AUTH, id="credential-missing"),
        pytest.param(False, "credential_expired", EXIT_AUTH, id="credential-expired"),
        pytest.param(
            False,
            "transient_retries_exhausted",
            EXIT_REMOTE,
            id="network-rest",
        ),
        pytest.param(False, "source_attempt_failed", EXIT_ERROR, id="general"),
    ],
)
def test_sync_result_exit_contract_is_stable(
    published: bool,
    error_code: str | None,
    expected_code: int,
) -> None:
    health = SourceHealth(
        schema_version=1,
        source_kind=SOURCE_KIND,
        last_attempt_at=_NOW,
        last_success_at=_NOW if published else None,
        remote_cursor=None,
        auth_expires_at=None,
        status=HealthStatus.OK if published else HealthStatus.ERROR,
        error_code=error_code,
        action_required=None,
        counts=HealthCounts(),
    )
    result = AttemptResult(
        published=published,
        generation_id="published" if published else None,
        health=health,
    )

    assert confluence_cli._sync_result_exit_code(result) == expected_code
