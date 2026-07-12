# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""
sync_summary.py - Print a summary of indexed chunks by section.
Called by sync.bat after all sections are synced.
"""

from typing import Any

from chroma_client import iter_collection_pages
from indexer import discover_sections, get_collection

BATCH_LIMIT = 10_000


def count_section(collection: Any, section: str) -> int:
    """Count chunks for a section using batched queries to avoid SQL limits."""
    total = 0
    for result in iter_collection_pages(
        collection,
        page_size=BATCH_LIMIT,
        where={"section": section},
        include=[],
    ):
        batch_size = len(result.get("ids", []))
        total += batch_size
    return total


def main() -> None:
    collection = get_collection()
    total = collection.count()
    print(f"  Total chunks in DB: {total}")

    if total == 0:
        return

    for sec in sorted(discover_sections()):
        count = count_section(collection, sec)
        if count > 0:
            print(f"    {sec}: {count} chunks")


if __name__ == "__main__":
    main()
