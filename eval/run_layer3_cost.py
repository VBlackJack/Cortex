# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Jalon 4 eval - Layer 3: selective vs full re-embed work (pure computation).

Cortex's embedding model is a local CPU model (fastembed, no per-token API
billing) - the brief's "token savings" thesis is reinterpreted honestly as
chunk/byte work avoided. Calls chunk_markdown_file() (pure function, no
Chroma write) on just the mutated set vs on every file in the pilot section.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import KB_PATH, require_kb_path  # noqa: E402
from chunker import chunk_markdown_file  # noqa: E402
from chunker_utils import is_excluded_path  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
STATE_DIR = EVAL_DIR.parent / "local" / "eval-jalon4"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "eval_config.json"


def main() -> None:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    root = Path(require_kb_path(KB_PATH))
    section = config["section"]

    selective_paths = list(state["mutated"].keys())
    selective_chunks = 0
    selective_bytes = 0
    for rel_path in selective_paths:
        abs_path = root / rel_path
        result = chunk_markdown_file(abs_path)
        selective_chunks += len(result.chunks)
        selective_bytes += abs_path.stat().st_size

    full_chunks = 0
    full_bytes = 0
    full_files = 0
    for path in sorted((root / section).rglob("*.md")):
        rel = path.relative_to(root)
        if is_excluded_path(rel):
            continue
        full_files += 1
        result = chunk_markdown_file(path)
        full_chunks += len(result.chunks)
        full_bytes += path.stat().st_size

    result = {
        "selective_files": len(selective_paths),
        "selective_chunks": selective_chunks,
        "selective_bytes": selective_bytes,
        "full_section_files": full_files,
        "full_section_chunks": full_chunks,
        "full_section_bytes": full_bytes,
        "chunk_work_avoided_pct": round(
            100.0 * (1 - selective_chunks / full_chunks), 2
        ) if full_chunks else None,
        "byte_work_avoided_pct": round(
            100.0 * (1 - selective_bytes / full_bytes), 2
        ) if full_bytes else None,
        "note": (
            "No per-token API cost applies (local fastembed model). This "
            "measures chunk/byte re-embed work avoided by selective sync "
            "(only the M mutated files) vs a full section re-embed."
        ),
    }
    print(json.dumps(result, indent=2))
    out_path = STATE_DIR / "layer3_cost.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
