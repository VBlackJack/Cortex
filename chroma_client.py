# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Centralized Chroma client creation with telemetry disabled."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings


def create_persistent_client(path: str | Path) -> chromadb.PersistentClient:
    """Create a local persistent client with anonymized telemetry disabled."""
    return chromadb.PersistentClient(
        path=str(path),
        settings=Settings(anonymized_telemetry=False),
    )


def iter_collection_pages(
    collection: Any,
    *,
    page_size: int = 5_000,
    **get_kwargs: Any,
) -> Iterator[dict[str, Any]]:
    """Yield Chroma get() pages and let collection errors reach the caller."""
    if page_size <= 0:
        raise ValueError("page_size must be greater than zero")
    offset = 0
    while True:
        page: dict[str, Any] = collection.get(
            limit=page_size,
            offset=offset,
            **get_kwargs,
        )
        yield page
        ids = page.get("ids")
        page_items = ids if isinstance(ids, list) else page.get("metadatas") or []
        if len(page_items) < page_size:
            return
        offset += page_size
