# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Stable machine progress lines carried on the diagnostic stderr stream."""

from __future__ import annotations

import json
import sys
from typing import Literal

PROGRESS_PREFIX = "CORTEX_PROGRESS "
ProgressPhase = Literal["enumeration", "staging", "conversion", "publication"]


def emit_progress(phase: ProgressPhase, current: int, total: int) -> None:
    """Emit one compact, sanitized, flush-safe progress record."""
    if current < 0 or total < 0 or current > total:
        raise ValueError("progress counters must satisfy 0 <= current <= total")
    payload = json.dumps(
        {
            "contract_version": 1,
            "phase": phase,
            "current": current,
            "total": total,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    sys.stderr.write(PROGRESS_PREFIX + payload + "\n")
    sys.stderr.flush()


__all__ = ["PROGRESS_PREFIX", "emit_progress"]
