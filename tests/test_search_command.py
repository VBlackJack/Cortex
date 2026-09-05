# Copyright 2026 Julien Bombled
# Licensed under the Apache License, Version 2.0.
"""Desktop search contract and safe source opening tests."""

import json
from pathlib import Path

import pytest

import indexer
from search_command import EXCERPT_LIMIT, emit_search, present_hit, safe_document_path


def test_open_target_rejects_escape_and_executable(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir()
    (tmp_path / "outside.md").write_text("outside")
    (root / "run.exe").write_text("not a document")
    (root / "ok.md").write_text("document")
    assert safe_document_path(root, "../outside.md") is None
    assert safe_document_path(root, "run.exe") is None
    assert safe_document_path(root, "ok.md") == str(root / "ok.md")


def test_result_bounds_content_and_rejects_credentials_in_url() -> None:
    hit = present_hit(
        {
            "id": "id",
            "text": "x" * 5000,
            "metadata": {"source_url": "https://user:secret@example.org/a"},
        },
        None,
    )
    assert len(hit["excerpt"]) == EXCERPT_LIMIT
    assert hit["open_target"] is None


def test_json_envelope_preserves_degradation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("reranker.warmup_reranker", lambda: None)
    monkeypatch.setattr(
        indexer,
        "search",
        lambda *a, **kw: indexer.SearchResults(
            [{"id": "a", "text": "answer", "metadata": {}}],
            mode="vector-only",
            fallback_reason="unavailable",
        ),
    )
    assert emit_search("test", None, 5, None) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["contract_version"] == 1
    assert report["degraded"] is True
    assert len(report["results"]) == 1
