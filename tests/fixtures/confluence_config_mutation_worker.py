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
"""Subprocess worker for real Confluence config mutation lock tests."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import filelock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from confluence_writer.config import ConfluenceSettings, SpaceMapping  # noqa: E402
from confluence_writer.config_mutation import (  # noqa: E402
    ConfluenceConfigConflictError,
    ConfluenceConfigLockedError,
    confluence_config_mutation_lock_path,
    write_confluence_config_cas,
)


def _settings(label: str) -> ConfluenceSettings:
    return ConfluenceSettings(
        schema_version=2,
        base_url=f"https://{label}.example.test:8443",
        credential_target=f"Cortex {label}",
        auth_expires_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
        console_path=Path(f"C:/Tools/{label}/console.exe"),
        spaces=(
            SpaceMapping(
                space_key="DOC",
                target=f"knowledge/{label}",
                classification="perso-non-sensible",
                selection="pages",
                pages=(),
            ),
        ),
    )


def _hold_lock(config_path: Path, ready_path: Path, release_path: Path) -> int:
    lock_path = confluence_config_mutation_lock_path(config_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with filelock.FileLock(lock_path).acquire():
        ready_path.write_text("ready\n", encoding="utf-8")
        while not release_path.exists():
            time.sleep(0.02)
    return 0


def _mutate(
    config_path: Path,
    label: str,
    expected_hash: str | None,
    timeout_seconds: float,
) -> int:
    try:
        write_confluence_config_cas(
            config_path,
            _settings(label),
            expected_hash=expected_hash,
            timeout_seconds=timeout_seconds,
        )
    except ConfluenceConfigLockedError:
        print(f"LOCKED:{label}")
        return 0
    except ConfluenceConfigConflictError:
        print(f"CONFLICT:{label}")
        return 0
    print(f"OK:{label}")
    return 0


def main() -> int:
    mode = sys.argv[1]
    config_path = Path(sys.argv[2])
    if mode == "hold":
        return _hold_lock(config_path, Path(sys.argv[3]), Path(sys.argv[4]))
    label = sys.argv[3]
    raw_hash = sys.argv[4]
    expected_hash = None if raw_hash == "absent" else raw_hash
    timeout_seconds = float(sys.argv[5])
    if mode == "race":
        ready_path = Path(sys.argv[6])
        go_path = Path(sys.argv[7])
        ready_path.write_text("ready\n", encoding="utf-8")
        while not go_path.exists():
            time.sleep(0.02)
    return _mutate(config_path, label, expected_hash, timeout_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
