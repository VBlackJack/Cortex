# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Jalon 4 eval - Layer 2: prepare BEFORE/AFTER contexts for downstream tasks.

BEFORE = search() hits, raw embedded text, no freshness signal.
AFTER  = search() + annotate_search_hits(); any "stale" hit's shown text is
replaced by the live file content (the mechanism a freshness-aware consumer
would use); any "missing" hit is flagged as no longer available.

Writes one context file per (task, condition) under local/eval-jalon4/layer2/
for a blind subagent consumer to read. No Chroma write, no cortex_sync.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import KB_PATH  # noqa: E402
from indexer import search  # noqa: E402
from freshness import annotate_search_hits  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
STATE_DIR = EVAL_DIR.parent / "local" / "eval-jalon4"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "eval_config.json"
OUT_DIR = STATE_DIR / "layer2"


def build_before(query: str, top_k: int, section: str) -> str:
    hits = search(query=query, section=section, top_k=top_k)
    lines = []
    for h in hits:
        meta = h.get("metadata", {})
        lines.append(f"--- source: {meta.get('path')} (no freshness signal) ---")
        lines.append(h.get("text", ""))
    return "\n\n".join(lines)


def build_after(query: str, top_k: int, section: str, root: Path) -> str:
    hits = search(query=query, section=section, top_k=top_k)
    hits = annotate_search_hits(hits)
    lines = []
    live_shown: set[str] = set()
    for h in hits:
        meta = h.get("metadata", {})
        path = meta.get("path")
        fresh = h.get("freshness")
        if fresh == "stale":
            if path in live_shown:
                lines.append(f"--- source: {path} (freshness=STALE - live content already shown above for this source) ---")
                continue
            live_shown.add(path)
            live_path = root / path
            try:
                live_text = live_path.read_text(encoding="utf-8")
            except OSError:
                live_text = "(live file unreadable)"
            lines.append(f"--- source: {path} (freshness=STALE - embedded copy is outdated; showing LIVE file content instead) ---")
            lines.append(live_text)
        elif fresh == "missing":
            lines.append(f"--- source: {path} (freshness=MISSING - the underlying file no longer exists on disk; do not cite its content as current) ---")
        else:
            lines.append(f"--- source: {path} (freshness={fresh}) ---")
            lines.append(h.get("text", ""))
    return "\n\n".join(lines)


def main() -> None:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    root = Path(KB_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    top_k = config["layer2_top_k"]

    stale_dependent_tasks = config["layer2_stale_dependent_tasks"]
    missing_task = config["layer2_missing_task"]
    control_tasks = [
        {
            "id": f"C{i+1}",
            "path": entry["path"],
            "query": entry["query"],
            "question": entry["question"],
            "expected_substring": entry["expected_substring"],
        }
        for i, entry in enumerate(config["layer2_control_tasks"])
    ]

    manifest = []
    for task in stale_dependent_tasks + [missing_task] + control_tasks:
        before_ctx = build_before(task["query"], top_k, config["section"])
        after_ctx = build_after(task["query"], top_k, config["section"], root)

        before_path = OUT_DIR / f"{task['id']}_before_context.txt"
        after_path = OUT_DIR / f"{task['id']}_after_context.txt"
        before_path.write_text(before_ctx, encoding="utf-8")
        after_path.write_text(after_ctx, encoding="utf-8")

        manifest.append({
            "id": task["id"],
            "path": task["path"],
            "question": task["question"],
            "before_context_file": str(before_path),
            "after_context_file": str(after_path),
            "expected_token": task.get("expected_token"),
            "expected_substring": task.get("expected_substring"),
        })
        print(f"[{task['id']}] before={len(before_ctx)} chars, after={len(after_ctx)} chars -> {task['path']}")

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest written to {manifest_path}")


if __name__ == "__main__":
    main()
