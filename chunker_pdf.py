"""
chunker_pdf.py - PDF chunker for native (non-scanned) PDF files.
Extracts text page by page using pdfplumber, then splits into fixed-size chunks.
"""

import hashlib
from pathlib import Path

import pdfplumber

from config import KB_PATH, CHUNK_SIZE, CHUNK_OVERLAP, KNOWN_SECTIONS

MAX_PDF_SIZE_BYTES = 50_000_000  # 50 MB - skip larger files


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()


def _get_section(file_path: Path, kb_path: str) -> str:
    """Derive section name from the folder structure under KB_PATH."""
    try:
        parts = file_path.relative_to(kb_path).parts
        if parts:
            return parts[0]
    except ValueError:
        pass
    return "Unknown"


def _split_fixed_size(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split text into overlapping fixed-size chunks."""
    chunks = []
    text_len = len(text)
    start = 0

    while start < text_len:
        end = min(start + max_chars, text_len)
        chunks.append(text[start:end])
        if end >= text_len:
            break
        next_start = end - overlap_chars
        if next_start <= start:
            next_start = start + 1
        start = next_start

    return chunks


# ── PDF chunker ───────────────────────────────────────────────────────────────

def chunk_pdf_file(file_path: Path) -> list[dict]:
    """
    Extract text from a native PDF and return chunks with metadata.
    Returns an empty list if the file is too large, scanned (no text), or unreadable.
    """
    file_path = Path(file_path)

    if file_path.stat().st_size > MAX_PDF_SIZE_BYTES:
        return []

    try:
        pages_text = []
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                if text and text.strip():
                    pages_text.append((page_num, text.strip()))
    except Exception:
        return []

    if not pages_text:
        return []  # scanned PDF or unreadable

    # Hash the full extracted text to detect changes
    full_text = "\n".join(t for _, t in pages_text)
    file_hash = _compute_hash(full_text)

    section = _get_section(file_path, KB_PATH)
    # Build a readable title from the filename
    title = file_path.stem.replace("-", " ").replace("_", " ").title()

    chunks = []
    chunk_idx = 0

    for page_num, page_text in pages_text:
        segments = _split_fixed_size(page_text, CHUNK_SIZE, CHUNK_OVERLAP)
        for segment in segments:
            if not segment.strip():
                continue
            chunk_id = f"{file_hash}_{chunk_idx}"
            chunks.append({
                "id": chunk_id,
                "text": segment,
                "metadata": {
                    "path":        str(file_path),
                    "section":     section,
                    "title":       title,
                    "header":      f"Page {page_num}",
                    "chunk_index": chunk_idx,
                    "file_hash":   file_hash,
                    "format":      "pdf",
                    "page":        page_num,
                },
            })
            chunk_idx += 1

    return chunks
