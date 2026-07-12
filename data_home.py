# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Fail-closed migration from the repository index to the user data home."""

from __future__ import annotations

import logging
import os
from pathlib import Path

_LOG = logging.getLogger("cortex.data_home")


class CortexDataHomeError(RuntimeError):
    """Base error for an unsafe or incomplete Cortex data-home transition."""


class LegacyDataMigrationRequiredError(CortexDataHomeError):
    """Raised when the legacy index must move before Cortex can open Chroma."""


class DataHomeConflictError(CortexDataHomeError):
    """Raised when both legacy and configured indexes exist."""


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def migration_state(legacy_path: Path, target_path: Path) -> str:
    """Return configured_legacy, conflict, required, ready or empty."""
    legacy = Path(legacy_path)
    target = Path(target_path)
    if _same_path(legacy, target):
        return "configured_legacy"
    legacy_exists = legacy.exists()
    target_exists = target.exists()
    if legacy_exists and target_exists:
        return "conflict"
    if legacy_exists:
        return "required"
    if target_exists:
        return "ready"
    return "empty"


def ensure_index_location(legacy_path: Path, target_path: Path) -> None:
    """Refuse to open Chroma when migration is required or ambiguous."""
    state = migration_state(legacy_path, target_path)
    if state == "required":
        raise LegacyDataMigrationRequiredError(
            f"Legacy Cortex index found at '{legacy_path}', while the configured "
            f"data home is '{target_path}'. Run `python setup_config.py "
            "--migrate-data` to move it before search or sync. Cortex will not "
            "create a second active index."
        )
    if state == "conflict":
        raise DataHomeConflictError(
            f"Both the legacy Cortex index '{legacy_path}' and configured index "
            f"'{target_path}' exist. Refusing to choose or merge them. Keep one "
            "authoritative index, move the other aside, then retry."
        )


def move_legacy_index(legacy_path: Path, target_path: Path) -> bool:
    """Atomically rename the legacy index; never fall back to copying."""
    legacy = Path(legacy_path)
    target = Path(target_path)
    state = migration_state(legacy, target)
    if state in {"configured_legacy", "ready", "empty"}:
        return False
    if state == "conflict":
        raise DataHomeConflictError(
            f"Cannot migrate because target '{target}' already exists while "
            f"legacy index '{legacy}' is still present. Nothing was changed."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(legacy, target)
    except OSError as exc:
        raise CortexDataHomeError(
            f"Could not atomically move '{legacy}' to '{target}': {exc}. Cortex "
            "does not silently copy indexes. If the paths are on different "
            "volumes, move the directory manually while all Cortex clients are "
            "closed, or configure chroma_path on the legacy volume."
        ) from exc
    _LOG.warning(
        "legacy_index_moved source=%s target=%s rollback=move_directory_back",
        legacy,
        target,
    )
    return True
