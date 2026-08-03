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
from pathlib import Path
from typing import Any

from confluence_writer.constants import JOB_SCHEMA_SHA256, RESULT_SCHEMA_SHA256
from confluence_writer.rest import ConfluenceRestClient
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


def test_vendored_schema_bytes_match_frozen_3a_provenance() -> None:
    job = (_RESOURCES / "job.schema.json").read_bytes().replace(b"\r\n", b"\n")
    result = (_RESOURCES / "result.schema.json").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(job).hexdigest() == JOB_SCHEMA_SHA256
    assert hashlib.sha256(result).hexdigest() == RESULT_SCHEMA_SHA256
