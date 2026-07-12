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


def test_whole_vault_scan_restricted_to_included_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """section=None (whole vault) must only scan INCLUDED_SECTIONS folders -
    an out-of-policy dir (neither included nor structurally excluded) must
    not be silently treated as a normal section (no per-file fresh/
    unindexed status), but must still be surfaced as present."""
    root = tmp_path / "kb"
    included = root / "knowledge"
    included.mkdir(parents=True)
    (included / "note.md").write_bytes(b"# Note\nReal content long enough to chunk.\n")

    excluded = root / "_archive"
    excluded.mkdir(parents=True)
    (excluded / "old.md").write_bytes(b"# Old\nArchived content.\n")

    unknown = root / "newthing"
    unknown.mkdir(parents=True)
    (unknown / "mystery.md").write_bytes(b"# Mystery\nUnclassified content.\n")

    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    report = freshness.cortex_freshness_report(FakeCollection([]), section=None)

    statuses = {entry["path"]: entry["status"] for entry in report["entries"]}
    assert statuses["knowledge/note.md"] == "unindexed"
    assert statuses["_archive/old.md"] == "excluded"
    assert "newthing/mystery.md" not in statuses
    assert "newthing" in report["scope"]["out_of_policy_dirs"]


def test_no_chunks_is_distinct_from_unindexed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    drafts = root / "_drafts"
    drafts.mkdir(parents=True)
    empty_index_page = drafts / "index-stub.md"
    real_gap = drafts / "real-draft.md"
    empty_index_page.write_bytes(b"# Stub\n")
    real_gap.write_bytes(b"# Real draft\nThis body is long enough to chunk.\n")
    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    report = freshness.cortex_freshness_report(FakeCollection([]), section="_drafts")

    statuses = {entry["path"]: entry["status"] for entry in report["entries"]}
    assert statuses["_drafts/index-stub.md"] == "no_chunks"
    assert statuses["_drafts/real-draft.md"] == "unindexed"


def test_summary_mode_omits_per_file_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    (section / "note.md").write_bytes(
        b"# Note\nThis body is long enough to be an unindexed source.\n"
    )
    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    report = freshness.cortex_freshness_report(
        FakeCollection([]),
        section="knowledge",
        include_entries=False,
    )

    assert report["summary"] == {"unindexed": 1}
    assert "entries" not in report


def test_classify_hash_fresh_stale_unknown() -> None:
    coherent_meta = [
        {
            "content_hash": "a" * 64,
            "contract_id": FRESHNESS_CONTRACT_ID,
            "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
        }
    ]
    assert freshness.classify_hash("a" * 64, coherent_meta) == "fresh"
    assert freshness.classify_hash("b" * 64, coherent_meta) == "stale"
    # Legacy row: no contract fields at all.
    assert freshness.classify_hash("a" * 64, [{"file_hash": "legacy"}]) == "unknown"
    # Contract id/version mismatch.
    mismatched = [
        {
            "content_hash": "a" * 64,
            "contract_id": "some-other-contract",
            "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
        }
    ]
    assert freshness.classify_hash("a" * 64, mismatched) == "unknown"


def test_annotate_search_hits_fresh_and_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    note = section / "note.md"
    note.write_bytes(b"# Note\nbody content here.\n")
    live_hash = sha256_bytes(note.read_bytes())
    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    fresh_hit = {
        "text": "chunk text",
        "metadata": {
            "path": "knowledge/note.md",
            "content_hash": live_hash,
            "contract_id": FRESHNESS_CONTRACT_ID,
            "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
        },
        "distance": 0.1,
    }
    hits = freshness.annotate_search_hits([dict(fresh_hit)])
    assert hits[0]["freshness"] == "fresh"

    note.write_bytes(note.read_bytes() + b"more\n")
    hits = freshness.annotate_search_hits([dict(fresh_hit)])
    assert hits[0]["freshness"] == "stale"


def test_pdf_freshness_hashes_bytes_without_utf8_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    pdf = section / "binary.pdf"
    pdf.write_bytes(b"%PDF-\xff\x00binary")
    content_hash = sha256_bytes(pdf.read_bytes())
    metadata = {
        "path": "knowledge/binary.pdf",
        "content_hash": content_hash,
        "contract_id": FRESHNESS_CONTRACT_ID,
        "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
    }
    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    report = freshness.cortex_freshness_report(
        FakeCollection([metadata]), section="knowledge"
    )
    hits = freshness.annotate_search_hits([{"metadata": metadata}])

    assert report["entries"] == [
        {"path": "knowledge/binary.pdf", "status": "fresh", "chunks": "1"}
    ]
    assert hits[0]["freshness"] == "fresh"


def test_annotate_search_hits_missing_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    root.mkdir()
    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    missing_hit = {"metadata": {"path": "knowledge/gone.md", "content_hash": "a" * 64}}
    outside_hit = {"metadata": {"path": "../escape.md", "content_hash": "a" * 64}}
    malformed_hit = {"metadata": {"path": None}}

    hits = freshness.annotate_search_hits(
        [dict(missing_hit), dict(outside_hit), dict(malformed_hit)]
    )
    assert hits[0]["freshness"] == "missing"
    assert hits[1]["freshness"] == "error"
    assert hits[2]["freshness"] == "error"


def test_search_annotation_without_kb_keeps_hits_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freshness, "KB_PATH", None)
    hits = [{"text": "indexed content", "metadata": {"path": "knowledge/note.md"}}]

    annotated = freshness.annotate_search_hits(hits)

    assert annotated[0]["text"] == "indexed content"
    assert annotated[0]["freshness"] == "unavailable"


def test_annotate_search_hits_dedups_shared_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    section = root / "knowledge"
    section.mkdir(parents=True)
    note = section / "shared.md"
    note.write_bytes(b"# Shared\nbody content here.\n")
    live_hash = sha256_bytes(note.read_bytes())
    monkeypatch.setattr(freshness, "KB_PATH", str(root))

    calls = {"count": 0}
    original = freshness.read_markdown_snapshot

    def counting_snapshot(path: Path, kb_root: Path) -> freshness.FileSnapshot:
        calls["count"] += 1
        return original(path, kb_root)

    monkeypatch.setattr(freshness, "read_markdown_snapshot", counting_snapshot)

    metadata = {
        "path": "knowledge/shared.md",
        "content_hash": live_hash,
        "contract_id": FRESHNESS_CONTRACT_ID,
        "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
    }
    hits = [
        {"metadata": dict(metadata), "distance": 0.1},
        {"metadata": dict(metadata), "distance": 0.2},
        {"metadata": dict(metadata), "distance": 0.3},
    ]
    annotated = freshness.annotate_search_hits(hits)

    assert calls["count"] == 1
    assert all(hit["freshness"] == "fresh" for hit in annotated)


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
