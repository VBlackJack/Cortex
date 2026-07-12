# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Jalon 4 eval - construct the controlled drift set on the pilot section.

Mutates M notes (byte change -> should become stale) and quarantines D notes
(move out of KB_PATH -> should become missing), per eval_config.json. Backs
up pristine bytes for every touched note first. Writes a state manifest so
teardown_drift.py can restore reliably even across separate invocations.

No Chroma write. No cortex_sync call. Source-file mutation only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import KB_PATH, require_kb_path  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
STATE_DIR = EVAL_DIR.parent / "local" / "eval-jalon4"
STATE_FILE = STATE_DIR / "state.json"
BACKUP_DIR = STATE_DIR / "mutate-backups"
QUARANTINE_DIR = STATE_DIR / "quarantine"
CONFIG_FILE = STATE_DIR / "eval_config.json"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def flatten(rel_path: str) -> str:
    return rel_path.replace("/", "__")


def main() -> None:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    root = Path(require_kb_path(KB_PATH))

    if STATE_FILE.exists():
        raise SystemExit(
            f"State file already exists at {STATE_FILE} - a drift set may already "
            "be active. Run teardown_drift.py first, or inspect manually."
        )

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    state: dict[str, dict[str, Any]] = {"mutated": {}, "quarantined": {}}

    for entry in config["mutate_to_stale"]:
        rel_path = entry["path"]
        abs_path = root / rel_path
        pristine = abs_path.read_bytes()
        pristine_hash = sha256_of(pristine)
        backup_path = BACKUP_DIR / flatten(rel_path)
        backup_path.write_bytes(pristine)

        if entry["kind"] == "canary":
            token = entry["canary_token"]
            marker = (
                f"\n\n## Eval Canary (jalon4, temporary)\n"
                f"CANARY_STATUS_TOKEN={token}\n"
            ).encode()
        else:
            marker = b"\n\n<!-- jalon4 layer1 drift marker -->\n"

        mutated = pristine + marker
        abs_path.write_bytes(mutated)
        mutated_hash = sha256_of(mutated)

        state["mutated"][rel_path] = {
            "pristine_sha256": pristine_hash,
            "mutated_sha256": mutated_hash,
            "backup_path": str(backup_path),
        }
        print(f"[mutate] {rel_path}: {pristine_hash[:12]} -> {mutated_hash[:12]}")

    for rel_path in config["quarantine_to_missing"]:
        abs_path = root / rel_path
        pristine = abs_path.read_bytes()
        pristine_hash = sha256_of(pristine)
        quarantine_path = QUARANTINE_DIR / flatten(rel_path)
        abs_path.rename(quarantine_path)

        state["quarantined"][rel_path] = {
            "pristine_sha256": pristine_hash,
            "quarantine_path": str(quarantine_path),
        }
        print(f"[quarantine] {rel_path}: moved to {quarantine_path.name}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"\nState written to {STATE_FILE}")
    print(f"Mutated: {len(state['mutated'])}, Quarantined: {len(state['quarantined'])}")


if __name__ == "__main__":
    main()
