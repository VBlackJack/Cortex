"""
Cortex — Markdown Chunker
Splits .md files into semantically meaningful chunks with metadata.
"""

import hashlib
import re
from pathlib import Path

from config import CHUNK_CHARS, CHUNK_OVERLAP_CHARS, KB_PATH

MAX_CHARS = CHUNK_CHARS
OVERLAP_CHARS = CHUNK_OVERLAP_CHARS

# Skip files larger than this (bytes) — avoids loading huge index pages
MAX_FILE_SIZE_BYTES = 300_000  # ~300 KB


def _compute_hash(content: str) -> str:
    """MD5 hash of file content for change detection."""
    return hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    Extract YAML frontmatter from markdown content.
    Returns (metadata_dict, remaining_content).
    """
    metadata = {}
    if not content.startswith("---"):
        return metadata, content

    end = content.find("\n---", 3)
    if end == -1:
        return metadata, content

    frontmatter = content[3:end].strip()
    body = content[end + 4:].lstrip("\n")

    for line in frontmatter.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip().strip("'\"")

    return metadata, body


def _get_section(file_path: Path, kb_path: str) -> str:
    """Extract top-level section from file path relative to KB_PATH."""
    try:
        rel = file_path.relative_to(kb_path)
        return rel.parts[0] if rel.parts else "Unknown"
    except ValueError:
        return "Unknown"


def _split_by_headers(content: str) -> list[tuple[str, str]]:
    """
    Split markdown content on H1/H2/H3 headers.
    Returns list of (header, content) tuples.
    """
    pattern = re.compile(r"^(#{1,3} .+)$", re.MULTILINE)
    parts = []
    last_end = 0
    current_header = ""

    for match in pattern.finditer(content):
        chunk_text = content[last_end:match.start()].strip()
        if chunk_text:
            parts.append((current_header, chunk_text))
        current_header = match.group(1).strip()
        last_end = match.end()

    remaining = content[last_end:].strip()
    if remaining:
        parts.append((current_header, remaining))

    return parts if parts else [("", content.strip())]


def _split_fixed_size(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """
    Split text into fixed-size chunks with overlap.
    Guarantees termination: start always advances by at least 1 char.
    """
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + max_chars, text_len)

        # Try to break on a natural boundary near the end of the window
        if end < text_len:
            split_pos = text.rfind("\n", start, end)
            if split_pos == -1 or split_pos <= start:
                split_pos = text.rfind(". ", start, end)
            if split_pos != -1 and split_pos > start:
                end = split_pos + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # If we've reached the end, stop
        if end >= text_len:
            break

        # Advance start — guarantee progress even if overlap is large
        next_start = end - overlap_chars
        if next_start <= start:
            next_start = start + 1  # always move forward
        start = next_start

    return chunks


def chunk_markdown_file(file_path: Path) -> list[dict]:
    """
    Chunk a single markdown file into searchable pieces with metadata.

    Returns a list of chunk dicts:
    {
        "id": str,           # "relative/path.md::0"
        "text": str,         # chunk content
        "metadata": {
            "path": str,
            "section": str,
            "title": str,
            "header": str,
            "chunk_index": int,
            "file_hash": str,
        }
    }
    """
    # Skip files that are too large
    try:
        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return []
    except Exception:
        return []

    try:
        raw_content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    file_hash = _compute_hash(raw_content)
    frontmatter, body = _parse_frontmatter(raw_content)
    section = _get_section(file_path, KB_PATH)

    try:
        rel_path = str(file_path.relative_to(KB_PATH))
    except ValueError:
        rel_path = str(file_path)

    title = frontmatter.get("title") or file_path.stem

    if len(body.strip()) < 20:
        return []

    header_sections = _split_by_headers(body)
    chunks = []
    chunk_index = 0

    for header, section_content in header_sections:
        full_text = f"{header}\n{section_content}".strip() if header else section_content
        sub_chunks = _split_fixed_size(full_text, MAX_CHARS, OVERLAP_CHARS)

        for sub_chunk in sub_chunks:
            if not sub_chunk.strip():
                continue
            chunks.append({
                "id": f"{rel_path}::{chunk_index}",
                "text": sub_chunk,
                "metadata": {
                    "path": rel_path,
                    "section": section,
                    "title": title,
                    "header": header,
                    "chunk_index": chunk_index,
                    "file_hash": file_hash,
                }
            })
            chunk_index += 1

    return chunks
