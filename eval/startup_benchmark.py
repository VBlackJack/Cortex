# Copyright 2026 Julien Bombled
# Licensed under the Apache License, Version 2.0.
"""Measure repeated packaged --version launches without touching a knowledge base."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

DEFAULT_SAMPLES = 5
DEFAULT_TIMEOUT = 30.0


def measure(executable: Path, samples: int, timeout: float) -> dict[str, Any]:
    """Record first and subsequent launches; no OS cache flush or GUI launch is implied."""
    if samples < 2 or timeout <= 0 or not executable.is_file():
        raise ValueError("An existing executable, at least two samples and a timeout are required")
    digest = hashlib.sha256()
    with executable.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    durations = []
    versions = []
    for _ in range(samples):
        started = time.perf_counter()
        result = subprocess.run(
            [str(executable.resolve()), "--version"],
            capture_output=True,
            check=True,
            timeout=timeout,
        )
        durations.append(time.perf_counter() - started)
        versions.append(result.stdout.decode("utf-8").strip())
    if len(set(versions)) != 1 or not versions[0]:
        raise RuntimeError("Version output changed or was empty during measurement")
    return {
        "schema_version": 1,
        "executable": str(executable.resolve()),
        "sha256": digest.hexdigest(),
        "version": versions[0],
        "platform": platform.platform(),
        "seconds": durations,
        "first_launch_seconds": durations[0],
        "subsequent_median_seconds": statistics.median(durations[1:]),
        "scope": "version process startup; OS caches retained; GUI and search not measured",
    }


def main() -> int:
    """Write a reproducible startup report for one explicitly selected executable."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    report = measure(args.executable, args.samples, args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
