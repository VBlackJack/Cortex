# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Unit tests for chunker.py — boundary cases and invariants.
"""

import hashlib
import importlib
from pathlib import Path

import pytest

from chunker import (
    MAX_CHARS,
    MAX_FILE_SIZE_BYTES,
    _parse_frontmatter,
    _split_by_headers,
    _split_fixed_size,
    chunk_markdown_file,
)
from chunker_utils import split_fixed_size, split_fixed_size_spans

# ── _split_fixed_size ─────────────────────────────────────────────────────────


def test_split_fixed_size_empty_returns_empty():
    assert _split_fixed_size("", 100, 10) == []


def test_split_fixed_size_whitespace_only_returns_empty():
    assert _split_fixed_size("   \n  ", 100, 10) == []


def test_split_fixed_size_shorter_than_max_returns_single():
    text = "hello world"
    assert _split_fixed_size(text, 100, 10) == [text]


def test_split_fixed_size_one_char():
    assert _split_fixed_size("x", 100, 10) == ["x"]


@pytest.mark.parametrize(
    ("max_chars", "overlap_chars"),
    [(0, 0), (-1, 0), (10, -1), (10, 10), (10, 20)],
)
def test_split_fixed_size_rejects_invalid_config(
    max_chars: int, overlap_chars: int
) -> None:
    with pytest.raises(ValueError):
        _split_fixed_size("a" * 50, max_chars, overlap_chars)


def test_split_fixed_size_breaks_on_newline():
    text = ("x" * 45) + "\n" + ("y" * 100)
    chunks = _split_fixed_size(text, max_chars=50, overlap_chars=5)
    assert chunks[0] == "x" * 45


def test_split_fixed_size_breaks_on_sentence_when_no_newline():
    text = ("x" * 25) + ". " + ("y" * 100)
    chunks = _split_fixed_size(text, max_chars=30, overlap_chars=5)
    assert chunks[0] == ("x" * 25) + "."


def test_split_fixed_size_no_natural_boundary_falls_back_to_hard_cut():
    text = "x" * 100
    chunks = _split_fixed_size(text, max_chars=20, overlap_chars=5)
    assert len(chunks) >= 5
    assert all(len(c) <= 20 for c in chunks)


def test_split_fixed_size_rejects_boundary_inside_existing_overlap() -> None:
    text = "abcdefgh\n" + ("x" * 30)
    chunks = _split_fixed_size(text, max_chars=10, overlap_chars=4)
    assert chunks[1] == "fgh\nxxxxxx"
    assert "fgh" not in chunks


def test_split_fixed_size_boundary_floor_is_inclusive() -> None:
    accepted = ("x" * 15) + "\n" + ("y" * 40)
    rejected = ("x" * 14) + "\n" + ("y" * 40)
    assert _split_fixed_size(accepted, 20, 5)[0] == "x" * 15
    assert len(_split_fixed_size(rejected, 20, 5)[0]) == 20


def test_split_fixed_size_configured_progress_is_at_least_384() -> None:
    text = (("x" * 448) + "\n") * 5
    spans = split_fixed_size_spans(text, max_chars=512, overlap_chars=64)
    starts = [start for start, _ in spans]
    assert all(current - previous >= 384 for previous, current in zip(starts, starts[1:]))


def test_split_fixed_size_spans_reconstruct_exact_source() -> None:
    text = " preamble \n" + (("body sentence. \n") * 100) + " trailing \n"
    spans = split_fixed_size_spans(text, max_chars=80, overlap_chars=12)
    reconstructed = ""
    covered_end = 0
    for start, end in spans:
        reconstructed += text[max(start, covered_end) : end]
        covered_end = max(covered_end, end)
    assert reconstructed == text


# ── _parse_frontmatter ────────────────────────────────────────────────────────


def test_parse_frontmatter_none():
    meta, body = _parse_frontmatter("# Title\n\nbody text")
    assert meta == {}
    assert body == "# Title\n\nbody text"


def test_parse_frontmatter_unclosed():
    content = "---\ntitle: foo\nno closing fence\nbody"
    meta, body = _parse_frontmatter(content)
    assert meta == {}
    assert body == content


def test_parse_frontmatter_valid_with_quotes():
    content = "---\ntitle: \"Hello\"\nauthor: 'Bob'\n---\nbody here"
    meta, body = _parse_frontmatter(content)
    assert meta == {"title": "Hello", "author": "Bob"}
    assert body == "body here"


# ── _split_by_headers ─────────────────────────────────────────────────────────


def test_split_by_headers_no_headers():
    parts = _split_by_headers("just plain text\nwith newlines")
    assert parts == [("", "just plain text\nwith newlines")]


def test_split_by_headers_mixed_levels():
    content = "# H1\nintro\n## H2\nbody\n### H3\ndetail"
    parts = _split_by_headers(content)
    headers = [h for h, _ in parts]
    assert "# H1" in headers
    assert "## H2" in headers
    assert "### H3" in headers
    assert "".join(text for _, text in parts) == content


def test_split_by_headers_header_without_following_content():
    content = "## Lonely header"
    parts = _split_by_headers(content)
    assert parts == [("## Lonely header", content)]


def test_split_by_headers_preserves_preamble_and_whitespace() -> None:
    content = " preamble \n\n# H1\nbody \n\n## H2\n tail\n"
    parts = _split_by_headers(content)
    assert [header for header, _ in parts] == ["", "# H1", "## H2"]
    assert "".join(text for _, text in parts) == content


# ── chunk_markdown_file ───────────────────────────────────────────────────────


def test_chunk_markdown_file_empty(tmp_path: Path):
    f = tmp_path / "empty.md"
    f.write_text("", encoding="utf-8")
    result = chunk_markdown_file(f)
    assert result.status == "empty"
    assert result.chunks == []


def test_chunk_markdown_file_too_short(tmp_path: Path):
    f = tmp_path / "short.md"
    f.write_text("tiny", encoding="utf-8")
    assert chunk_markdown_file(f).status == "empty"


def test_chunk_markdown_file_oversized(tmp_path: Path):
    f = tmp_path / "huge.md"
    f.write_text("x" * (MAX_FILE_SIZE_BYTES + 1), encoding="utf-8")
    assert chunk_markdown_file(f).status == "too_large"


def test_chunk_markdown_file_valid(tmp_path: Path):
    f = tmp_path / "doc.md"
    body = "# Title\n\n" + ("Some real content. " * 30)
    f.write_text(body, encoding="utf-8")
    result = chunk_markdown_file(f)
    assert result.status == "ok"
    chunks = result.chunks
    assert len(chunks) >= 1
    first = chunks[0]
    assert "id" in first
    assert "text" in first
    assert "metadata" in first
    meta = first["metadata"]
    assert "path" in meta
    assert "section" in meta
    assert "file_hash" in meta
    assert len(meta["content_hash"]) == 64
    assert meta["contract_id"] == "freshness-contract-v1"
    assert meta["content_hash_contract_version"] == "v1"
    assert meta["chunking_contract_version"] == "v1"
    assert meta["expected_chunk_count"] == len(chunks)
    assert meta["content_hash"] in first["id"]
    assert "chunk_index" in meta


def test_chunk_markdown_file_hash_stable(tmp_path: Path):
    f = tmp_path / "stable.md"
    body = "# Title\n\n" + ("Stable content. " * 20)
    f.write_text(body, encoding="utf-8")
    h1 = chunk_markdown_file(f).chunks[0]["metadata"]["file_hash"]
    h2 = chunk_markdown_file(f).chunks[0]["metadata"]["file_hash"]
    assert h1 == h2


def test_chunk_markdown_content_hash_is_independent_of_chunking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "stable-content.md"
    raw = ("# Title\r\n\r\n" + ("Stable content. " * 100)).encode()
    f.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    original = chunk_markdown_file(f).chunks
    monkeypatch.setattr(
        "chunker.split_fixed_size",
        lambda text, _size, _overlap: [text[:600], text[600:]],
    )
    changed_boundaries = chunk_markdown_file(f).chunks
    assert {chunk["metadata"]["content_hash"] for chunk in original} == {expected}
    assert {
        chunk["metadata"]["content_hash"] for chunk in changed_boundaries
    } == {expected}


def test_pdf_chunker_uses_shared_fixed_size_splitter() -> None:
    pdf_chunker = importlib.import_module("chunker_pdf")
    assert getattr(pdf_chunker, "split_fixed_size") is split_fixed_size


def test_pdf_chunker_hashes_the_exact_parsed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_chunker = importlib.import_module("chunker_pdf")
    source = tmp_path / "note.pdf"
    raw = b"not-a-real-pdf-but-one-exact-snapshot"
    source.write_bytes(raw)

    class Page:
        def extract_text(self) -> str:
            return "Extracted PDF content long enough to be indexed."

    class Pdf:
        pages = [Page()]

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def open_snapshot(snapshot: object) -> Pdf:
        assert snapshot.getvalue() == raw  # type: ignore[attr-defined]
        return Pdf()

    monkeypatch.setattr(pdf_chunker.pdfplumber, "open", open_snapshot)

    result = pdf_chunker.chunk_pdf_file(source)

    assert result.status == "ok"
    assert result.chunks[0]["metadata"]["content_hash"] == hashlib.sha256(raw).hexdigest()
    assert result.chunks[0]["metadata"]["chunking_contract_version"] == "v1"


def test_pdf_chunker_reports_extraction_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_chunker = importlib.import_module("chunker_pdf")
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"broken")

    def fail_extract(_snapshot: object) -> None:
        raise RuntimeError("parser failed")

    monkeypatch.setattr(pdf_chunker.pdfplumber, "open", fail_extract)

    result = pdf_chunker.chunk_pdf_file(source)

    assert result.status == "extraction_error"
    assert result.error == "parser failed"


def test_chunk_markdown_file_rejects_invalid_utf8(tmp_path: Path):
    f = tmp_path / "invalid.md"
    f.write_bytes(b"# Invalid\n\xff")
    result = chunk_markdown_file(f)
    assert result.status == "read_error"
    assert result.error


def test_chunk_respects_max_chars(tmp_path: Path):
    f = tmp_path / "long.md"
    body = "# Title\n\n" + ("a " * 1000)
    f.write_text(body, encoding="utf-8")
    chunks = chunk_markdown_file(f).chunks
    # Each chunk's text should be within MAX_CHARS (allowing some slack
    # for the natural-boundary backoff which can produce slightly shorter chunks).
    for c in chunks:
        assert len(c["text"]) <= MAX_CHARS + 10
