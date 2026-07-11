# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Transactional ordering tests for B2 hash-aware file publication."""

from __future__ import annotations

import pytest

from config import FRESHNESS_CONTRACT_ID, FRESHNESS_CONTRACT_VERSION
from sync_hash_aware import sync_file


class Collection:
    def __init__(self, fail_upsert: bool = False) -> None:
        self.fail_upsert = fail_upsert
        self.events: list[str] = []

    def upsert(self, **_kwargs: object) -> None:
        self.events.append("upsert")
        if self.fail_upsert:
            raise RuntimeError("interrupted")

    def delete(self, **_kwargs: object) -> None:
        self.events.append("delete")


def _chunks() -> list[dict[str, object]]:
    return [
        {
            "id": "note.md::0",
            "text": "text",
            "metadata": {
                "content_hash": "a" * 64,
                "contract_id": FRESHNESS_CONTRACT_ID,
                "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
            },
        }
    ]


def test_interrupted_upsert_never_deletes_old_chunks() -> None:
    collection = Collection(fail_upsert=True)
    with pytest.raises(RuntimeError, match="interrupted"):
        sync_file(collection, _chunks(), ["old::0"])
    assert collection.events == ["upsert"]


def test_repeated_publish_is_idempotent() -> None:
    collection = Collection()
    sync_file(collection, _chunks(), ["note.md::0"])
    sync_file(collection, _chunks(), ["note.md::0"])
    assert collection.events == ["upsert", "upsert"]
