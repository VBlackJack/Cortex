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
"""Metadata migration backup and restore tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrate_metadata_v2 import backup_indexes, restore_indexes, verify_restore_sample


def test_backup_is_restorable_to_disposable_targets(tmp_path: Path) -> None:
    chroma = tmp_path / "source" / "chroma"
    chroma.mkdir(parents=True)
    (chroma / "chroma.sqlite3").write_bytes(b"immutable chroma sample")
    segment = chroma / "segment"
    segment.mkdir()
    (segment / "vectors.bin").write_bytes(bytes(range(32)))
    lexical = tmp_path / "source" / "lexical.db"
    with sqlite3.connect(lexical) as connection:
        connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('restorable')")

    backup = backup_indexes(chroma, lexical, tmp_path / "backups")
    verification = verify_restore_sample(backup)
    restored_chroma = tmp_path / "restored" / "chroma"
    restored_lexical = tmp_path / "restored" / "lexical.db"
    restore_indexes(backup, restored_chroma, restored_lexical)

    assert verification == {
        "chroma_files": 2,
        "chroma_bytes_match": True,
        "lexical_bytes_match": True,
    }
    assert (restored_chroma / "segment" / "vectors.bin").read_bytes() == bytes(range(32))
    with sqlite3.connect(restored_lexical) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("restorable",)
