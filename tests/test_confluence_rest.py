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
"""Sequential Confluence REST pagination contract tests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

import confluence_writer.rest as rest_module
from confluence_writer.constants import JOB_SCHEMA_SHA256, RESULT_SCHEMA_SHA256
from confluence_writer.models import RemotePageContent
from confluence_writer.rest import ConfluenceRestClient, ConfluenceRestError, UrlLibTransport
from ingestion.credentials import SecretValue

_FAKE_SECRET = "fixture-only-fake-secret-confluence-rest-6d6f"
_RESOURCES = Path(__file__).parents[1] / "confluence_writer" / "resources"


class QueueTransport:
    """Deterministic REST transport that records requested pages."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.json_calls: list[str] = []

    def get_json(self, uri: str, headers: Mapping[str, str]) -> dict[str, Any]:
        self.json_calls.append(uri)
        assert "Authorization" in headers
        return self.responses.pop(0)

    def get_bytes(
        self,
        uri: str,
        headers: Mapping[str, str],
        *,
        maximum_bytes: int,
    ) -> bytes:
        raise AssertionError("enumeration must not download content")


def _page(page_id: str, when: str) -> dict[str, Any]:
    return {
        "id": page_id,
        "title": f"Page {page_id}",
        "space": {"key": "DOC"},
        "version": {"number": 2, "when": when},
        "history": {
            "createdDate": "2026-07-01T08:00:00Z",
            "lastUpdated": {
                "when": when,
                "by": {"displayName": "Élodie"},
            },
        },
        "_links": {"webui": f"/display/DOC/{page_id}"},
    }


def test_space_enumeration_follows_multi_page_links_at_limit_250() -> None:
    transport = QueueTransport(
        [
            {
                "results": [_page("1001", "2026-08-01T10:00:00Z")],
                "_links": {"next": "/rest/api/content?spaceKey=DOC&start=250&limit=250"},
            },
            {
                "results": [_page("1002", "2026-08-02T10:00:00Z")],
                "_links": {},
            },
        ]
    )
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    pages = client.enumerate_pages("DOC")

    assert [page.page_id for page in pages] == ["1001", "1002"]
    assert len(transport.json_calls) == 2
    assert "limit=250" in transport.json_calls[0]
    assert transport.json_calls[1].endswith("start=250&limit=250")


def test_subtree_enumeration_uses_the_cql_ancestor_search_and_follows_next_links() -> None:
    transport = QueueTransport(
        [
            {
                "results": [_page("1002", "2026-08-01T10:00:00Z")],
                "_links": {"next": "/rest/api/content/search?cql=ancestor%3D1001&start=250"},
            },
            {
                "results": [_page("1003", "2026-08-02T10:00:00Z")],
                "_links": {},
            },
        ]
    )
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    pages = client.enumerate_subtree("1001", "DOC")

    assert [page.page_id for page in pages] == ["1002", "1003"]
    assert len(transport.json_calls) == 2
    assert "rest/api/content/search" in transport.json_calls[0]
    assert "ancestor%3D1001" in transport.json_calls[0]
    assert "descendant/page" not in transport.json_calls[0]
    assert "limit=250" in transport.json_calls[0]


def test_subtree_enumeration_fails_closed_on_a_page_from_another_space() -> None:
    payload = _page("1002", "2026-08-01T10:00:00Z")
    payload["space"] = {"key": "OTHER"}
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=QueueTransport([{"results": [payload], "_links": {}}]),
    )

    with pytest.raises(ConfluenceRestError, match="another space"):
        client.enumerate_subtree("1001", "DOC")


def test_ancestor_ids_returns_every_declared_ancestor_in_document_order() -> None:
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=QueueTransport([{"ancestors": [{"id": "1001"}, {"id": "1002"}]}]),
    )

    assert client.ancestor_ids("1003") == ("1001", "1002")


def test_selected_page_fetches_full_metadata_and_validates_space() -> None:
    transport = QueueTransport([_page("1001", "2026-08-01T10:00:00Z")])
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    page = client.get_page("1001", "DOC")

    assert page.page_id == "1001"
    assert page.space_key == "DOC"
    assert transport.json_calls == [
        "https://confluence.example.test/rest/api/content/1001"
        "?expand=space,version,history.lastUpdated,history.createdBy"
    ]


def test_selected_page_from_another_space_fails_closed() -> None:
    payload = _page("1001", "2026-08-01T10:00:00Z")
    payload["space"] = {"key": "OTHER"}
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=QueueTransport([payload]),
    )

    with pytest.raises(ConfluenceRestError, match="page from another space"):
        client.get_page("1001", "DOC")


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        pytest.param("missing-space", "field 'space'", id="missing-space"),
        pytest.param("different-id", "different page ID", id="different-id"),
    ],
)
def test_selected_page_rejects_missing_space_or_mismatched_identity(
    defect: str,
    message: str,
) -> None:
    payload = _page("1001", "2026-08-01T10:00:00Z")
    if defect == "missing-space":
        del payload["space"]
    else:
        payload["id"] = "1002"
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=QueueTransport([payload]),
    )

    with pytest.raises(ConfluenceRestError, match=message):
        client.get_page("1001", "DOC")


def test_page_content_accepts_empty_storage_body() -> None:
    transport = QueueTransport(
        [
            {"body": {"storage": {"value": ""}}},
            {"results": [], "_links": {}},
        ]
    )
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    content = client.page_content("1001")

    assert content == RemotePageContent(xhtml="", attachments=())


@pytest.mark.parametrize(
    "storage",
    [
        pytest.param({}, id="absent"),
        pytest.param({"value": None}, id="null"),
        pytest.param({"value": 42}, id="wrong-type"),
    ],
)
def test_page_content_rejects_missing_or_non_string_storage_body(
    storage: dict[str, object],
) -> None:
    transport = QueueTransport([{"body": {"storage": storage}}])
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    with pytest.raises(ConfluenceRestError, match=r"body\.storage\.value"):
        client.page_content("1001")


def test_tiny_transport_returns_mocked_location_without_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_headers = Message()
    response_headers["Location"] = "/pages/viewpage.action?pageId=1001"
    redirect = HTTPError(
        "https://confluence.example.test/x/AbC",
        302,
        "Found",
        response_headers,
        None,
    )

    class RedirectOpener:
        def open(self, *_args: object, **_kwargs: object) -> None:
            raise redirect

    monkeypatch.setattr(rest_module, "build_opener", lambda *_handlers: RedirectOpener())

    location = UrlLibTransport().get_redirect(
        "https://confluence.example.test/x/AbC",
        {"Authorization": f"Bearer {_FAKE_SECRET}"},
    )

    assert location == "/pages/viewpage.action?pageId=1001"


def test_vendored_schema_bytes_match_frozen_3a_provenance() -> None:
    job = (_RESOURCES / "job.schema.json").read_bytes().replace(b"\r\n", b"\n")
    result = (_RESOURCES / "result.schema.json").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(job).hexdigest() == JOB_SCHEMA_SHA256
    assert hashlib.sha256(result).hexdigest() == RESULT_SCHEMA_SHA256
