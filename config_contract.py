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
"""Versioned machine contract for Cortex user configuration operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

CONFIG_CLI_CONTRACT_VERSION: Literal[1] = 1

ConfigErrorCode = Literal[
    "invalid_configuration",
    "invalid_argument",
    "hash_mismatch",
    "locked",
    "write_failed",
    "validation_failed",
]


class ConfigContractModel(BaseModel):  # type: ignore[misc]
    """Strict immutable base for user configuration contract models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfigError(ConfigContractModel):
    """One structured configuration operation error."""

    code: ConfigErrorCode
    phase: str
    path: Literal[None] = None


class ConfigValues(ConfigContractModel):
    """All resolved schema v1 user configuration values."""

    schema_version: int
    kb_path: str | None
    chroma_path: str
    index_whole_folder: bool
    included_sections: tuple[str, ...]
    excluded_dirs: tuple[str, ...]
    exclude_files: tuple[str, ...]
    max_markdown_file_size_bytes: int
    max_pdf_size_bytes: int
    write_lock_path: str
    write_lock_timeout_seconds: float


class ConfigGetReport(ConfigContractModel):
    """Complete result for one user configuration read."""

    contract_version: Literal[1] = CONFIG_CLI_CONTRACT_VERSION
    operation: Literal["config_get"] = "config_get"
    status: Literal["succeeded"] = "succeeded"
    present: bool
    content_hash: str | None
    valid: bool
    error: ConfigError | None
    values: ConfigValues | None
    restart_required: Literal[False] = False
    reindex_required: Literal[False] = False


class ConfigSetReport(ConfigContractModel):
    """Complete result for one compare-and-swap user configuration mutation."""

    contract_version: Literal[1] = CONFIG_CLI_CONTRACT_VERSION
    operation: Literal["config_set"] = "config_set"
    status: Literal["succeeded", "unchanged", "conflict", "locked", "failed"]
    changed: bool
    previous_content_hash: str | None
    content_hash: str | None
    backup_written: bool
    rebuilt_from_defaults: bool
    restart_required: bool
    reindex_required: bool
    error: ConfigError | None


__all__ = [
    "CONFIG_CLI_CONTRACT_VERSION",
    "ConfigError",
    "ConfigErrorCode",
    "ConfigGetReport",
    "ConfigSetReport",
    "ConfigValues",
]
