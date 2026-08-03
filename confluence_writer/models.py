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
"""Validated in-memory Confluence source contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RemotePage:
    """One page returned by a complete space enumeration."""

    page_id: str
    title: str
    space_key: str
    version_number: int
    version_when: datetime | None
    last_updated: datetime | None
    author: str | None
    occurred_at: datetime | None
    canonical_uri: str

    @property
    def updated_at(self) -> datetime | None:
        """Return the newest available incremental marker."""
        candidates = [
            value for value in (self.version_when, self.last_updated) if value is not None
        ]
        return max(candidates) if candidates else None


@dataclass(frozen=True)
class RemoteAttachment:
    """One attachment descriptor listed below a page."""

    attachment_id: str
    file_name: str
    media_type: str
    file_size: int
    download_uri: str
    is_drawio_source: bool


@dataclass(frozen=True)
class RemotePageContent:
    """Storage-format XHTML and attachment descriptors for one page."""

    xhtml: str
    attachments: tuple[RemoteAttachment, ...]
