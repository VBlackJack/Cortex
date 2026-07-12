# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Resumable, checkpointed full-vault sync driver for B2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import CHROMA_PATH, INCLUDED_SECTIONS, KB_PATH, require_kb_path
from cortex_logging import configure_logging
from indexer import get_collection
from lexical_index import prepare_lexical_index
from sync_hash_aware import (
    SyncCheckpoint,
    empty_sync_stats,
    merge_sync_stats,
    sync_section,
)
from write_lock import chroma_write_lock


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default="local/b2-vault-checkpoint.json")
    parser.add_argument(
        "--sections",
        nargs="*",
        default=None,
        help="Limit the run to these sections (default: all discovered sections)",
    )
    parser.add_argument("--verbose", action="store_true", help="Trace per-file progress to stderr")
    args = parser.parse_args()

    root = Path(require_kb_path(KB_PATH))
    if not root.is_dir():
        raise RuntimeError(f"KB_PATH is not a directory: {root}")
    sections = args.sections or sorted(INCLUDED_SECTIONS)
    checkpoint = SyncCheckpoint(Path(args.checkpoint))
    print("[init] loading collection / embedding function ...", flush=True)
    collection = get_collection()
    print("[init] collection ready", flush=True)

    totals = empty_sync_stats()
    # Holds the write lock for the WHOLE multi-section run, not just each
    # section individually - closes the gap between sections where another
    # writer could otherwise slip in. sync_section() acquires the same lock
    # again per section; filelock is reentrant on the same process/instance,
    # so this nests without deadlocking (see write_lock.py).
    with chroma_write_lock():
        lexical_index = None
        try:
            lexical_index = prepare_lexical_index(
                collection,
                Path(CHROMA_PATH).parent / "lexical.db",
            )
        except Exception as exc:  # noqa: BLE001 -- Chroma remains authoritative.
            totals["errors"] += 1
            print(f"[lexical] prepare failed: {exc}", file=sys.stderr, flush=True)
        for section in sections:
            print(f"[sync] {section} ...", flush=True)
            stats = sync_section(
                collection,
                root,
                section,
                checkpoint,
                verbose=args.verbose,
                lexical_index=lexical_index,
            )
            merge_sync_stats(totals, stats)
            print(f"[done] {section}: {stats}", flush=True)

    print(f"TOTAL {totals}")


if __name__ == "__main__":
    main()
