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
"""Strict structural parity and discoverability contracts for FR/EN docs."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FR_FAQ = ROOT / "docs" / "fr" / "faq.md"
EN_FAQ = ROOT / "docs" / "en" / "faq.md"
FR_SPEC = ROOT / "docs" / "fr" / "spec.md"
EN_SPEC = ROOT / "docs" / "en" / "spec.md"
FAQ_MARKERS = (
    "install-or-source",
    "data-locations",
    "change-kb",
    "sync-after-edits",
    "client-not-seeing-cortex",
    "uninstall",
    "logs",
    "offline-models",
    "pip-audit",
    "parallel-clients",
)
SPEC_MARKERS = (
    "identity",
    "mcp-tools",
    "search",
    "indexing",
    "freshness",
    "integrity-concurrency",
    "clients",
    "data-locations",
    "distribution",
    "limits-security",
    "version-license",
)


def _markers(document: str) -> tuple[str, ...]:
    return tuple(re.findall(r"<!-- faq:([a-z0-9-]+) -->", document))


def _spec_markers(document: str) -> tuple[str, ...]:
    return tuple(re.findall(r"<!-- spec:([a-z0-9-]+) -->", document))


def _table_shapes(document: str) -> tuple[int, ...]:
    shapes: list[int] = []
    row_count = 0
    for line in document.splitlines():
        if line.startswith("|"):
            row_count += 1
        elif row_count:
            shapes.append(row_count)
            row_count = 0
    if row_count:
        shapes.append(row_count)
    return tuple(shapes)


def test_faq_has_strict_fr_en_question_parity() -> None:
    french = FR_FAQ.read_text(encoding="utf-8")
    english = EN_FAQ.read_text(encoding="utf-8")

    assert _markers(french) == FAQ_MARKERS
    assert _markers(english) == FAQ_MARKERS
    assert french.count("\n## ") == len(FAQ_MARKERS)
    assert english.count("\n## ") == len(FAQ_MARKERS)
    assert french.count("```powershell") == english.count("```powershell")
    assert "Datacron" not in french
    assert "Datacron" not in english


def test_faq_is_linked_from_both_indexes_and_readmes() -> None:
    expected_links = {
        ROOT / "docs" / "fr" / "index.md": "[FAQ](faq.md)",
        ROOT / "docs" / "en" / "index.md": "[FAQ](faq.md)",
        ROOT / "README.md": "[FAQ](docs/fr/faq.md)",
        ROOT / "README.en.md": "[FAQ](docs/en/faq.md)",
    }

    for path, link in expected_links.items():
        assert link in path.read_text(encoding="utf-8")


def test_spec_has_strict_fr_en_structural_parity() -> None:
    french = FR_SPEC.read_text(encoding="utf-8")
    english = EN_SPEC.read_text(encoding="utf-8")

    assert _spec_markers(french) == SPEC_MARKERS
    assert _spec_markers(english) == SPEC_MARKERS
    assert french.count("\n## ") == len(SPEC_MARKERS)
    assert english.count("\n## ") == len(SPEC_MARKERS)
    assert _table_shapes(french) == _table_shapes(english)
    assert len(_table_shapes(french)) == len(SPEC_MARKERS)
    assert re.search(r"(?m)^\|.*\n(?:[ \t]*\n)+\|", french) is None
    assert re.search(r"(?m)^\|.*\n(?:[ \t]*\n)+\|", english) is None
    assert "Datacron" not in french
    assert "Datacron" not in english


def test_spec_is_linked_from_both_indexes_and_readmes() -> None:
    expected_links = {
        ROOT / "docs" / "fr" / "index.md": "[Specification publique](spec.md)",
        ROOT / "docs" / "en" / "index.md": "[Public specification](spec.md)",
        ROOT / "README.md": "[Specification publique](docs/fr/spec.md)",
        ROOT / "README.en.md": "[Public specification](docs/en/spec.md)",
    }

    for path, link in expected_links.items():
        assert link in path.read_text(encoding="utf-8")
