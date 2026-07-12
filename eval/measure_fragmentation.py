# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Measure source-to-chunk fragmentation in the existing Cortex index.

The script only reads Chroma and source-file metadata/content sizes. It never
creates a collection and never writes to the index. Results are written below
``local/eval-jalon4`` by default, which is excluded from version control.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from chroma_client import create_persistent_client, iter_collection_pages  # noqa: E402
from chunker import (  # noqa: E402
    _merge_small_header_sections,
    _parse_frontmatter,
    _split_by_headers,
)
from chunker_utils import split_fixed_size  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = EVAL_DIR.parent / "local" / "eval-jalon4"
# Commit A must run before the product constant is introduced in commit B.
# getattr makes the baseline use the frozen value now and the product constant later.
MIN_CHUNK_CHARS = int(getattr(config, "CHUNK_MIN_CHARS", 300))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--section",
        action="append",
        dest="sections",
        help="Measure only this section; repeat to select several (default: all indexed).",
    )
    parser.add_argument(
        "--label",
        default="measurement",
        help="Filename/result label, for example 'before' or 'after'.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"JSON destination directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=5_000,
        help="Number of Chroma records read per page (default: 5000).",
    )
    return parser.parse_args()


def safe_source_size(kb_root: Path, relative_path: str) -> tuple[int | None, str | None]:
    """Return a source byte size without allowing metadata paths outside the KB."""
    source_path = (kb_root / Path(relative_path)).resolve()
    try:
        source_path.relative_to(kb_root)
    except ValueError:
        return None, "path_outside_kb"
    try:
        return source_path.stat().st_size, None
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def classify_markdown_small_chunks(
    source_path: Path,
    indexed_chunks: list[tuple[int, str, dict[str, Any]]],
) -> Counter[str]:
    """Classify small Markdown chunks by replaying the exact v2 split locally."""
    targeted_count = sum(len(text) < MIN_CHUNK_CHARS for _index, text, _meta in indexed_chunks)
    try:
        raw_content = source_path.read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return Counter({"unclassified": targeted_count})

    _frontmatter, body = _parse_frontmatter(raw_content)
    expected: list[tuple[str, str]] = []
    for _header, exact_group in _merge_small_header_sections(_split_by_headers(body)):
        sub_chunks = split_fixed_size(exact_group, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
        for position, text in enumerate(sub_chunks):
            if len(sub_chunks) == 1:
                kind = "whole_section"
            elif position == len(sub_chunks) - 1:
                kind = "split_tail"
            else:
                kind = "split_body"
            expected.append((text, kind))

    actual_texts = [text for _index, text, _meta in indexed_chunks]
    if actual_texts != [text for text, _kind in expected]:
        return Counter({"unclassified": targeted_count})
    return Counter(
        kind
        for (text, kind) in expected
        if len(text) < MIN_CHUNK_CHARS
    )


def classify_pdf_small_chunks(
    indexed_chunks: list[tuple[int, str, dict[str, Any]]],
) -> Counter[str]:
    """Treat a PDF page as a section and distinguish whole pages from split tails."""
    page_chunks: dict[int, list[tuple[int, str]]] = defaultdict(list)
    unclassified = 0
    for chunk_index, text, metadata in indexed_chunks:
        page = metadata.get("page")
        if isinstance(page, int):
            page_chunks[page].append((chunk_index, text))
        elif len(text) < MIN_CHUNK_CHARS:
            unclassified += 1

    result: Counter[str] = Counter({"unclassified": unclassified})
    for chunks in page_chunks.values():
        chunks.sort()
        for position, (_chunk_index, text) in enumerate(chunks):
            if len(text) >= MIN_CHUNK_CHARS:
                continue
            if len(chunks) == 1:
                result["whole_section"] += 1
            elif position == len(chunks) - 1:
                result["split_tail"] += 1
            else:
                result["unclassified"] += 1
    return result


def classify_small_chunks(
    kb_root: Path,
    relative_path: str,
    indexed_chunks: list[tuple[int, str, dict[str, Any]]],
) -> Counter[str]:
    """Classify targeted small chunks for one multi-chunk source file."""
    targeted_count = sum(len(text) < MIN_CHUNK_CHARS for _index, text, _meta in indexed_chunks)
    source_path = (kb_root / Path(relative_path)).resolve()
    try:
        source_path.relative_to(kb_root)
    except ValueError:
        return Counter({"unclassified": targeted_count})

    suffix = source_path.suffix.lower()
    if suffix == ".md":
        return classify_markdown_small_chunks(source_path, indexed_chunks)
    if suffix == ".pdf":
        return classify_pdf_small_chunks(indexed_chunks)
    return Counter({"unclassified": targeted_count})


def measure(
    collection: Any,
    *,
    kb_root: Path,
    selected_sections: set[str] | None,
    page_size: int,
) -> dict[str, Any]:
    """Aggregate fragmentation metrics from paged collection reads."""
    path_chunks: dict[str, dict[str, list[tuple[int, str, dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    malformed_records = 0

    for page in iter_collection_pages(
        collection,
        page_size=page_size,
        include=["documents", "metadatas"],
    ):
        documents = page.get("documents") or []
        metadatas = page.get("metadatas") or []
        for document, metadata in zip(documents, metadatas, strict=True):
            if not isinstance(document, str) or not isinstance(metadata, dict):
                malformed_records += 1
                continue
            section = metadata.get("section")
            relative_path = metadata.get("path")
            if not isinstance(section, str) or not isinstance(relative_path, str):
                malformed_records += 1
                continue
            if selected_sections is not None and section not in selected_sections:
                continue
            chunk_index = metadata.get("chunk_index")
            if not isinstance(chunk_index, int):
                malformed_records += 1
                continue
            path_chunks[section][relative_path].append((chunk_index, document, metadata))

    section_results: dict[str, dict[str, Any]] = {}
    for section in sorted(path_chunks):
        section_path_chunks = path_chunks[section]
        for chunks in section_path_chunks.values():
            chunks.sort(key=lambda chunk: chunk[0])
        section_path_lengths = {
            path: [len(text) for _index, text, _metadata in chunks]
            for path, chunks in section_path_chunks.items()
        }
        lengths = [
            length
            for file_lengths in section_path_lengths.values()
            for length in file_lengths
        ]
        source_bytes = 0
        missing_sources: list[dict[str, str]] = []
        for relative_path in sorted(section_path_lengths):
            size, error = safe_source_size(kb_root, relative_path)
            if size is None:
                missing_sources.append({"path": relative_path, "error": error or "unknown"})
            else:
                source_bytes += size

        small_multi_file_chunks = sum(
            sum(length < MIN_CHUNK_CHARS for length in file_lengths)
            for file_lengths in section_path_lengths.values()
            if len(file_lengths) > 1
        )
        multi_file_chunks = sum(
            len(file_lengths)
            for file_lengths in section_path_lengths.values()
            if len(file_lengths) > 1
        )
        diagnostic: Counter[str] = Counter()
        for relative_path, indexed_chunks in section_path_chunks.items():
            if len(indexed_chunks) > 1:
                diagnostic.update(
                    classify_small_chunks(kb_root, relative_path, indexed_chunks)
                )
        chunk_count = len(lengths)
        diagnosed_count = sum(diagnostic.values())
        section_results[section] = {
            "chunk_count": chunk_count,
            "indexed_file_count": len(section_path_lengths),
            "source_bytes_total": source_bytes,
            "source_bytes_per_chunk": round(source_bytes / chunk_count, 3),
            "median_chunk_text_chars": statistics.median(lengths),
            "multi_chunk_file_chunk_count": multi_file_chunks,
            "chunks_below_min_chars_from_multi_chunk_files": small_multi_file_chunks,
            "chunks_below_min_chars_from_multi_chunk_files_pct": round(
                100 * small_multi_file_chunks / chunk_count, 3
            )
            if chunk_count
            else 0.0,
            "small_chunk_diagnostic": {
                "whole_section_count": diagnostic["whole_section"],
                "split_tail_count": diagnostic["split_tail"],
                "unclassified_count": (
                    diagnostic["unclassified"] + diagnostic["split_body"]
                ),
                "whole_section_pct_of_small": round(
                    100 * diagnostic["whole_section"] / diagnosed_count, 3
                )
                if diagnosed_count
                else 0.0,
                "split_tail_pct_of_small": round(
                    100 * diagnostic["split_tail"] / diagnosed_count, 3
                )
                if diagnosed_count
                else 0.0,
                "note": "For PDFs, one page is treated as one section.",
            },
            "missing_source_file_count": len(missing_sources),
            "missing_source_files": missing_sources,
        }

    requested_but_absent = (
        sorted(selected_sections - section_results.keys()) if selected_sections else []
    )
    return {
        "minimum_chunk_chars": MIN_CHUNK_CHARS,
        "malformed_record_count": malformed_records,
        "requested_but_absent_sections": requested_but_absent,
        "sections": section_results,
    }


def slug(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in value
    )
    return cleaned.strip("-") or "measurement"


def main() -> None:
    args = parse_args()
    if args.page_size <= 0:
        raise SystemExit("--page-size must be greater than zero")

    kb_root = Path(config.require_kb_path(config.KB_PATH)).resolve()
    client = create_persistent_client(config.CHROMA_PATH)
    # get_collection is intentionally used instead of get_or_create_collection or
    # indexer.get_collection: this measurement must never create/migrate index state.
    collection = client.get_collection(name=config.COLLECTION_NAME)
    selected_sections = set(args.sections) if args.sections else None
    measured_at = datetime.now(timezone.utc)
    result = {
        "schema_version": 1,
        "label": args.label,
        "measured_at_utc": measured_at.isoformat(),
        "collection_name": config.COLLECTION_NAME,
        "chroma_path": str(Path(config.CHROMA_PATH)),
        "kb_path": str(kb_root),
        "selected_sections": sorted(selected_sections) if selected_sections else None,
        **measure(
            collection,
            kb_root=kb_root,
            selected_sections=selected_sections,
            page_size=args.page_size,
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = measured_at.strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output_dir / f"fragmentation-{slug(args.label)}-{timestamp}.json"
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nWritten to {output_path}")


if __name__ == "__main__":
    main()
