# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Jalon 4 eval - Layer 1: detection correctness (code-based grader).

Compares cortex_freshness_report labels against the ground truth encoded in
eval_config.json + the live state.json manifest. Runs the read multiple
times against the SAME unchanged mutated state to check consistency
(pass^k), then computes precision/recall/F1 for stale and missing, plus the
false-stale rate on the untouched population. No Chroma write.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer import get_collection  # noqa: E402
from freshness import cortex_freshness_report  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
STATE_DIR = EVAL_DIR.parent / "local" / "eval-jalon4"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "eval_config.json"


def ground_truth(
    config: dict[str, Any], state: dict[str, Any]
) -> tuple[dict[str, str], set[str]]:
    truth: dict[str, str] = {}
    for rel_path in state["mutated"]:
        truth[rel_path] = "stale"
    for rel_path in state["quarantined"]:
        truth[rel_path] = "missing"
    excluded_pool = set(config["excluded_from_pool"])
    return truth, excluded_pool


def confusion(labels: dict[str, str], truth: dict[str, str], target: str) -> dict[str, int]:
    tp = fp = fn = 0
    for path, expected in truth.items():
        actual = labels.get(path)
        if expected == target and actual == target:
            tp += 1
        elif expected == target and actual != target:
            fn += 1
        elif expected != target and actual == target:
            fp += 1
    return {"tp": tp, "fp": fp, "fn": fn}


def prf(c: dict[str, int]) -> dict[str, float]:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def main() -> None:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    truth, excluded_pool = ground_truth(config, state)

    collection = get_collection()  # type: ignore[no-untyped-call]  # legacy indexer.py, not touched by this lot
    trials = config["trials_layer1"]
    trial_label_sets = []

    for trial in range(trials):
        report = cortex_freshness_report(collection, section=config["section"])
        labels = {e["path"]: e["status"] for e in report["entries"]}
        trial_label_sets.append(labels)
        print(f"[trial {trial + 1}/{trials}] entries={len(report['entries'])} "
              f"summary={report['summary']}")

    consistent = all(labels == trial_label_sets[0] for labels in trial_label_sets)
    print(f"\nConsistency across {trials} trials: {'PASS' if consistent else 'FAIL'}")

    final_labels = trial_label_sets[-1]

    stale_metrics = prf(confusion(final_labels, truth, "stale"))
    missing_metrics = prf(confusion(final_labels, truth, "missing"))

    untouched_pool = [
        e["path"] for e in cortex_freshness_report(collection, section=config["section"])["entries"]
        if e["path"] not in truth and e["path"] not in excluded_pool
    ]
    false_stale = [p for p in untouched_pool if final_labels.get(p) == "stale"]
    false_stale_rate = len(false_stale) / len(untouched_pool) if untouched_pool else 0.0

    result = {
        "trials": trials,
        "consistent_across_trials": consistent,
        "stale_class": {**confusion(final_labels, truth, "stale"), **stale_metrics},
        "missing_class": {**confusion(final_labels, truth, "missing"), **missing_metrics},
        "untouched_population_size": len(untouched_pool),
        "false_stale_count": len(false_stale),
        "false_stale_paths": false_stale,
        "false_stale_rate": false_stale_rate,
        "ground_truth": truth,
        "observed_labels_for_ground_truth": {p: final_labels.get(p) for p in truth},
    }
    print("\n=== Layer 1 result ===")
    print(json.dumps(result, indent=2))

    out_path = STATE_DIR / "layer1_result.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
