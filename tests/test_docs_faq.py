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

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FR_FAQ = ROOT / "docs" / "fr" / "faq.md"
EN_FAQ = ROOT / "docs" / "en" / "faq.md"
FR_SPEC = ROOT / "docs" / "fr" / "spec.md"
EN_SPEC = ROOT / "docs" / "en" / "spec.md"
CHANGELOG = ROOT / "CHANGELOG.md"
FR_RELEASE_NOTES = ROOT / "docs" / "fr" / "notes-de-version.md"
EN_RELEASE_NOTES = ROOT / "docs" / "en" / "release-notes.md"
FR_WINDOWS_INSTALL = ROOT / "docs" / "fr" / "installation-windows.md"
EN_WINDOWS_INSTALL = ROOT / "docs" / "en" / "windows-install.md"
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


def _release_markers(document: str) -> tuple[str, ...]:
    return tuple(re.findall(r"<!-- release:([a-z0-9-]+) -->", document))


def _changelog_release_slugs(document: str) -> tuple[str, ...]:
    versions = re.findall(r"(?m)^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", document)
    return tuple(version.replace(".", "-") for version in versions)


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
        ROOT / "README.fr.md": "[FAQ](docs/fr/faq.md)",
        ROOT / "README.md": "[FAQ](docs/en/faq.md)",
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
        ROOT / "docs" / "fr" / "index.md": "[Spécification publique](spec.md)",
        ROOT / "docs" / "en" / "index.md": "[Public specification](spec.md)",
        ROOT / "README.fr.md": "[Spécification publique](docs/fr/spec.md)",
        ROOT / "README.md": "[Public specification](docs/en/spec.md)",
    }

    for path, link in expected_links.items():
        assert link in path.read_text(encoding="utf-8")


def test_release_notes_have_strict_fr_en_structural_parity() -> None:
    french = FR_RELEASE_NOTES.read_text(encoding="utf-8")
    english = EN_RELEASE_NOTES.read_text(encoding="utf-8")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    french_markers = _release_markers(french)
    english_markers = _release_markers(english)
    changelog_release_slugs = _changelog_release_slugs(changelog)

    assert french_markers == english_markers
    assert french.count("\n## ") == len(french_markers)
    assert english.count("\n## ") == len(english_markers)
    assert all(slug in french_markers for slug in changelog_release_slugs)
    assert all(slug in english_markers for slug in changelog_release_slugs)
    assert re.search(r"(?m)^\|.*\n(?:[ \t]*\n)+\|", french) is None
    assert re.search(r"(?m)^\|.*\n(?:[ \t]*\n)+\|", english) is None
    assert "Datacron" not in french
    assert "Datacron" not in english


def test_release_notes_are_linked_from_both_indexes_and_readmes() -> None:
    expected_links = {
        ROOT / "docs" / "fr" / "index.md": ("[Notes de version](notes-de-version.md)",),
        ROOT / "docs" / "en" / "index.md": ("[Release notes](release-notes.md)",),
        ROOT / "README.fr.md": (
            "[Notes de version](docs/fr/notes-de-version.md)",
            "[Journal technique](CHANGELOG.md)",
        ),
        ROOT / "README.md": (
            "[Release notes](docs/en/release-notes.md)",
            "[Technical changelog](CHANGELOG.md)",
        ),
    }

    for path, links in expected_links.items():
        document = path.read_text(encoding="utf-8")
        for link in links:
            assert link in document


COMPANION_LABELS = ROOT / "tests" / "fixtures" / "companion_ui_labels.json"


def _fold(value: str) -> str:
    """Drop diacritics and collapse spacing, so a stripped label still matches."""
    decomposed = unicodedata.normalize("NFD", value)
    return " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char)).split()
    ).casefold()


def _quoted_spans(document: str) -> list[str]:
    """Return every inline code span, flattened, so a wrapped label still matches."""
    parts = document.split("`")
    return [" ".join(parts[index].split()) for index in range(1, len(parts), 2)]


def test_each_language_quotes_companion_labels_from_its_own_interface() -> None:
    """No document may quote a control by the name of the other language.

    Companion ships in English and French. A label quoted in the wrong language sends the
    reader hunting for a control that, in their interface, does not exist under that name.
    The pairs come from the shipped resource files rather than from a hand-picked list,
    because a hand-picked list is exactly what let a French label survive in an English
    page while the two labels beside it were corrected.
    """
    labels = json.loads(COMPANION_LABELS.read_text(encoding="utf-8"))["labels"]
    assert len(labels) > 200, "The captured label set is too small to prove anything."
    # Folded, because a document that spells a label without its accents still sends the
    # reader after the wrong control, and that is the exact form this guard first missed.
    french_labels = {_fold(entry["fr"]): entry["fr"] for entry in labels}
    english_labels = {_fold(entry["en"]): entry["en"] for entry in labels}

    documents = [(ROOT / "README.md", french_labels, "French")]
    documents += [
        (path, french_labels, "French")
        for path in sorted((ROOT / "docs" / "en").glob("*.md"))
    ]
    documents.append((ROOT / "README.fr.md", english_labels, "English"))
    documents += [
        (path, english_labels, "English")
        for path in sorted((ROOT / "docs" / "fr").glob("*.md"))
    ]

    offences = []
    for path, foreign, language in documents:
        for span in _quoted_spans(path.read_text(encoding="utf-8")):
            for segment in span.split(" > "):
                if _fold(segment) in foreign:
                    offences.append(f"{path.name} quotes the {language} label {segment!r}")
    assert not offences, "\n".join(offences)


def test_novice_local_sync_docs_use_the_exact_companion_labels() -> None:
    """Each mirror quotes the labels of its own language, and only those.

    Companion ships in English and French. A label quoted in the wrong language is worse
    than no label at all: the reader searches the interface for a control that, for them,
    does not exist under that name.
    """
    french = ("`Base locale`", "`Synchroniser les documents locaux`")
    english = ("`Local database`", "`Synchronize local documents`")
    documents = {
        ROOT / "README.fr.md": (french, english),
        ROOT / "README.md": (english, french),
        FR_WINDOWS_INSTALL: (french, english),
        EN_WINDOWS_INSTALL: (english, french),
        FR_RELEASE_NOTES: (french, english),
        EN_RELEASE_NOTES: (english, french),
    }

    for path, (expected, foreign) in documents.items():
        document = path.read_text(encoding="utf-8")
        for label in expected:
            assert label in document, f"{path.name} does not quote {label}"
        for label in foreign:
            assert label not in document, f"{path.name} quotes {label} from the other language"
        assert "`Sync maintenant`" not in document
        assert "ouvrir `Sync`" not in document
        assert "open `Sync`" not in document


def test_unsigned_installer_docs_verify_sha256_before_smartscreen_bypass() -> None:
    expectations = {
        ROOT / "README.fr.md": "`Exécuter quand même`",
        ROOT / "README.md": "`Run anyway`",
        FR_WINDOWS_INSTALL: "`Exécuter quand même`",
        EN_WINDOWS_INSTALL: "`Run anyway`",
    }

    for path, bypass_label in expectations.items():
        document = path.read_text(encoding="utf-8")
        checksum_position = document.index("SHA256SUMS")
        hash_command_position = document.index("Get-FileHash")
        bypass_position = document.index(bypass_label)
        assert checksum_position < hash_command_position < bypass_position
