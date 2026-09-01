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
from typing import Literal

from pydantic import BaseModel, ConfigDict


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


class CliContractModel(BaseModel):  # type: ignore[misc]
    """Strict immutable base for JSON consumed by external clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolvedPageContract(CliContractModel):
    """Versioned machine result for one resolved Confluence page."""

    contract_version: Literal[1]
    page_id: str
    title: str
    space_key: str
    configured: bool


class ScopeChoiceContract(CliContractModel):
    """Count and approximate storage cost for one collection choice."""

    page_count: int
    estimated_bytes: int


class ScopePreviewContract(CliContractModel):
    """Versioned network preview presented before persisting one page root."""

    contract_version: Literal[1]
    page_id: str
    title: str
    space_key: str
    recommended_selection: Literal["pages", "subtree"]
    page_only: ScopeChoiceContract
    subtree: ScopeChoiceContract
    whole_space: ScopeChoiceContract
    storage_root: str
    retention_generations: int


class ConfiguredPageContract(CliContractModel):
    """One explicitly configured page and its latest known local title."""

    page_id: str
    title: str | None


class ConfiguredSpaceContract(CliContractModel):
    """One allowlisted space exposed to GUI clients."""

    space_key: str
    selection: Literal["whole_space", "pages", "subtree"]
    target: str
    classification: Literal["perso-non-sensible", "pro-confidentiel"]
    pages: tuple[ConfiguredPageContract, ...] | None


class LastSyncContract(CliContractModel):
    """Local health fields safe for machine display."""

    last_success_at: datetime | None
    status: Literal["ok", "degraded", "error"] | None
    error_code: str | None
    scope_summaries: tuple[ScopeSummaryContract, ...] = ()


class ScopeSummaryContract(CliContractModel):
    """Observed last-run scope used by GUI anomaly reporting."""

    space_key: str
    selection: Literal["whole_space", "pages", "subtree"]
    selected_page_count: int
    available_page_count: int | None
    excluded_descendant_count: int | None


class PagesContract(CliContractModel):
    """Versioned local-only configuration and health snapshot."""

    contract_version: Literal[2]
    spaces: tuple[ConfiguredSpaceContract, ...]
    last_sync: LastSyncContract
