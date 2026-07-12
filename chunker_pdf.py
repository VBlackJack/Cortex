# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Chunk native PDF files from one immutable byte snapshot."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber

from chunker_utils import (
    ChunkResult,
    compute_hash,
    get_relative_path,
    get_section,
    sha256_bytes,
    split_fixed_size,
)
from config import (
    CHUNK_MIN_CHARS,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CHUNKING_CONTRACT_VERSION,
    FRESHNESS_CONTRACT_ID,
    FRESHNESS_CONTRACT_VERSION,
    KB_PATH,
    MAX_PDF_SIZE_BYTES,
    require_kb_path,
)


def chunk_pdf_file(file_path: Path) -> ChunkResult:
    """Extract and chunk a PDF while hashing the exact bytes being parsed."""
    file_path = Path(file_path)
    try:
        if file_path.stat().st_size > MAX_PDF_SIZE_BYTES:
            return ChunkResult(status="too_large")
        raw_bytes = file_path.read_bytes()
    except OSError as exc:
        return ChunkResult(status="read_error", error=str(exc))
    if len(raw_bytes) > MAX_PDF_SIZE_BYTES:
        return ChunkResult(status="too_large")

    try:
        pages_text: list[tuple[int, str]] = []
        with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                if text and text.strip():
                    pages_text.append((page_num, text.strip()))
    except Exception as exc:  # noqa: BLE001 -- PDF backends expose no stable exception base.
        return ChunkResult(status="extraction_error", error=str(exc))

    if not pages_text:
        return ChunkResult(status="empty")

    full_text = "\n".join(text for _, text in pages_text)
    file_hash = compute_hash(full_text)
    content_hash = sha256_bytes(raw_bytes)
    kb_path = require_kb_path(KB_PATH)
    section = get_section(file_path, kb_path)
    rel_path = get_relative_path(file_path, kb_path)
    title = file_path.stem.replace("-", " ").replace("_", " ").title()
    chunks: list[dict[str, Any]] = []

    for page_num, page_text in pages_text:
        for segment in split_fixed_size(
            page_text,
            CHUNK_SIZE,
            CHUNK_OVERLAP,
            CHUNK_MIN_CHARS,
        ):
            if not segment.strip():
                continue
            chunk_index = len(chunks)
            chunks.append(
                {
                    "id": (
                        f"{rel_path}::{content_hash}::"
                        f"{CHUNKING_CONTRACT_VERSION}::{chunk_index}"
                    ),
                    "text": segment,
                    "metadata": {
                        "path": rel_path,
                        "section": section,
                        "title": title,
                        "header": f"Page {page_num}",
                        "chunk_index": chunk_index,
                        "file_hash": file_hash,
                        "content_hash": content_hash,
                        "contract_id": FRESHNESS_CONTRACT_ID,
                        "content_hash_contract_version": FRESHNESS_CONTRACT_VERSION,
                        "chunking_contract_version": CHUNKING_CONTRACT_VERSION,
                        "format": "pdf",
                        "page": page_num,
                    },
                }
            )

    if not chunks:
        return ChunkResult(status="empty")
    expected_chunk_count = len(chunks)
    for chunk in chunks:
        chunk["metadata"]["expected_chunk_count"] = expected_chunk_count
    return ChunkResult(status="ok", chunks=chunks)
