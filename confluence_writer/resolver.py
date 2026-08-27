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
"""GUI-safe Confluence reference resolution and local configuration views."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from confluence_writer.config import ConfluenceSettings, SpaceMapping
from confluence_writer.constants import CLI_CONTRACT_VERSION, SOURCE_SYSTEM
from confluence_writer.frontmatter import parse_frontmatter
from confluence_writer.models import (
    ConfiguredPageContract,
    ConfiguredSpaceContract,
    LastSyncContract,
    PagesContract,
    RemotePage,
    ResolvedPageContract,
)
from confluence_writer.rest import ConfluenceRestClient
from ingestion.storage import IngestionStorage

_PAGE_ID = re.compile(r"^[0-9]+$")


class InvalidPageReferenceError(ValueError):
    """Raised when input is not one of the supported Kazan reference forms."""


class OutsideAllowlistError(RuntimeError):
    """Raised when a resolved page belongs to no configured space."""


@dataclass(frozen=True)
class _ParsedReference:
    kind: str
    page_id: str | None = None
    space_key: str | None = None
    title: str | None = None
    uri: str | None = None


def _origin(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    return parsed.scheme.casefold(), parsed.netloc.casefold()


def _parse_reference(
    value: str,
    *,
    base_url: str,
    allow_tiny: bool = True,
) -> _ParsedReference:
    candidate = value.strip()
    if _PAGE_ID.fullmatch(candidate):
        return _ParsedReference(kind="id", page_id=candidate)

    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidPageReferenceError("Expected a numeric page ID or an HTTP(S) Kazan URL.")
    if _origin(candidate) != _origin(base_url):
        raise InvalidPageReferenceError("Kazan URL must use the configured Confluence origin.")

    if parsed.path.endswith("/pages/viewpage.action"):
        page_ids = parse_qs(parsed.query, keep_blank_values=True).get("pageId", [])
        if len(page_ids) != 1 or not _PAGE_ID.fullmatch(page_ids[0]):
            raise InvalidPageReferenceError("viewpage URL must contain one numeric pageId.")
        return _ParsedReference(kind="id", page_id=page_ids[0])

    display_marker = "/display/"
    if display_marker in parsed.path:
        remainder = parsed.path.split(display_marker, 1)[1]
        raw_space, separator, raw_title = remainder.partition("/")
        space_key = unquote(raw_space)
        title = unquote(raw_title).replace("+", " ")
        if not separator or not space_key or not title:
            raise InvalidPageReferenceError("display URL must contain a space and title.")
        return _ParsedReference(kind="display", space_key=space_key, title=title)

    spaces_marker = "/spaces/"
    if spaces_marker in parsed.path:
        remainder = parsed.path.split(spaces_marker, 1)[1]
        segments = [segment for segment in remainder.split("/") if segment]
        if len(segments) >= 3 and segments[1] == "pages" and _PAGE_ID.fullmatch(segments[2]):
            return _ParsedReference(kind="id", page_id=segments[2])
        raise InvalidPageReferenceError("spaces URL must point at /pages/<numeric id>.")

    tiny_marker = "/x/"
    if tiny_marker in parsed.path:
        key = parsed.path.split(tiny_marker, 1)[1]
        if allow_tiny and key and "/" not in key and not parsed.query:
            return _ParsedReference(kind="tiny", uri=candidate)
        raise InvalidPageReferenceError("Tiny link must contain one path key.")

    raise InvalidPageReferenceError("Unsupported Kazan page URL.")


def resolve_page(
    value: str,
    *,
    settings: ConfluenceSettings,
    client: ConfluenceRestClient,
) -> ResolvedPageContract:
    """Resolve, verify, and classify one Kazan page reference."""
    if settings.base_url is None:
        raise InvalidPageReferenceError("Confluence base_url is not configured.")
    parsed = _parse_reference(value, base_url=settings.base_url)
    if parsed.kind == "tiny":
        assert parsed.uri is not None
        redirected = client.resolve_tiny_link(parsed.uri)
        parsed = _parse_reference(redirected, base_url=settings.base_url, allow_tiny=False)

    page: RemotePage
    if parsed.kind == "id":
        assert parsed.page_id is not None
        page = client.get_page_by_id(parsed.page_id)
    else:
        assert parsed.space_key is not None
        assert parsed.title is not None
        page = client.find_page(parsed.space_key, parsed.title)

    mapping = next(
        (
            item
            for item in settings.spaces
            if item.space_key.casefold() == page.space_key.casefold()
        ),
        None,
    )
    if mapping is None:
        raise OutsideAllowlistError("Resolved page belongs to a space outside the allowlist.")
    configured = _is_configured(page, mapping, client)
    return ResolvedPageContract(
        contract_version=CLI_CONTRACT_VERSION,
        page_id=page.page_id,
        title=page.title,
        space_key=page.space_key,
        configured=configured,
    )


def _is_configured(
    page: RemotePage,
    mapping: SpaceMapping,
    client: ConfluenceRestClient,
) -> bool:
    """Decide whether one resolved page is already collected by its space mapping."""
    selection = mapping.effective_selection
    if selection == "whole_space":
        return True
    if page.page_id in mapping.selected_page_ids:
        return True
    if selection != "subtree":
        return False
    roots = set(mapping.selected_page_ids)
    return any(ancestor in roots for ancestor in client.ancestor_ids(page.page_id))


def validate_page_reference(value: str, *, base_url: str) -> None:
    """Validate one supported reference without credential or network access."""
    _parse_reference(value, base_url=base_url)


def build_pages_contract(
    settings: ConfluenceSettings,
    storage: IngestionStorage,
) -> PagesContract:
    """Build a local-only configuration view from public ingestion readers."""
    titles: dict[str, str] = {}
    generation_id = storage.current_generation_id()
    manifest = None if generation_id is None else storage.load_manifest(generation_id)
    if generation_id is not None and manifest is not None:
        for document in manifest.documents:
            try:
                content = storage.document_path(generation_id, document.path).read_bytes()
                values = parse_frontmatter(content)
            except (OSError, UnicodeDecodeError):
                continue
            title = values.get("title")
            if (
                values.get("source_system") == SOURCE_SYSTEM
                and values.get("source_uid") == document.source_uid
                and isinstance(title, str)
                and title
            ):
                titles[document.source_uid] = title

    spaces: list[ConfiguredSpaceContract] = []
    for mapping in settings.spaces:
        pages = None
        if mapping.effective_selection == "pages":
            pages = tuple(
                ConfiguredPageContract(page_id=page_id, title=titles.get(page_id))
                for page_id in mapping.selected_page_ids
            )
        spaces.append(
            ConfiguredSpaceContract(
                space_key=mapping.space_key,
                selection=mapping.effective_selection,
                target=mapping.target,
                classification=mapping.classification,
                pages=pages,
            )
        )

    health = storage.load_health()
    return PagesContract(
        contract_version=CLI_CONTRACT_VERSION,
        spaces=tuple(spaces),
        last_sync=LastSyncContract(
            last_success_at=None if health is None else health.last_success_at,
            status=None if health is None else health.status.value,
            error_code=None if health is None else health.error_code,
        ),
    )


__all__ = [
    "InvalidPageReferenceError",
    "OutsideAllowlistError",
    "build_pages_contract",
    "resolve_page",
    "validate_page_reference",
]
