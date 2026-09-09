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


@pytest.mark.parametrize("mode", ["vector", "hybrid", "rerank"])
@pytest.mark.parametrize("json_output", [False, True])
def test_console_search_routes_the_explicit_strategy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    mode: str, json_output: bool,
) -> None:
    calls = []

    def search(*args: object, **kwargs: object) -> indexer.SearchResults:
        calls.append(kwargs)
        return indexer.SearchResults([], mode="vector-only")

    monkeypatch.setattr(indexer, "search", search)
    arguments = ["test", "--retrieval-mode", mode] + (["--json"] if json_output else [])
    assert indexer.search_main(arguments) == 0
    assert calls[0]["retrieval_mode"] == mode
    capsys.readouterr()


def test_default_json_search_does_not_warm_the_unused_reranker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.test_indexer_search import Collection

    monkeypatch.setattr(indexer, "get_collection", Collection)
    monkeypatch.setattr(indexer, "warmup_reranker", lambda: pytest.fail("unused reranker"))
    monkeypatch.setattr(indexer, "LexicalIndex", lambda: pytest.fail("unused lexical index"))
    assert emit_search("question", None, 5, None) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "vector-only"
    assert payload["degraded"] is False
