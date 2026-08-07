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
"""Strict versioned machine contract for Cortex portable bundles."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from index_contract import (
    CHUNKING_CONTRACT_VERSION,
    EMBEDDING_MODEL,
    EMBEDDING_POOLING,
    LEXICAL_INDEX_CONTRACT_VERSION,
    METADATA_SCHEMA_VERSION,
)

BUNDLE_CONTRACT_VERSION: Literal[1] = 1
CONTAINER_VERSION: Literal[1] = 1
BUNDLE_FORMAT: Literal["cortexbundle"] = "cortexbundle"
BUNDLE_COMPRESSION: Literal["none"] = "none"
CIPHER_NAME: Literal["aes-256-gcm"] = "aes-256-gcm"
KDF_NAME: Literal["argon2id"] = "argon2id"
FRAME_BYTES: Literal[1048576] = 1_048_576
MAX_ENCRYPTED_FRAME_BYTES = FRAME_BYTES + 16
MAX_HEADER_BYTES = 65_536
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
SALT_BYTES = 16
NONCE_PREFIX_BYTES = 4

ROLE_ORDER = (
    "chroma",
    "lexical",
    "ingestion_store",
    "config",
    "ingestion_config",
    "confluence_config",
)
BundleRole = Literal[
    "chroma",
    "lexical",
    "ingestion_store",
    "config",
    "ingestion_config",
    "confluence_config",
]

EXCLUDED_ITEMS = (
    (
        "confluence_pat",
        "vit dans le Windows Credential Manager, hors du systeme de fichiers",
    ),
    (
        "vault",
        "volume de donnees source, a copier ou rendre accessible separement",
    ),
    ("logs", "sans valeur sur un autre poste"),
    ("locks", "etat de processus, invalide hors de sa machine"),
    ("companion_settings", "appartient au depot CortexCompanion"),
)
ExcludedItemName = Literal[
    "confluence_pat",
    "vault",
    "logs",
    "locks",
    "companion_settings",
]

BundleErrorCode = Literal[
    "archive_not_found",
    "archive_unreadable",
    "malformed_container",
    "unsupported_container_version",
    "header_field_rejected",
    "kdf_parameters_rejected",
    "password_missing",
    "kdf_unavailable",
    "authentication_failed",
    "truncated_archive",
    "malformed_payload",
    "malformed_manifest",
    "unsupported_contract_version",
    "header_manifest_mismatch",
    "member_rejected",
    "member_digest_mismatch",
]

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def decode_canonical_base64(value: str, expected_bytes: int) -> bytes:
    """Decode one canonical RFC 4648 section 4 value of an exact length."""
    if len(value) % 4 != 0 or not value.endswith("="):
        raise ValueError("base64 padding is required")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("base64 must use the standard RFC 4648 alphabet") from exc
    if len(decoded) != expected_bytes:
        raise ValueError(f"decoded value must contain exactly {expected_bytes} bytes")
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("base64 value is not canonical")
    return decoded


class BundleContractModel(BaseModel):  # type: ignore[misc]
    """Strict immutable base for all bundle wire models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class IndexContracts(BundleContractModel):
    """Five product values that determine index compatibility."""

    metadata_schema_version: int
    chunking_contract_version: str
    lexical_index_contract_version: str
    embedding_model: str
    embedding_pooling: str


class EmbeddingFingerprint(BundleContractModel):
    """Runtime vector-space fingerprint stored in a bundle."""

    embedding_model: str
    fastembed_version: str
    pooling: str


class RoleSummary(BundleContractModel):
    """Clear non-authoritative size summary for one logical role."""

    role: BundleRole
    present: bool
    bytes: int

    @model_validator(mode="after")  # type: ignore[untyped-decorator]
    def validate_absence_size(self) -> RoleSummary:
        """Require absent roles to advertise zero bytes."""
        if self.bytes < 0 or (not self.present and self.bytes != 0):
            raise ValueError("an absent role must advertise zero bytes")
        return self


class KdfParameters(BundleContractModel):
    """Bounded Argon2id parameters carried by the clear header."""

    name: Literal["argon2id"]
    salt: str
    memory_cost: int
    iterations: int
    lanes: int

    @field_validator("salt")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_salt(cls, value: str) -> str:
        """Require the exact canonical 16-byte salt encoding."""
        decode_canonical_base64(value, SALT_BYTES)
        return value

    @model_validator(mode="after")  # type: ignore[untyped-decorator]
    def validate_cost_bounds(self) -> KdfParameters:
        """Apply the denial-of-service bounds before key derivation."""
        if not 8_192 <= self.memory_cost <= 1_048_576:
            raise ValueError("memory_cost is outside the supported range")
        if not 1 <= self.iterations <= 10:
            raise ValueError("iterations is outside the supported range")
        if not 1 <= self.lanes <= 16:
            raise ValueError("lanes is outside the supported range")
        return self


class CipherParameters(BundleContractModel):
    """Fixed AES-GCM frame parameters carried by the clear header."""

    name: Literal["aes-256-gcm"]
    frame_bytes: Literal[1048576]
    nonce_prefix: str

    @field_validator("nonce_prefix")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_nonce_prefix(cls, value: str) -> str:
        """Require the exact canonical four-byte nonce prefix encoding."""
        decode_canonical_base64(value, NONCE_PREFIX_BYTES)
        return value


class BundleHeader(BundleContractModel):
    """Clear convenience header cryptographically bound to every frame."""

    container_version: Literal[1]
    format: Literal["cortexbundle"]
    created_at: str
    cortex_version: str
    compression: Literal["none"]
    contracts: IndexContracts
    embedding_fingerprint: EmbeddingFingerprint
    roles_summary: tuple[RoleSummary, ...]
    kdf: KdfParameters
    cipher: CipherParameters

    @field_validator("roles_summary", mode="before")  # type: ignore[untyped-decorator]
    @classmethod
    def freeze_roles_summary(cls, value: object) -> object:
        """Convert the JSON array to an immutable tuple before strict validation."""
        return tuple(value) if isinstance(value, list) else value

    @field_validator("created_at")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        """Require an ISO-8601 instant whose offset is UTC."""
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("created_at must be an ISO-8601 UTC instant") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("created_at must use UTC")
        return value

    @field_validator("cortex_version")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_cortex_version(cls, value: str) -> str:
        """Reject an empty producer version."""
        if not value:
            raise ValueError("cortex_version must not be empty")
        return value

    @field_validator("roles_summary")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_role_order(
        cls,
        value: tuple[RoleSummary, ...],
    ) -> tuple[RoleSummary, ...]:
        """Require all six roles in canonical order."""
        if tuple(item.role for item in value) != ROLE_ORDER:
            raise ValueError("roles_summary must contain all roles in canonical order")
        return value


class BundleMember(BundleContractModel):
    """One canonical regular-file member declared by a role."""

    path: str
    bytes: int
    sha256: str

    @field_validator("path")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Require a normalized safe POSIX path relative to its role root."""
        candidate = PurePosixPath(value)
        windows = PureWindowsPath(value)
        if (
            not value
            or value in {".", ".."}
            or candidate.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or value != candidate.as_posix()
            or ".." in candidate.parts
            or ":" in value
            or "\\" in value
            or "\x00" in value
        ):
            raise ValueError("member path must be a normalized safe relative POSIX path")
        return value

    @field_validator("bytes")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_size(cls, value: int) -> int:
        """Reject negative member sizes."""
        if value < 0:
            raise ValueError("member bytes must not be negative")
        return value

    @field_validator("sha256")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        """Require a lowercase SHA-256 hexadecimal digest."""
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("sha256 must contain 64 lowercase hexadecimal characters")
        return value


class BundleRoleManifest(BundleContractModel):
    """Authoritative encrypted declaration for one logical role."""

    role: BundleRole
    present: bool
    reason_absent: str | None
    members: tuple[BundleMember, ...]
    bytes: int
    members_digest: str | None

    @field_validator("members", mode="before")  # type: ignore[untyped-decorator]
    @classmethod
    def freeze_members(cls, value: object) -> object:
        """Convert the JSON member array to an immutable tuple."""
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")  # type: ignore[untyped-decorator]
    def validate_role_invariants(self) -> BundleRoleManifest:
        """Require coherent absence, totals, digest syntax, and member ordering."""
        if tuple(item.path.encode("utf-8") for item in self.members) != tuple(
            sorted(item.path.encode("utf-8") for item in self.members)
        ):
            raise ValueError("members must be sorted by UTF-8 path bytes")
        if len({item.path for item in self.members}) != len(self.members):
            raise ValueError("members must not contain duplicate paths")
        if self.bytes != sum(item.bytes for item in self.members):
            raise ValueError("role bytes must equal the sum of member bytes")
        if not self.present:
            if (
                self.reason_absent is None
                or self.members
                or self.bytes != 0
                or self.members_digest is not None
            ):
                raise ValueError("absent roles must carry only an absence reason")
        elif self.reason_absent is not None or self.members_digest is None:
            raise ValueError("present roles require a members digest and no absence reason")
        if self.members_digest is not None and not _SHA256_PATTERN.fullmatch(
            self.members_digest
        ):
            raise ValueError("members_digest must be a lowercase SHA-256 digest")
        return self


class SourcePaths(BundleContractModel):
    """Encrypted diagnostic paths from the source machine, one per role."""

    chroma: str | None
    lexical: str | None
    ingestion_store: str | None
    config: str | None
    ingestion_config: str | None
    confluence_config: str | None

    @field_validator("*")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_absolute_path(cls, value: str | None) -> str | None:
        """Require either null or an absolute Windows/POSIX source path."""
        if value is None:
            return None
        if not value or not (
            PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()
        ):
            raise ValueError("source paths must be absolute")
        return value


class ExcludedItem(BundleContractModel):
    """One fixed policy exclusion announced by every bundle."""

    item: ExcludedItemName
    reason: str


class BundleManifest(BundleContractModel):
    """Authoritative encrypted portable-bundle manifest."""

    bundle_contract_version: Literal[1]
    created_at: str
    cortex_version: str
    contracts: IndexContracts
    embedding_fingerprint: EmbeddingFingerprint
    source_paths: SourcePaths
    roles: tuple[BundleRoleManifest, ...]
    excluded: tuple[ExcludedItem, ...]

    @field_validator("roles", "excluded", mode="before")  # type: ignore[untyped-decorator]
    @classmethod
    def freeze_manifest_arrays(cls, value: object) -> object:
        """Convert manifest JSON arrays to immutable tuples."""
        return tuple(value) if isinstance(value, list) else value

    @field_validator("created_at")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        """Apply the same UTC timestamp requirement as the clear header."""
        validated = BundleHeader.validate_created_at(value)
        return cast(str, validated)

    @field_validator("cortex_version")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_cortex_version(cls, value: str) -> str:
        """Reject an empty producer version."""
        validated = BundleHeader.validate_cortex_version(value)
        return cast(str, validated)

    @model_validator(mode="after")  # type: ignore[untyped-decorator]
    def validate_manifest_invariants(self) -> BundleManifest:
        """Require canonical roles, matching path presence, and fixed exclusions."""
        if tuple(item.role for item in self.roles) != ROLE_ORDER:
            raise ValueError("roles must contain all roles in canonical order")
        path_values = self.source_paths.model_dump()
        for role in self.roles:
            if role.present != (path_values[role.role] is not None):
                raise ValueError("source_paths nullability must match role presence")
        exclusions = tuple((item.item, item.reason) for item in self.excluded)
        if exclusions != EXCLUDED_ITEMS:
            raise ValueError("excluded must contain the five fixed entries in order")
        return self


class BundleError(BundleContractModel):
    """One path-redacted bundle operation error."""

    code: BundleErrorCode
    phase: str
    path: Literal[None] = None


class BundleDescribeReport(BundleContractModel):
    """Complete machine result for clear bundle description."""

    contract_version: Literal[1] = BUNDLE_CONTRACT_VERSION
    operation: Literal["bundle_describe"] = "bundle_describe"
    status: Literal["succeeded", "failed"]
    error: BundleError | None
    restart_required: Literal[False] = False
    authenticated: Literal[False] | None
    claimed_compatible: bool | None
    created_at: str | None
    cortex_version: str | None
    roles_summary: tuple[RoleSummary, ...] | None


class BundleVerifyReport(BundleContractModel):
    """Complete machine result for authenticated bundle verification."""

    contract_version: Literal[1] = BUNDLE_CONTRACT_VERSION
    operation: Literal["bundle_verify"] = "bundle_verify"
    status: Literal["succeeded", "failed"]
    error: BundleError | None
    restart_required: Literal[False] = False
    authenticated: Literal[True] | None
    compatible: bool | None
    header_matches_manifest: bool | None
    members_verified: bool | None
    roles: tuple[BundleRoleManifest, ...] | None


def local_index_contracts() -> IndexContracts:
    """Return current product contracts without importing user configuration."""
    return IndexContracts(
        metadata_schema_version=METADATA_SCHEMA_VERSION,
        chunking_contract_version=CHUNKING_CONTRACT_VERSION,
        lexical_index_contract_version=LEXICAL_INDEX_CONTRACT_VERSION,
        embedding_model=EMBEDDING_MODEL,
        embedding_pooling=EMBEDDING_POOLING,
    )


__all__ = [
    "BUNDLE_COMPRESSION",
    "BUNDLE_CONTRACT_VERSION",
    "BUNDLE_FORMAT",
    "CIPHER_NAME",
    "CONTAINER_VERSION",
    "EXCLUDED_ITEMS",
    "FRAME_BYTES",
    "KDF_NAME",
    "MAX_ENCRYPTED_FRAME_BYTES",
    "MAX_HEADER_BYTES",
    "MAX_MANIFEST_BYTES",
    "NONCE_PREFIX_BYTES",
    "ROLE_ORDER",
    "SALT_BYTES",
    "BundleDescribeReport",
    "BundleError",
    "BundleErrorCode",
    "BundleHeader",
    "BundleManifest",
    "BundleMember",
    "BundleRole",
    "BundleRoleManifest",
    "BundleVerifyReport",
    "CipherParameters",
    "EmbeddingFingerprint",
    "ExcludedItem",
    "IndexContracts",
    "KdfParameters",
    "RoleSummary",
    "SourcePaths",
    "decode_canonical_base64",
    "local_index_contracts",
]
