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
"""Atomic persisted storage for ingestion generations and health."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from ingestion.constants import (
    CURRENT_POINTER_FILE_NAME,
    DOCUMENTS_DIRECTORY_NAME,
    GENERATIONS_DIRECTORY_NAME,
    HEALTH_FILE_NAME,
    LOCK_FILE_NAME,
    MANIFEST_FILE_NAME,
    PENDING_PREFIX,
    SCHEMA_VERSION,
    TEMPORARY_FILE_SUFFIX,
)
from ingestion.models import CurrentGenerationPointer, GenerationManifest, SourceHealth

_LOG = logging.getLogger("cortex.ingestion.storage")
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ModelT = TypeVar("ModelT", bound=BaseModel)


class IngestionStorageError(RuntimeError):
    """Raised when persisted ingestion state is invalid or unsafe."""


def _validate_component(value: str, label: str) -> str:
    if not _SAFE_COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise IngestionStorageError(f"{label} must be a safe single path component")
    return value


def _atomic_write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    payload = model.model_dump_json(indent=2) + "\n"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=TEMPORARY_FILE_SUFFIX,
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _read_model(path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cast(ModelT, model_type.model_validate(payload))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise IngestionStorageError(f"Invalid persisted ingestion state at '{path}'.") from exc


class IngestionStorage:
    """Own one source kind's generation pointer, health, and retention."""

    def __init__(self, root: Path, source_kind: str, retention_generations: int) -> None:
        """Initialize storage without creating or mutating persisted state."""
        if retention_generations < 1:
            raise ValueError("retention_generations must be at least one")
        self.root = Path(root)
        self.source_kind = _validate_component(source_kind, "source_kind")
        self.retention_generations = retention_generations

    @property
    def source_root(self) -> Path:
        """Return the isolated root for this source kind."""
        return self.root / self.source_kind

    @property
    def generations_root(self) -> Path:
        """Return the directory containing immutable generations."""
        return self.source_root / GENERATIONS_DIRECTORY_NAME

    @property
    def current_pointer_path(self) -> Path:
        """Return the atomically replaced current-generation pointer path."""
        return self.source_root / CURRENT_POINTER_FILE_NAME

    @property
    def health_path(self) -> Path:
        """Return the atomically replaced health path."""
        return self.source_root / HEALTH_FILE_NAME

    @property
    def lock_path(self) -> Path:
        """Return the source-specific anti-overlap lock path."""
        return self.source_root / LOCK_FILE_NAME

    def generation_path(self, generation_id: str) -> Path:
        """Return a validated immutable generation path."""
        return self.generations_root / _validate_component(generation_id, "generation_id")

    def pending_generation_path(self, generation_id: str) -> Path:
        """Return a temporary path whose name ends with the generation ID."""
        validated = _validate_component(generation_id, "generation_id")
        return self.generations_root / f"{PENDING_PREFIX}{validated}"

    def document_path(self, generation_id: str, relative_path: str) -> Path:
        """Resolve a manifest document path inside one generation."""
        candidate = self.generation_path(generation_id) / DOCUMENTS_DIRECTORY_NAME / relative_path
        resolved_root = (self.generation_path(generation_id) / DOCUMENTS_DIRECTORY_NAME).resolve()
        resolved_candidate = candidate.resolve()
        if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
            raise IngestionStorageError("document path escapes its generation")
        return candidate

    def current_generation_id(self) -> str | None:
        """Read the currently served generation ID, if any."""
        if not self.current_pointer_path.exists():
            return None
        return _read_model(
            self.current_pointer_path,
            CurrentGenerationPointer,
        ).generation_id

    def load_current_manifest(self) -> GenerationManifest | None:
        """Load the immutable manifest selected by the current pointer."""
        generation_id = self.current_generation_id()
        if generation_id is None:
            return None
        return self.load_manifest(generation_id)

    def load_manifest(self, generation_id: str) -> GenerationManifest:
        """Load and validate one immutable generation manifest."""
        path = self.generation_path(generation_id) / MANIFEST_FILE_NAME
        manifest = _read_model(path, GenerationManifest)
        if manifest.generation_id != generation_id:
            raise IngestionStorageError("manifest generation_id does not match its directory")
        return manifest

    def load_health(self) -> SourceHealth | None:
        """Load the most recent atomic health state, if present."""
        if not self.health_path.exists():
            return None
        health = _read_model(self.health_path, SourceHealth)
        if health.source_kind != self.source_kind:
            raise IngestionStorageError("source-health source_kind does not match its directory")
        return health

    def write_health(self, health: SourceHealth) -> None:
        """Atomically replace health for every attempted run."""
        if health.source_kind != self.source_kind:
            raise IngestionStorageError("cannot write health for another source kind")
        _atomic_write_model(self.health_path, health)
        _LOG.info(
            "ingestion_health_written source_kind=%s status=%s error_code=%s",
            self.source_kind,
            health.status.value,
            health.error_code,
        )

    def create_pending_generation(self, generation_id: str) -> Path:
        """Create a new empty temporary generation directory."""
        path = self.pending_generation_path(generation_id)
        if path.exists() or self.generation_path(generation_id).exists():
            raise IngestionStorageError("generation_id already exists")
        (path / DOCUMENTS_DIRECTORY_NAME).mkdir(parents=True)
        return path

    def publish_pending_generation(
        self,
        generation_id: str,
        manifest: GenerationManifest,
        *,
        before_pointer_switch: Callable[[], None] | None = None,
    ) -> None:
        """Finalize a generation, then atomically switch the served pointer."""
        if manifest.generation_id != generation_id:
            raise IngestionStorageError("manifest generation_id does not match publication")
        pending = self.pending_generation_path(generation_id)
        final = self.generation_path(generation_id)
        if not pending.is_dir() or final.exists():
            raise IngestionStorageError("pending generation is missing or already published")
        manifest_path = pending / MANIFEST_FILE_NAME
        if manifest_path.exists():
            raise IngestionStorageError("manifest already exists in pending generation")
        _atomic_write_model(manifest_path, manifest)
        os.replace(pending, final)
        if before_pointer_switch is not None:
            before_pointer_switch()
        _atomic_write_model(
            self.current_pointer_path,
            CurrentGenerationPointer(
                schema_version=SCHEMA_VERSION,
                generation_id=generation_id,
            ),
        )
        self.purge_old_generations(dry_run=False)
        _LOG.info(
            "ingestion_generation_published source_kind=%s generation_id=%s documents=%d "
            "tombstones=%d",
            self.source_kind,
            generation_id,
            len(manifest.documents),
            len(manifest.tombstones),
        )

    def purge_old_generations(self, *, dry_run: bool) -> tuple[Path, ...]:
        """Plan or remove generations older than the configured retention."""
        if not self.generations_root.exists():
            return ()
        current = self.current_generation_id()
        published = [
            path
            for path in self.generations_root.iterdir()
            if path.is_dir() and not path.name.startswith(PENDING_PREFIX)
        ]
        published.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
        keep = {path.name for path in published[: self.retention_generations]}
        if current is not None:
            keep.add(current)
        targets = tuple(path for path in published if path.name not in keep)
        for target in targets:
            if target.parent.resolve() != self.generations_root.resolve():
                raise IngestionStorageError("retention target escaped the generations root")
            if not dry_run:
                shutil.rmtree(target)
                _LOG.info(
                    "ingestion_generation_purged source_kind=%s generation_id=%s",
                    self.source_kind,
                    target.name,
                )
        return targets

    def discard_pending_generation(self, generation_id: str) -> None:
        """Remove only the exact temporary generation owned by a failed attempt."""
        path = self.pending_generation_path(generation_id)
        if path.exists():
            if path.parent.resolve() != self.generations_root.resolve():
                raise IngestionStorageError("pending generation escaped the generations root")
            shutil.rmtree(path)


__all__ = ["IngestionStorage", "IngestionStorageError"]
