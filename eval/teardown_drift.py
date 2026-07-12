# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Jalon 4 eval - restore the vault to its pristine pre-eval state.

Restores every mutated note to its exact pristine bytes and moves every
quarantined note back to its original path. Asserts restored sha256 equals
the recorded pristine sha256 for each touched file. Fails loud and stops
(leaves the state file in place for manual recovery) if any restore does
not match - never silently reports success on a partial restore.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import KB_PATH, require_kb_path  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
STATE_DIR = EVAL_DIR.parent / "local" / "eval-jalon4"
STATE_FILE = STATE_DIR / "state.json"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    if not STATE_FILE.exists():
        raise SystemExit(f"No state file at {STATE_FILE} - nothing to restore.")

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    root = Path(require_kb_path(KB_PATH))
    failures = []

    for rel_path, info in state["mutated"].items():
        abs_path = root / rel_path
        backup_path = Path(info["backup_path"])
        pristine = backup_path.read_bytes()
        abs_path.write_bytes(pristine)
        restored_hash = sha256_of(abs_path.read_bytes())
        expected_hash = info["pristine_sha256"]
        ok = restored_hash == expected_hash
        print(f"[restore-mutate] {rel_path}: {'OK' if ok else 'MISMATCH'} "
              f"({restored_hash[:12]} vs expected {expected_hash[:12]})")
        if not ok:
            failures.append(rel_path)

    for rel_path, info in state["quarantined"].items():
        abs_path = root / rel_path
        quarantine_path = Path(info["quarantine_path"])
        quarantine_path.rename(abs_path)
        restored_hash = sha256_of(abs_path.read_bytes())
        expected_hash = info["pristine_sha256"]
        ok = restored_hash == expected_hash
        print(f"[restore-quarantine] {rel_path}: {'OK' if ok else 'MISMATCH'} "
              f"({restored_hash[:12]} vs expected {expected_hash[:12]})")
        if not ok:
            failures.append(rel_path)

    if failures:
        print(f"\nFAILED to restore {len(failures)} file(s): {failures}")
        print("State file preserved for manual recovery. NOT deleting it.")
        raise SystemExit(1)

    STATE_FILE.unlink()
    print(f"\nAll {len(state['mutated']) + len(state['quarantined'])} files "
          "restored byte-exact. State file removed.")


if __name__ == "__main__":
    main()
