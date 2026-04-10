"""
chunker_pdf.py - PDF chunker for native (non-scanned) PDF files.
Extracts text page by page using pdfplumber, then splits into fixed-size chunks.
"""

from pathlib import Path

import pdfplumber

from config import KB_PATH, CHUNK_SIZE, CHUNK_OVERLAP
from chunker_utils import compute_hash, get_section, get_relative_path, split_fixed_size

MAX_PDF_SIZE_BYTES = 50_000_000  # 50 MB - skip larger files


# ── PDF chunker ──────────────────────────────────────────────────────────────

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
    file_hash = compute_hash(full_text)

    section = get_section(file_path, KB_PATH)
    rel_path = get_relative_path(file_path, KB_PATH)
    # Build a readable title from the filename
    title = file_path.stem.replace("-", " ").replace("_", " ").title()

    chunks = []
    chunk_idx = 0

    for page_num, page_text in pages_text:
        segments = split_fixed_size(page_text, CHUNK_SIZE, CHUNK_OVERLAP)
        for segment in segments:
            if not segment.strip():
                continue
            chunk_id = f"{rel_path}::{chunk_idx}"
            chunks.append({
                "id": chunk_id,
                "text": segment,
                "metadata": {
                    "path":        rel_path,
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
