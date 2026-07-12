# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Centralized Chroma client creation with telemetry disabled."""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings


def create_persistent_client(path: str | Path) -> chromadb.PersistentClient:
    """Create a local persistent client with anonymized telemetry disabled."""
    return chromadb.PersistentClient(
        path=str(path),
        settings=Settings(anonymized_telemetry=False),
    )
