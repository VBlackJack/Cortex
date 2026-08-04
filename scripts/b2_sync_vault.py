# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Resumable, checkpointed full-vault sync driver for B2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import CHROMA_PATH, INCLUDED_SECTIONS, KB_PATH, require_kb_path
from cortex_logging import configure_logging
from indexer import get_collection
from ingestion.config import load_ingestion_settings
from lexical_index import prepare_lexical_index
from sync_hash_aware import (
    SyncCheckpoint,
    empty_sync_stats,
    merge_sync_stats,
    sync_ingestion_documents,
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
        ingestion_settings = load_ingestion_settings()
        print("[sync] current ingestion document generation ...", flush=True)
        document_stats = sync_ingestion_documents(
            collection,
            ingestion_settings.data_root,
            retention_generations=ingestion_settings.retention_generations,
            checkpoint=checkpoint,
            verbose=args.verbose,
            lexical_index=lexical_index,
        )
        merge_sync_stats(totals, document_stats)
        print(f"[done] ingestion documents: {document_stats}", flush=True)

    print(f"TOTAL {totals}")


if __name__ == "__main__":
    main()
