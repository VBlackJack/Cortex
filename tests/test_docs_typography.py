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
"""Typography guard for the documentation, the sources and the workflows.

A typographic substitute (curly quote, dash, ellipsis, special space, ligature)
says nothing an ordinary ASCII character does not, and it does not survive a
Windows console, a diff or a CI log intact. Accented letters, arrows, box
drawing, check boxes and emoji carry meaning and stay allowed.

The guard walks the tree recursively and asserts separately that it reached
both documentation languages: a manual sweep once reported green while two
subdirectories had never been opened.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCANNED_PATTERNS = (
    "README*.md",
    "CHANGELOG.md",
    "docs/**/*.md",
    "models/*.md",
    "packaging/**/*.md",
    "packaging/windows/*.iss",
    "*.py",
    "confluence_writer/**/*.py",
    "ingestion/**/*.py",
    "scripts/*.py",
    "eval/*.py",
    "packaging/**/*.py",
    "tests/**/*.py",
    ".github/workflows/*.yml",
    "install.bat",
    "sync.bat",
)

EXCLUDED_DIRECTORIES = frozenset({"local", "build", ".git", "__pycache__"})
EXCLUDED_DIRECTORY_PREFIXES = ("dist",)
EXCLUDED_SUFFIXES = frozenset({".lock"})
# The retrieval corpus quotes real French documents verbatim, and the retrieval
# gate pins its SHA-256 in eval/retrieval_acceptance.json: it is never rewritten.
EXCLUDED_FILES = frozenset({"eval/retrieval_corpus.json"})

# Inno Setup needs the byte order mark at the start of a script that carries
# non-ASCII messages; anywhere else, and in any other file, it is refused.
LEADING_BOM_ALLOWED_SUFFIXES = frozenset({".iss"})
BYTE_ORDER_MARK = 0xFEFF

FORBIDDEN_CODE_POINTS = {
    0x2014: "em dash, write -",
    0x2013: "en dash, write -",
    0x2010: "Unicode hyphen, write -",
    0x2011: "non-breaking hyphen, write -",
    0x2212: "minus sign, write -",
    0x2018: "curly single quote, write '",
    0x2019: "curly apostrophe, write '",
    0x201C: 'curly double quote, write "',
    0x201D: 'curly double quote, write "',
    0x00AB: 'guillemet, write "',
    0x00BB: 'guillemet, write "',
    0x201E: 'low double quote, write "',
    0x2026: "one-character ellipsis, write ...",
    0x00A0: "no-break space, write an ordinary space",
    0x202F: "narrow no-break space, write an ordinary space",
    0x200B: "zero-width space, remove it",
    BYTE_ORDER_MARK: "byte order mark inside the text, remove it",
    0x0153: "oe ligature, write oe",
    0x0152: "OE ligature, write OE",
    0x00E6: "ae ligature, write ae",
    0x00C6: "AE ligature, write AE",
}

# Release notes and the changelog are read from a release page and from an
# updater: ASCII plus the accented letters of a French keyboard, nothing else.
STRICT_FILES = ("docs/en/release-notes.md", "CHANGELOG.md")
LATIN1_FIRST = 0x00C0
LATIN1_LAST = 0x00FF
ASCII_LIMIT = 0x80


def _is_excluded(relative: Path) -> bool:
    if relative.as_posix() in EXCLUDED_FILES or relative.suffix in EXCLUDED_SUFFIXES:
        return True
    for part in relative.parts[:-1]:
        if part in EXCLUDED_DIRECTORIES or part.startswith(EXCLUDED_DIRECTORY_PREFIXES):
            return True
    return False


def _scanned_files() -> list[Path]:
    found: set[Path] = set()
    for pattern in SCANNED_PATTERNS:
        for path in ROOT.glob(pattern):
            if path.is_file() and not _is_excluded(path.relative_to(ROOT)):
                found.add(path)
    return sorted(found)


def _offences(path: Path) -> list[str]:
    relative = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    if path.suffix in LEADING_BOM_ALLOWED_SUFFIXES and text.startswith(chr(BYTE_ORDER_MARK)):
        text = text[1:]
    found = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for character in line:
            reason = FORBIDDEN_CODE_POINTS.get(ord(character))
            if reason is not None:
                found.append(f"{relative}:{line_number}: U+{ord(character):04X} ({reason})")
    return found


def _is_accented_latin1_letter(character: str) -> bool:
    # A decomposition into a base letter and a combining mark is what makes a
    # letter accented; it leaves out the ae ligature, the sharp s, the
    # multiplication and division signs and every other Latin-1 symbol.
    code_point = ord(character)
    return (
        LATIN1_FIRST <= code_point <= LATIN1_LAST
        and character.isalpha()
        and bool(unicodedata.decomposition(character))
    )


def test_guard_reaches_both_documentation_languages() -> None:
    relatives = [path.relative_to(ROOT).as_posix() for path in _scanned_files()]
    assert any(relative.startswith("docs/fr/") for relative in relatives), (
        "The typography guard did not reach a single file under docs/fr."
    )
    assert any(relative.startswith("docs/en/") for relative in relatives), (
        "The typography guard did not reach a single file under docs/en."
    )


def test_guard_never_scans_an_excluded_file() -> None:
    relatives = {path.relative_to(ROOT).as_posix() for path in _scanned_files()}
    assert not relatives & EXCLUDED_FILES
    assert not any(relative.endswith(".lock") for relative in relatives)


def test_no_scanned_file_contains_a_typographic_substitute() -> None:
    offences = [offence for path in _scanned_files() for offence in _offences(path)]
    assert not offences, (
        "Typographic substitutes found, by file, line and code point.\n" + "\n".join(offences)
    )


def test_release_notes_and_changelog_use_ascii_and_accented_letters_only() -> None:
    offences = []
    for relative in STRICT_FILES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for character in line:
                if ord(character) < ASCII_LIMIT or _is_accented_latin1_letter(character):
                    continue
                offences.append(f"{relative}:{line_number}: U+{ord(character):04X}")
    assert not offences, (
        "Release notes and the changelog accept ASCII and accented letters only.\n"
        + "\n".join(offences)
    )
