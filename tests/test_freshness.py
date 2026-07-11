# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Tests for the autonomous freshness contract and read-only report."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import freshness
import pytest
from config import FRESHNESS_CONTRACT_ID, FRESHNESS_CONTRACT_VERSION
from chunker_utils import sha256_bytes


class FakeCollection:
    def __init__(self, metadatas: list[dict[str, Any]]) -> None:
        self.metadatas = metadatas
        self.calls = 0

    def get(self, **_kwargs: object) -> dict[str, list[dict[str, Any]]]:
        self.calls += 1
        return {"metadatas": self.metadatas if self.calls == 1 else []}


def test_shared_vectors_hash_exact_written_bytes(tmp_path: Path) -> None:
    manifest_path = Path(__file__).parent / "fixtures" / "freshness-contract-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["contract"] == FRESHNESS_CONTRACT_ID
    for vector in manifest["vectors"]:
        target = tmp_path / f"{vector['id']}.md"
        target.write_bytes(base64.b64decode(vector["base64"], validate=True))
        assert sha256_bytes(target.read_bytes()) == vector["sha256"]


def test_freshness_taxonomy_is_read_only_and_autonomous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    memory = root / "_memory"
    memory.mkdir(parents=True)
    fresh = memory / "fresh.md"
    stale = memory / "stale.md"
    unknown = memory / "unknown.md"
    fresh.write_bytes(b"# Fresh\r\nbody\r\n")
    stale.write_bytes(b"# Stale\nbody\n")
    unknown.write_bytes(b"# Unknown\nbody\n")
    fresh_hash = sha256_bytes(fresh.read_bytes())
    collection = FakeCollection(
        [
            {
                "path": "_memory\\fresh.md",
                "content_hash": fresh_hash,
                "contract_id": FRESHNESS_CONTRACT_ID,
                "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
            },
            {
                "path": "_memory/stale.md",
                "content_hash": "0" * 64,
                "contract_id": FRESHNESS_CONTRACT_ID,
                "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
            },
            {"path": "_memory/unknown.md", "file_hash": "legacy"},
            {
                "path": "_memory/missing.md",
                "content_hash": "1" * 64,
                "contract_id": FRESHNESS_CONTRACT_ID,
                "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
            },
            {
                "path": "_memory/_archive/old.md",
                "content_hash": "3" * 64,
                "contract_id": FRESHNESS_CONTRACT_ID,
                "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
            },
            {"path": "../escape.md", "content_hash": "2" * 64},
        ]
    )
    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    report = freshness.cortex_freshness_report(collection, section="_memory")

    statuses = {entry["path"]: entry["status"] for entry in report["entries"]}
    assert statuses["_memory/fresh.md"] == "fresh"
    assert statuses["_memory/stale.md"] == "stale"
    assert statuses["_memory/unknown.md"] == "unknown"
    assert statuses["_memory/missing.md"] == "missing"
    # Regression guard: an indexed-but-off-disk path under an excluded dir
    # must report "excluded", not "missing" - this is the exact branch
    # (freshness.py's is_excluded_path check in the leftover-indexed loop)
    # that previously crashed with NameError (orphaned "_is_excluded" call).
    assert statuses["_memory/_archive/old.md"] == "excluded"
    assert statuses["../escape.md"] == "error"
    assert report["read_only"] is True
    assert report["freshness_is_not_completeness"] is True


def test_strict_decode_and_containment_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir()
    invalid = root / "invalid.md"
    invalid.write_bytes(b"\xff")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")

    try:
        freshness.read_markdown_snapshot(invalid, root)
    except UnicodeDecodeError:
        pass
    else:
        raise AssertionError("invalid UTF-8 must fail strictly")
    try:
        freshness.read_markdown_snapshot(outside, root)
    except ValueError:
        pass
    else:
        raise AssertionError("outside source must be rejected")


def test_controlled_byte_mutations_have_no_false_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    memory = root / "_memory"
    memory.mkdir(parents=True)
    manifest_path = Path(__file__).parent / "fixtures" / "freshness-contract-v1.json"
    vectors = json.loads(manifest_path.read_text(encoding="utf-8"))["vectors"]
    metadatas: list[dict[str, Any]] = []
    for vector in vectors:
        target = memory / f"{vector['id']}.md"
        target.write_bytes(base64.b64decode(vector["base64"], validate=True))
        metadatas.append(
            {
                "path": f"_memory/{target.name}",
                "content_hash": vector["sha256"],
                "contract_id": FRESHNESS_CONTRACT_ID,
                "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
            }
        )
    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    fresh = freshness.cortex_freshness_report(
        FakeCollection(metadatas), section="_memory"
    )
    assert {entry["status"] for entry in fresh["entries"]} == {"fresh"}

    for vector in vectors:
        target = memory / f"{vector['id']}.md"
        target.write_bytes(target.read_bytes() + b"x")
    stale = freshness.cortex_freshness_report(
        FakeCollection(metadatas), section="_memory"
    )
    assert {entry["status"] for entry in stale["entries"]} == {"stale"}
