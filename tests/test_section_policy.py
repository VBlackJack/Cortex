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
"""Tests for the single, config-driven section policy (arbitrated 2026-07-11):
INCLUDED_SECTIONS (allowlist), EXCLUDED_DIRS (denylist), and the
out-of-policy surfacing for anything in neither set. Also covers Divergence
B - indexer.py's own sync path previously bypassed is_excluded_path
entirely, checking only the old EXCLUDE_DIRS.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import indexer
from chunker_utils import discover_out_of_policy_dirs, is_excluded_path
from config import EXCLUDED_DIRS, INCLUDED_SECTIONS


def test_is_excluded_path_covers_every_denylist_entry() -> None:
    for name in EXCLUDED_DIRS:
        assert is_excluded_path(Path(name) / "note.md"), f"{name} should be excluded"
    assert is_excluded_path(Path(".hidden") / "note.md")  # dotfile convention
    for name in INCLUDED_SECTIONS:
        assert not is_excluded_path(Path(name) / "note.md"), f"{name} should not be excluded"


def test_discover_out_of_policy_dirs(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    for name in [*INCLUDED_SECTIONS, *EXCLUDED_DIRS, "newthing", "another_unknown"]:
        (root / name).mkdir(parents=True)

    out_of_policy = discover_out_of_policy_dirs(root)

    assert set(out_of_policy) == {"newthing", "another_unknown"}
    for name in INCLUDED_SECTIONS:
        assert name not in out_of_policy
    for name in EXCLUDED_DIRS:
        assert name not in out_of_policy


def test_discover_out_of_policy_dirs_empty_when_fully_covered(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    for name in [*INCLUDED_SECTIONS, *EXCLUDED_DIRS]:
        (root / name).mkdir(parents=True)

    assert discover_out_of_policy_dirs(root) == []


def test_discover_sections_returns_only_included_and_warns_on_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "kb"
    present = sorted(INCLUDED_SECTIONS)[:-1]
    for name in present:
        (root / name).mkdir(parents=True)
    # Deliberately do NOT create the last included section - proves the
    # policy warns rather than silently returning a phantom name (the
    # exact failure mode that let KNOWN_SECTIONS drift unnoticed).
    missing = sorted(INCLUDED_SECTIONS)[-1]

    monkeypatch.setattr(indexer, "KB_PATH", str(root))

    with caplog.at_level(logging.WARNING, logger="cortex"):
        sections = indexer.discover_sections()

    assert set(sections) == set(present)
    assert missing not in sections
    assert any(missing in record.getMessage() for record in caplog.records)


def test_sync_excludes_datacron_via_is_excluded_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Divergence B, closed: indexer._sync_locked() previously only checked
    the old EXCLUDE_DIRS (missed .datacron/_archive/_trash entirely). Tested
    against _sync_locked directly (bypasses the write lock wrapper - no
    contention with a real running server.py, no shared lock file touched)
    with an isolated KB_PATH/CHROMA_PATH, never the production vault/DB."""
    root = tmp_path / "kb"
    chroma_path = tmp_path / "chroma_db"
    datacron_dir = root / ".datacron"
    datacron_dir.mkdir(parents=True)
    (datacron_dir / "probe.md").write_bytes(
        b"# Probe\nThis body is long enough to chunk if the exclusion fails.\n"
    )

    monkeypatch.setattr(indexer, "KB_PATH", str(root))
    monkeypatch.setattr(indexer, "CHROMA_PATH", str(chroma_path))
    monkeypatch.setattr(indexer, "LEGACY_CHROMA_PATH", str(chroma_path))

    stats = indexer._sync_locked(section=".datacron", verbose=False)

    assert stats["added_chunks"] == 0
    assert stats["errors"] == 0

    collection = indexer.get_collection()  # type: ignore[no-untyped-call]  # legacy indexer.py, not touched by this lot
    assert collection.count() == 0, ".datacron content must never be embedded"
