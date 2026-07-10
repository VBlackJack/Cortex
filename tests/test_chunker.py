# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Unit tests for chunker.py — boundary cases and invariants.
"""

from pathlib import Path


from chunker import (
    MAX_CHARS,
    MAX_FILE_SIZE_BYTES,
    _split_fixed_size,
    _parse_frontmatter,
    _split_by_headers,
    chunk_markdown_file,
)


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


def test_split_fixed_size_overlap_larger_than_max_terminates():
    """The guard at chunker.py must prevent infinite loops when overlap >= max_chars."""
    text = "a" * 50
    chunks = _split_fixed_size(text, max_chars=10, overlap_chars=20)
    assert len(chunks) > 0
    # Loop must have terminated — implicit by reaching this assertion.
    # All chunks should be non-empty.
    assert all(c for c in chunks)


def test_split_fixed_size_breaks_on_newline():
    text = "first line\n" + ("x" * 200)
    chunks = _split_fixed_size(text, max_chars=50, overlap_chars=5)
    # First chunk should end at the newline boundary, not mid-line.
    assert chunks[0] == "first line"


def test_split_fixed_size_breaks_on_sentence_when_no_newline():
    text = "Sentence one. " + ("x" * 100)
    chunks = _split_fixed_size(text, max_chars=30, overlap_chars=5)
    assert chunks[0].startswith("Sentence one.")


def test_split_fixed_size_no_natural_boundary_falls_back_to_hard_cut():
    text = "x" * 100
    chunks = _split_fixed_size(text, max_chars=20, overlap_chars=5)
    assert len(chunks) >= 5
    assert all(len(c) <= 20 for c in chunks)


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


def test_split_by_headers_header_without_following_content():
    content = "## Lonely header"
    parts = _split_by_headers(content)
    # Empty trailing content should not produce a chunk.
    assert all(text for _, text in parts) or parts == [("", "")] or parts == []


# ── chunk_markdown_file ───────────────────────────────────────────────────────


def test_chunk_markdown_file_empty(tmp_path: Path):
    f = tmp_path / "empty.md"
    f.write_text("", encoding="utf-8")
    assert chunk_markdown_file(f) == []


def test_chunk_markdown_file_too_short(tmp_path: Path):
    f = tmp_path / "short.md"
    f.write_text("tiny", encoding="utf-8")
    assert chunk_markdown_file(f) == []


def test_chunk_markdown_file_oversized(tmp_path: Path):
    f = tmp_path / "huge.md"
    f.write_text("x" * (MAX_FILE_SIZE_BYTES + 1), encoding="utf-8")
    assert chunk_markdown_file(f) == []


def test_chunk_markdown_file_valid(tmp_path: Path):
    f = tmp_path / "doc.md"
    body = "# Title\n\n" + ("Some real content. " * 30)
    f.write_text(body, encoding="utf-8")
    chunks = chunk_markdown_file(f)
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
    assert "chunk_index" in meta


def test_chunk_markdown_file_hash_stable(tmp_path: Path):
    f = tmp_path / "stable.md"
    body = "# Title\n\n" + ("Stable content. " * 20)
    f.write_text(body, encoding="utf-8")
    h1 = chunk_markdown_file(f)[0]["metadata"]["file_hash"]
    h2 = chunk_markdown_file(f)[0]["metadata"]["file_hash"]
    assert h1 == h2


def test_chunk_markdown_file_rejects_invalid_utf8(tmp_path: Path):
    f = tmp_path / "invalid.md"
    f.write_bytes(b"# Invalid\n\xff")
    assert chunk_markdown_file(f) == []


def test_chunk_respects_max_chars(tmp_path: Path):
    f = tmp_path / "long.md"
    body = "# Title\n\n" + ("a " * 1000)
    f.write_text(body, encoding="utf-8")
    chunks = chunk_markdown_file(f)
    # Each chunk's text should be within MAX_CHARS (allowing some slack
    # for the natural-boundary backoff which can produce slightly shorter chunks).
    for c in chunks:
        assert len(c["text"]) <= MAX_CHARS + 10
