# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

import os
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()

KB_PATH = os.environ.get("CORTEX_KB_PATH", r"G:\_DATA").strip('"')
CHROMA_PATH = str(_SCRIPT_DIR / "chroma_db")
COLLECTION_NAME = "cortex"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# FastEmbed has used mean pooling for this model since v0.6.0
# (qdrant/fastembed#436). FastEmbed exposes no reliable pooling introspection,
# so this explicit value is part of Cortex's persisted embedding contract.
EMBEDDING_POOLING = "mean"

# One-time migration baseline for the unstamped index whose construction was
# attested on 2026-07-12. Keep these literals independent from the runtime
# settings above: changing the runtime contract must never rewrite history.
LEGACY_INDEX_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
LEGACY_INDEX_FASTEMBED_VERSION = "0.8.0"
LEGACY_INDEX_EMBEDDING_POOLING = "mean"

# Chunk sizes (characters)
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
SEARCH_TOP_K_MIN = 1
SEARCH_TOP_K_MAX = 10
MAX_MARKDOWN_FILE_SIZE_BYTES = int(os.environ.get("CORTEX_MAX_MARKDOWN_FILE_SIZE_BYTES", "1000000"))

EXCLUDE_FILES = {"00_INDEX.md"}

FRESHNESS_CONTRACT_ID = "freshness-contract-v1"
FRESHNESS_CONTRACT_VERSION = "v1"
CHUNKING_CONTRACT_VERSION = "v1"

# Single section policy - the one source of truth for what Cortex ever
# indexes, consulted by discover_sections(), is_excluded_path(), the sync
# paths (indexer.py, sync_hash_aware.py), and freshness.py alike. No
# mechanism carries its own divergent list.
#
# INCLUDED_SECTIONS: explicit allowlist - only these top-level dirs are ever
# synced. Arbitrated 2026-07-11 (retires the stale KNOWN_SECTIONS list,
# whose 8 entries matched zero live folders).
INCLUDED_SECTIONS = frozenset({
    "knowledge",
    "operations",
    "projects",
    "sources",
    "_memory",
    "_drafts",
})

# EXCLUDED_DIRS: explicit denylist - structurally never content (internal
# metadata, archive, trash, attachments, staging inbox, personal journal).
# Arbitrated 2026-07-11.
EXCLUDED_DIRS = frozenset({
    ".datacron",
    "_archive",
    "_trash",
    "_attachments",
    "zzz_Corbeille",
    "_inbox",
    "_journal",
})

# Any live top-level dir in NEITHER set above is "out of policy": never
# auto-indexed, but surfaced (cortex_list_sections, cortex_freshness) as
# present and requiring an explicit policy decision - never a silent gap,
# never an accidental embed. See chunker_utils.discover_out_of_policy_dirs.

# Single-writer guarantee: every Chroma write path acquires this lock before
# touching the DB. OS-advisory (auto-released if the holder dies), bounded
# timeout, fail-closed on contention. See write_lock.py.
CORTEX_WRITE_LOCK_PATH = os.environ.get(
    "CORTEX_WRITE_LOCK_PATH", str(_SCRIPT_DIR / "chroma_db.write.lock")
)
CORTEX_WRITE_LOCK_TIMEOUT_SECONDS = float(
    os.environ.get("CORTEX_WRITE_LOCK_TIMEOUT_SECONDS", "30")
)
