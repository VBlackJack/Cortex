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
"""Block a generation worker immediately before its atomic pointer switch."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingestion.engine import GenerationEngine  # noqa: E402
from ingestion.models import CollectedDocument, GenerationAttempt  # noqa: E402
from ingestion.storage import IngestionStorage  # noqa: E402


def main() -> int:
    """Run until the parent terminates this process at the publication barrier."""
    root = Path(sys.argv[1])
    ready = Path(sys.argv[2])
    storage = IngestionStorage(root, "fixture-source", retention_generations=2)
    engine = GenerationEngine(storage)

    def block_before_pointer() -> None:
        ready.write_text("ready\n", encoding="utf-8")
        while True:
            time.sleep(1.0)

    engine.run(
        GenerationAttempt(
            documents=(
                CollectedDocument(
                    source_uid="document-1",
                    path="published/document-1.md",
                    content=b"replacement content\n",
                ),
            ),
            remote_seen_source_uids=frozenset({"document-1"}),
            enumeration_complete=True,
            enumeration_succeeded=True,
        ),
        now=datetime.now(timezone.utc),
        before_pointer_switch=block_before_pointer,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
