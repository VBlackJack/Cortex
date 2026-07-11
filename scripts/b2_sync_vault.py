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

from config import KB_PATH
from indexer import discover_sections, get_collection
from sync_hash_aware import SyncCheckpoint, sync_section


def main() -> None:
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

    root = Path(KB_PATH)
    sections = args.sections or discover_sections()
    checkpoint = SyncCheckpoint(Path(args.checkpoint))
    print("[init] loading collection / embedding function ...", flush=True)
    collection = get_collection()
    print("[init] collection ready", flush=True)

    totals = {"published": 0, "skipped": 0}
    for section in sections:
        if not (root / section).is_dir():
            print(f"[skip] {section}: folder not found", flush=True)
            continue
        print(f"[sync] {section} ...", flush=True)
        stats = sync_section(collection, root, section, checkpoint, verbose=args.verbose)
        totals["published"] += stats["published"]
        totals["skipped"] += stats["skipped"]
        print(f"[done] {section}: published={stats['published']} skipped={stats['skipped']}", flush=True)

    print(f"TOTAL published={totals['published']} skipped={totals['skipped']}")


if __name__ == "__main__":
    main()
