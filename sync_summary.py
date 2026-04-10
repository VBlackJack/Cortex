"""
sync_summary.py - Print a summary of indexed chunks by section.
Called by sync.bat after all sections are synced.
"""

from indexer import get_collection, discover_sections

BATCH_LIMIT = 10_000


def count_section(collection, section: str) -> int:
    """Count chunks for a section using batched queries to avoid SQL limits."""
    total = 0
    offset = 0
    while True:
        try:
            result = collection.get(
                where={"section": section},
                include=[],
                limit=BATCH_LIMIT,
                offset=offset,
            )
        except Exception:
            break
        batch_size = len(result.get("ids", []))
        total += batch_size
        if batch_size < BATCH_LIMIT:
            break
        offset += BATCH_LIMIT
    return total


def main():
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
