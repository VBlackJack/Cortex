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
"""Sequential Confluence REST v1 client with bounded downloads."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, cast, final
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen

from confluence_writer.constants import PAGE_LIMIT
from confluence_writer.models import RemoteAttachment, RemotePage, RemotePageContent
from ingestion.credentials import SecretValue
from ingestion.scheduling import TransientIngestionError

_LOG = logging.getLogger("cortex.confluence_writer.rest")
_TRANSIENT_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ConfluenceRestError(RuntimeError):
    """Raised for a permanent or malformed Confluence response."""


class HttpTransport(Protocol):
    """Minimal synchronous transport used by the sequential source adapter."""

    def get_json(self, uri: str, headers: Mapping[str, str]) -> dict[str, Any]:
        """Return one decoded JSON object."""
        ...

    def get_bytes(
        self,
        uri: str,
        headers: Mapping[str, str],
        *,
        maximum_bytes: int,
    ) -> bytes:
        """Return one response body no larger than the declared limit."""
        ...


@final
class UrlLibTransport:
    """Standard-library HTTP transport without implicit credential persistence."""

    def get_json(self, uri: str, headers: Mapping[str, str]) -> dict[str, Any]:
        """Read strict UTF-8 JSON while classifying retryable failures."""
        payload = self.get_bytes(uri, headers, maximum_bytes=16 * 1024 * 1024)
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfluenceRestError("Confluence returned invalid UTF-8 JSON.") from exc
        if not isinstance(value, dict):
            raise ConfluenceRestError("Confluence returned a non-object JSON response.")
        return cast(dict[str, Any], value)

    def get_bytes(
        self,
        uri: str,
        headers: Mapping[str, str],
        *,
        maximum_bytes: int,
    ) -> bytes:
        """Read a bounded response and never include authentication in errors."""
        request = Request(uri, headers=dict(headers), method="GET")
        try:
            with urlopen(request, timeout=60.0) as response:  # noqa: S310
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > maximum_bytes:
                    raise ConfluenceRestError("Confluence response exceeds the configured limit.")
                payload = cast(bytes, response.read(maximum_bytes + 1))
        except HTTPError as exc:
            if exc.code in _TRANSIENT_HTTP_STATUS:
                raise TransientIngestionError(
                    f"Confluence returned transient HTTP status {exc.code}."
                ) from exc
            raise ConfluenceRestError(f"Confluence returned HTTP status {exc.code}.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TransientIngestionError("Confluence request failed transiently.") from exc
        except ValueError as exc:
            raise ConfluenceRestError("Confluence returned an invalid Content-Length.") from exc
        if len(payload) > maximum_bytes:
            raise ConfluenceRestError("Confluence response exceeds the configured limit.")
        return payload


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfluenceRestError(f"Confluence response field '{label}' must be an object.")
    return cast(dict[str, Any], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ConfluenceRestError(f"Confluence response field '{label}' must be an array.")
    return cast(list[object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfluenceRestError(f"Confluence response field '{label}' must be a string.")
    return value


def _string_allow_empty(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ConfluenceRestError(f"Confluence response field '{label}' must be a string.")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _datetime(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    raw = _string(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfluenceRestError(f"Confluence field '{label}' is not RFC 3339.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConfluenceRestError(f"Confluence field '{label}' lacks a UTC offset.")
    return parsed


class ConfluenceRestClient:
    """Enumerate and download one allowlisted Confluence source sequentially."""

    def __init__(
        self,
        base_url: str,
        secret: SecretValue,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        """Bind an ephemeral bearer value to a source origin."""
        self._base_url = base_url.rstrip("/")
        self._origin = self._origin_of(self._base_url)
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {secret.reveal()}",
        }
        self._transport = UrlLibTransport() if transport is None else transport

    @staticmethod
    def _origin_of(uri: str) -> str:
        parsed = urlsplit(uri)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _resolve(self, link: str, *, current: str | None = None) -> str:
        base = self._base_url + "/" if current is None else current
        resolved = urljoin(base, link)
        if self._origin_of(resolved) != self._origin:
            raise ConfluenceRestError("Confluence response link changed origin.")
        return resolved

    def _api_uri(self, relative: str) -> str:
        return self._base_url + "/" + relative.lstrip("/")

    def enumerate_pages(self, space_key: str) -> tuple[RemotePage, ...]:
        """Follow every `_links.next` page at the fixed measured cadence."""
        uri: str | None = self._api_uri(
            "rest/api/content"
            f"?spaceKey={quote(space_key, safe='')}"
            "&type=page&status=current"
            "&expand=version,history.lastUpdated,history.createdBy"
            f"&limit={PAGE_LIMIT}"
        )
        visited: set[str] = set()
        pages: list[RemotePage] = []
        while uri is not None:
            if uri in visited:
                raise ConfluenceRestError("Confluence pagination returned a cycle.")
            visited.add(uri)
            payload = self._transport.get_json(uri, self._headers)
            for raw in _list(payload.get("results"), "results"):
                pages.append(self._parse_page(_object(raw, "results[]"), space_key))
            links = _object(payload.get("_links", {}), "_links")
            next_link = _optional_string(links.get("next"))
            uri = None if next_link is None else self._resolve(next_link, current=uri)
        _LOG.info(
            "confluence_space_enumerated space_key=%s pages=%d requests=%d",
            space_key,
            len(pages),
            len(visited),
        )
        return tuple(pages)

    def get_page(self, page_id: str, expected_space: str) -> RemotePage:
        """Fetch one selected page and validate its declared space before staging."""
        uri = self._api_uri(
            f"rest/api/content/{quote(page_id, safe='')}"
            "?expand=space,version,history.lastUpdated,history.createdBy"
        )
        payload = self._transport.get_json(uri, self._headers)
        _object(payload.get("space"), "space")
        page = self._parse_page(payload, expected_space)
        if page.page_id != page_id:
            raise ConfluenceRestError("Confluence returned a different page ID.")
        return page

    def _parse_page(self, value: dict[str, Any], expected_space: str) -> RemotePage:
        page_id = _string(value.get("id"), "id")
        title = _string(value.get("title"), "title")
        space = _object(value.get("space", {"key": expected_space}), "space")
        space_key = _string(space.get("key", expected_space), "space.key")
        if space_key != expected_space:
            raise ConfluenceRestError("Confluence returned a page from another space.")
        version = _object(value.get("version", {}), "version")
        version_number = version.get("number", 1)
        if type(version_number) is not int or version_number < 1:
            raise ConfluenceRestError("Confluence version.number must be a positive integer.")
        history = _object(value.get("history", {}), "history")
        last_updated = _object(history.get("lastUpdated", {}), "history.lastUpdated")
        author_object = last_updated.get("by", version.get("by"))
        author = None
        if author_object is not None:
            author = _optional_string(_object(author_object, "author").get("displayName"))
        links = _object(value.get("_links", {}), "_links")
        webui = _optional_string(links.get("webui"))
        canonical = self._api_uri(f"pages/{quote(page_id, safe='')}")
        if webui is not None:
            canonical = self._resolve(webui)
        return RemotePage(
            page_id=page_id,
            title=title,
            space_key=space_key,
            version_number=version_number,
            version_when=_datetime(version.get("when"), "version.when"),
            last_updated=_datetime(last_updated.get("when"), "history.lastUpdated.when"),
            author=author,
            occurred_at=_datetime(history.get("createdDate"), "history.createdDate"),
            canonical_uri=canonical,
        )

    def page_content(self, page_id: str) -> RemotePageContent:
        """Download XHTML and enumerate attachment descriptors for one changed page."""
        uri = self._api_uri(f"rest/api/content/{quote(page_id, safe='')}?expand=body.storage")
        payload = self._transport.get_json(uri, self._headers)
        body = _object(payload.get("body"), "body")
        storage = _object(body.get("storage"), "body.storage")
        xhtml = _string_allow_empty(storage.get("value"), "body.storage.value")
        return RemotePageContent(xhtml=xhtml, attachments=self._attachments(page_id))

    def _attachments(self, page_id: str) -> tuple[RemoteAttachment, ...]:
        uri: str | None = self._api_uri(
            f"rest/api/content/{quote(page_id, safe='')}/child/attachment?limit={PAGE_LIMIT}"
        )
        attachments: list[RemoteAttachment] = []
        visited: set[str] = set()
        while uri is not None:
            if uri in visited:
                raise ConfluenceRestError("Confluence attachment pagination returned a cycle.")
            visited.add(uri)
            payload = self._transport.get_json(uri, self._headers)
            for raw in _list(payload.get("results"), "results"):
                value = _object(raw, "results[]")
                extensions = _object(value.get("extensions", {}), "extensions")
                metadata = _object(value.get("metadata", {}), "metadata")
                links = _object(value.get("_links", {}), "_links")
                raw_size = extensions.get("fileSize", 0)
                if type(raw_size) is not int or raw_size < 0:
                    raise ConfluenceRestError(
                        "Attachment fileSize must be a non-negative integer."
                    )
                file_name = _string(value.get("title"), "attachment.title")
                media_type = _optional_string(metadata.get("mediaType")) or (
                    "application/octet-stream"
                )
                attachments.append(
                    RemoteAttachment(
                        attachment_id=_string(value.get("id"), "attachment.id"),
                        file_name=file_name,
                        media_type=media_type,
                        file_size=raw_size,
                        download_uri=self._resolve(
                            _string(links.get("download"), "attachment._links.download")
                        ),
                        is_drawio_source=file_name.casefold().endswith((".drawio", ".xml")),
                    )
                )
            links = _object(payload.get("_links", {}), "_links")
            next_link = _optional_string(links.get("next"))
            uri = None if next_link is None else self._resolve(next_link, current=uri)
        return tuple(attachments)

    def download_attachment(self, attachment: RemoteAttachment, *, maximum_bytes: int) -> bytes:
        """Download one attachment after validating declared and actual size."""
        if attachment.file_size > maximum_bytes:
            raise ConfluenceRestError("Attachment exceeds the configured maximum size.")
        return self._transport.get_bytes(
            attachment.download_uri,
            self._headers,
            maximum_bytes=maximum_bytes,
        )


__all__ = [
    "ConfluenceRestClient",
    "ConfluenceRestError",
    "HttpTransport",
    "UrlLibTransport",
]
