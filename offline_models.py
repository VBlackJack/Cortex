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
"""Manifest-gated runtime for stable, integrity-checked model caches.

The cache-root ``manifest.json`` uses this versioned shape::

    {
      "schema_version": 1,
      "files": {"relative/posix/path": "lowercase-sha256"}
    }

Every declared path must stay below the cache root. Extra top-level keys are
reserved for C2 model metadata and do not change the integrity contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import cast

from user_config import local_data_home

MANIFEST_FILENAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OfflineModelsError(RuntimeError):
    """Base error for an unusable embedded model payload."""


class ModelManifestError(OfflineModelsError):
    """Raised when an embedded model manifest or payload is invalid."""


@dataclass(frozen=True)
class ModelRuntime:
    """Resolved FastEmbed cache and network policy for this process."""

    cache_dir: Path
    embedded: bool
    manifest_path: Path | None

    @property
    def local_files_only(self) -> bool:
        """Prevent FastEmbed network access only for verified embedded payloads."""
        return self.embedded


_VERIFIED_RUNTIMES: dict[Path, ModelRuntime] = {}
_RUNTIME_LOCK = Lock()


def model_cache_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the single stable cache root shared by all model consumers."""
    return local_data_home(environ) / "models"


def _manifest_entries(manifest_path: Path) -> list[tuple[str, str]]:
    try:
        raw_manifest: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelManifestError(
            f"Embedded model manifest '{manifest_path}' could not be read: {exc}"
        ) from exc
    if not isinstance(raw_manifest, dict):
        raise ModelManifestError(
            f"Embedded model manifest '{manifest_path}' must contain a JSON object."
        )
    manifest = cast(dict[str, object], raw_manifest)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ModelManifestError(
            f"Embedded model manifest '{manifest_path}' has unsupported schema_version; "
            f"expected {MANIFEST_SCHEMA_VERSION}."
        )
    raw_files = manifest.get("files")
    if not isinstance(raw_files, dict) or not raw_files:
        raise ModelManifestError(
            f"Embedded model manifest '{manifest_path}' must declare at least one file."
        )

    entries: list[tuple[str, str]] = []
    for raw_path, raw_digest in raw_files.items():
        if not isinstance(raw_path, str) or not isinstance(raw_digest, str):
            raise ModelManifestError(
                f"Embedded model manifest '{manifest_path}' has a non-string file entry."
            )
        relative = PurePosixPath(raw_path)
        if (
            not raw_path
            or "\\" in raw_path
            or relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or ":" in relative.parts[0]
        ):
            raise ModelManifestError(
                f"Embedded model manifest '{manifest_path}' contains unsafe path '{raw_path}'."
            )
        digest = raw_digest.lower()
        if _SHA256_RE.fullmatch(digest) is None:
            raise ModelManifestError(
                f"Embedded model manifest '{manifest_path}' contains an invalid SHA-256 "
                f"for '{raw_path}'."
            )
        entries.append((raw_path, digest))
    return entries


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(cache_dir: Path) -> Path:
    """Verify every manifest entry locally and return the manifest path."""
    cache_root = Path(cache_dir).resolve()
    manifest_path = cache_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ModelManifestError(
            f"Embedded model manifest is missing or is not a file: '{manifest_path}'."
        )

    for relative_path, expected_digest in _manifest_entries(manifest_path):
        candidate = cache_root.joinpath(*PurePosixPath(relative_path).parts)
        resolved = candidate.resolve()
        try:
            resolved.relative_to(cache_root)
        except ValueError as exc:
            raise ModelManifestError(
                f"Embedded model file escapes the cache root: '{relative_path}'."
            ) from exc
        if not resolved.is_file():
            raise ModelManifestError(
                f"Embedded model file declared by '{manifest_path}' is missing: '{relative_path}'."
            )
        try:
            actual_digest = _sha256(resolved)
        except OSError as exc:
            raise ModelManifestError(
                f"Embedded model file '{relative_path}' could not be read: {exc}"
            ) from exc
        if actual_digest != expected_digest:
            raise ModelManifestError(
                f"Embedded model file '{relative_path}' failed SHA-256 verification: "
                f"expected {expected_digest}, got {actual_digest}."
            )
    return manifest_path


def activate_if_embedded(
    environ: MutableMapping[str, str] | None = None,
) -> ModelRuntime:
    """Verify an embedded payload and enforce offline mode before ML imports."""
    values = os.environ if environ is None else environ
    cache_root = model_cache_dir(values).resolve()
    manifest_path = cache_root / MANIFEST_FILENAME
    if not manifest_path.exists():
        return ModelRuntime(cache_root, embedded=False, manifest_path=None)

    with _RUNTIME_LOCK:
        runtime = _VERIFIED_RUNTIMES.get(cache_root)
        if runtime is None:
            verified_manifest = verify_manifest(cache_root)
            runtime = ModelRuntime(
                cache_root,
                embedded=True,
                manifest_path=verified_manifest,
            )
            _VERIFIED_RUNTIMES[cache_root] = runtime
    values["HF_HUB_OFFLINE"] = "1"
    return runtime


def _reset_for_tests() -> None:
    """Forget process-local verification results between isolated tests."""
    with _RUNTIME_LOCK:
        _VERIFIED_RUNTIMES.clear()


__all__ = [
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "ModelManifestError",
    "ModelRuntime",
    "OfflineModelsError",
    "activate_if_embedded",
    "model_cache_dir",
    "verify_manifest",
]
