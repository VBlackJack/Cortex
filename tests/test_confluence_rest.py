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
import threading
from collections.abc import Iterator, Mapping
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

import confluence_writer.rest as rest_module
from confluence_writer.constants import JOB_SCHEMA_SHA256, RESULT_SCHEMA_SHA256
from confluence_writer.models import RemotePageContent
from confluence_writer.rest import (
    ConfluenceCapabilityError,
    ConfluenceRestClient,
    ConfluenceRestError,
    UrlLibTransport,
)
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


# The complete query each count must issue, pinned whole so a widened limit, a lost
# quote or a reintroduced status clause all fail rather than slipping past a substring.
SPACE_COUNT_QUERY = "cql=space%3D%22DOC%22%20and%20type%3Dpage&limit=1"
SUBTREE_COUNT_QUERY = "cql=ancestor%3D1001%20and%20type%3Dpage%20and%20space%3D%22DOC%22&limit=1"


def test_scope_counts_read_one_indexed_total_without_paging() -> None:
    """The preview needs the number, never the pages, and must pay for one request."""
    transport = QueueTransport([{"results": [], "totalSize": 5916, "_links": {"next": "/next"}}])
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    assert client.count_pages("DOC") == 5916

    assert len(transport.json_calls) == 1
    request = transport.json_calls[0]
    assert "rest/api/content/search" in request
    assert "expand" not in request
    # Pinned whole, not by substring: "limit=1" is also a prefix of "limit=100", so a
    # constant that silently started paging would satisfy a containment check. The space
    # key travels inside a CQL string literal, and the absence of a status clause is
    # deliberate, since the measured deployment answers one with HTTP 400.
    assert request.endswith("?" + SPACE_COUNT_QUERY)


def test_subtree_count_scopes_the_ancestor_search_to_the_expected_space() -> None:
    transport = QueueTransport([{"results": [], "totalSize": 8, "_links": {}}])
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    assert client.count_subtree("1001", "DOC") == 8

    assert len(transport.json_calls) == 1
    request = transport.json_calls[0]
    assert "expand" not in request
    assert request.endswith("?" + SUBTREE_COUNT_QUERY)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"results": []}, id="absent"),
        pytest.param({"totalSize": None}, id="null"),
        pytest.param({"totalSize": "5916"}, id="string"),
        pytest.param({"totalSize": True}, id="boolean"),
        pytest.param({"totalSize": -1}, id="negative"),
    ],
)
def test_scope_count_fails_closed_when_the_total_is_unusable(payload: dict[str, Any]) -> None:
    """A missing total must not silently become a zero-page scope in the preview."""
    transport = QueueTransport([payload])
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    with pytest.raises(ConfluenceCapabilityError, match="no usable total"):
        client.count_pages("DOC")
    assert len(transport.json_calls) == 1


@pytest.mark.parametrize(
    "space_key",
    [
        pytest.param('DOC" or type=blogpost and space="OTHER', id="quote-break-out"),
        pytest.param("DOC OTHER", id="whitespace"),
        pytest.param("", id="empty"),
    ],
)
def test_scope_count_refuses_a_space_key_that_is_unsafe_inside_cql(space_key: str) -> None:
    """URL encoding is not CQL escaping, so the shape is checked before interpolation."""
    transport = QueueTransport([])
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    with pytest.raises(ConfluenceRestError, match="not safe inside a CQL query"):
        client.count_pages(space_key)
    assert transport.json_calls == []


def test_subtree_count_refuses_a_root_id_that_is_unsafe_inside_cql() -> None:
    transport = QueueTransport([])
    client = ConfluenceRestClient(
        "https://confluence.example.test",
        SecretValue(_FAKE_SECRET),
        transport=transport,
    )

    with pytest.raises(ConfluenceRestError, match="not safe inside a CQL query"):
        client.count_subtree("1001 or type=blogpost", "DOC")
    assert transport.json_calls == []


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


class _CredentialCaptureHandler(BaseHTTPRequestHandler):
    """Record whichever request headers reach this origin."""

    received: list[Mapping[str, str]] = []

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler contract.
        type(self).received.append(dict(self.headers))
        body = b'{"captured": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return None


class _RedirectingOriginHandler(BaseHTTPRequestHandler):
    """Answer with the redirect shape named by the requested path."""

    foreign_port: int = 0

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler contract.
        if self.path == "/foreign":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{type(self).foreign_port}/stolen")
            self.end_headers()
            return
        if self.path == "/relative":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        if self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
            return
        body = b'{"origin": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return None


def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[int]:
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def foreign_origin_port() -> Iterator[int]:
    _CredentialCaptureHandler.received = []
    yield from _serve(_CredentialCaptureHandler)


@pytest.fixture
def confluence_origin_port(foreign_origin_port: int) -> Iterator[int]:
    _RedirectingOriginHandler.foreign_port = foreign_origin_port
    yield from _serve(_RedirectingOriginHandler)


def test_cross_origin_redirect_never_replays_the_bearer_credential(
    confluence_origin_port: int,
    foreign_origin_port: int,
) -> None:
    headers = {"Authorization": f"Bearer {_FAKE_SECRET}"}

    with pytest.raises(ConfluenceRestError, match="another origin"):
        UrlLibTransport().get_json(
            f"http://127.0.0.1:{confluence_origin_port}/foreign",
            headers,
        )

    assert _CredentialCaptureHandler.received == []


def test_same_origin_redirect_is_followed(confluence_origin_port: int) -> None:
    payload = UrlLibTransport().get_json(
        f"http://127.0.0.1:{confluence_origin_port}/relative",
        {"Authorization": f"Bearer {_FAKE_SECRET}"},
    )

    assert payload == {"origin": True}


def test_redirect_loop_is_bounded(confluence_origin_port: int) -> None:
    with pytest.raises(ConfluenceRestError, match="redirect limit"):
        UrlLibTransport().get_json(
            f"http://127.0.0.1:{confluence_origin_port}/loop",
            {"Authorization": f"Bearer {_FAKE_SECRET}"},
        )


def test_catalog_paginates_titles_and_ancestor_chains() -> None:
    first = _page("1", "2026-08-01T10:00:00Z") | {"ancestors": []}
    child = _page("2", "2026-08-01T10:00:00Z") | {"ancestors": [{"id": "1"}]}
    transport = QueueTransport(
        [
            {"results": [first], "_links": {"next": "/rest/api/content?start=250"}},
            {"results": [child], "_links": {}},
        ]
    )
    client = ConfluenceRestClient(
        "https://confluence.example.test", SecretValue(_FAKE_SECRET), transport=transport
    )
    pages = client.page_catalog("DOC")
    assert [page.page_id for page in pages] == ["1", "2"]
    assert pages[1].ancestor_ids == ("1",)
    assert "expand=space,ancestors" in transport.json_calls[0]


@pytest.mark.parametrize(
    "ancestors", [None, [{"id": "1"}], [{"id": "2"}, {"id": "2"}], [{"id": "bad"}]]
)
def test_catalog_refuses_missing_or_invalid_ancestry(ancestors: object) -> None:
    page = _page("1", "2026-08-01T10:00:00Z")
    if ancestors is not None:
        page["ancestors"] = ancestors
    transport = QueueTransport([{"results": [page], "_links": {}}])
    client = ConfluenceRestClient(
        "https://confluence.example.test", SecretValue(_FAKE_SECRET), transport=transport
    )
    with pytest.raises(ConfluenceRestError):
        client.page_catalog("DOC")


def test_catalog_refuses_foreign_pagination_before_following_it() -> None:
    transport = QueueTransport(
        [{"results": [], "_links": {"next": "https://foreign.test/rest/api/content"}}]
    )
    client = ConfluenceRestClient(
        "https://confluence.example.test", SecretValue(_FAKE_SECRET), transport=transport
    )
    with pytest.raises(ConfluenceRestError, match="origin"):
        client.page_catalog("DOC")
    assert len(transport.json_calls) == 1
