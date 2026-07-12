# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Delete supervisor-approved missing paths with a durable local checkpoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chroma_client import iter_collection_pages
from config import CHROMA_PATH, LEGACY_CHROMA_PATH
from cortex_logging import configure_logging
from data_home import ensure_index_location
from indexer import get_collection
from write_lock import chroma_write_lock

REPORT = Path("local/b2-missing-report.json")
CHECKPOINT = Path("local/b2-delete-checkpoint.json")
BATCH_SIZE = 500


def main() -> None:
    configure_logging()
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    approved = {item["path"] for item in report["missing"]}
    completed = set()
    if CHECKPOINT.exists():
        completed = set(json.loads(CHECKPOINT.read_text(encoding="utf-8"))["completed"])

    ensure_index_location(Path(LEGACY_CHROMA_PATH), Path(CHROMA_PATH))

    # Chroma write lock covers the read (collection.get) through the delete
    # loop: the read decides what to delete, so both must be inside the same
    # exclusive section to stay consistent with a concurrent writer.
    with chroma_write_lock():
        collection = get_collection()
        by_path: dict[str, list[str]] = {}
        for result in iter_collection_pages(
            collection,
            include=["metadatas"],
        ):
            ids = result.get("ids", [])
            metas = result.get("metadatas", []) or []
            for chunk_id, meta in zip(ids, metas):
                raw_path = meta.get("path") if meta else None
                path = raw_path.replace("\\", "/") if isinstance(raw_path, str) else None
                if path is not None and path in approved and path not in completed:
                    by_path.setdefault(path, []).append(chunk_id)
        for path in sorted(by_path):
            chunk_ids = by_path[path]
            for index in range(0, len(chunk_ids), BATCH_SIZE):
                collection.delete(ids=chunk_ids[index : index + BATCH_SIZE])
            completed.add(path)
            CHECKPOINT.write_text(
                json.dumps({"completed": sorted(completed)}, indent=2) + "\n", encoding="utf-8"
            )
    print(
        json.dumps(
            {
                "deleted_paths": len(completed),
                "deleted_chunks": sum(map(len, by_path.values())),
            }
        )
    )


if __name__ == "__main__":
    main()
