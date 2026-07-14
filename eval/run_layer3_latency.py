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
"""Jalon 4 eval - Layer 3: annotation latency, cold-ish vs warm, k=5/10.

True OS page-cache flush is not attempted here (would need an admin-
privileged tool such as RAMMap/EmptyStandbyList, out of scope - flagged in
the report as an approximation, not a real cold start). "Cold-ish" instead
means: the FIRST annotation call in this process against a query whose
source files were not read earlier in this eval run (a distinct topic from
the drift set). "Warm" means repeated calls on the same query afterward.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freshness import annotate_search_hits  # noqa: E402
from indexer import search  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
STATE_DIR = EVAL_DIR.parent / "local" / "eval-jalon4"
CONFIG_FILE = STATE_DIR / "eval_config.json"


def timed_annotation(query: str, top_k: int) -> tuple[float, list[dict[str, Any]]]:
    hits = search(query=query, top_k=top_k)
    t0 = time.perf_counter()
    annotate_search_hits(hits)
    t1 = time.perf_counter()
    return (t1 - t0) * 1000, hits


def main() -> None:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    cold_query = config["layer3_latency_query"]
    warm_runs = config.get("warm_runs", 5)
    top_k_values = config["top_k_values"]

    result: dict[str, Any] = {"cold_ish": {}, "warm": {}}

    for top_k in top_k_values:
        cold_ms, hits = timed_annotation(cold_query, top_k)
        result["cold_ish"][str(top_k)] = {
            "ms": round(cold_ms, 3),
            "unique_paths": len({h["metadata"].get("path") for h in hits}),
        }
        print(f"[cold-ish] top_k={top_k}: {cold_ms:.2f} ms")

    for top_k in top_k_values:
        samples = []
        for _ in range(warm_runs):
            ms, hits = timed_annotation(cold_query, top_k)
            samples.append(ms)
        result["warm"][str(top_k)] = {
            "samples_ms": [round(s, 3) for s in samples],
            "median_ms": round(statistics.median(samples), 3),
        }
        print(f"[warm] top_k={top_k}: samples={[round(s,2) for s in samples]} "
              f"median={round(statistics.median(samples),2)}ms")

    result["note"] = (
        "cold_ish = first annotation call this process for a query on files "
        "not previously read in this eval run - an approximation, NOT a "
        "true OS-page-cache-flushed cold start (would require an "
        "admin-privileged tool, not attempted). warm = repeated calls on "
        "the identical query afterward."
    )

    print("\n" + json.dumps(result, indent=2))
    out_path = STATE_DIR / "layer3_latency.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
