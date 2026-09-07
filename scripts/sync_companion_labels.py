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
"""Keep the documented Companion labels equal to the ones Companion ships.

The documentation quotes interface controls by name, and a test refuses a page that
quotes one in the other language. Both read an extract of the Companion resources that
lives in this repository, so nothing here notices when a label is renamed next door.
This regenerates that extract, and answers non-zero when it no longer matches, which is
what the interoperability workflows run.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import NamedTuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXTRACT_PATH = REPOSITORY_ROOT / "tests" / "fixtures" / "companion_ui_labels.json"
DEFAULT_COMPANION_PATH = REPOSITORY_ROOT.parent / "CortexCompanion"
LOCALIZATION_RELATIVE = Path("src") / "CortexCompanion" / "Localization"
NEUTRAL_RESOURCE_NAME = "UiStrings.resx"
FRENCH_RESOURCE_NAME = "UiStrings.fr.resx"

EXTRACT_SOURCE = (
    "CortexCompanion src/CortexCompanion/Localization/UiStrings.resx and UiStrings.fr.resx"
)
EXTRACT_NOTE = (
    "Multi-word labels only, at least eight characters, and only where the two languages "
    "differ. Shorter or single-word labels collide with configuration keys and machine "
    "contract values such as ok, mode and classification."
)

# A label shorter than this, or made of one word, is indistinguishable from a
# configuration key or a machine contract value once diacritics are folded away.
MINIMUM_LABEL_LENGTH = 8
# Beyond this a resource is a sentence, not a control name, and no page quotes it.
MAXIMUM_LABEL_LENGTH = 60


class SyncError(RuntimeError):
    """Raised when the Companion resources cannot be read at all."""


class Label(NamedTuple):
    """One control name in both languages."""

    key: str
    french: str
    english: str


def fold(value: str) -> str:
    """Return the value without diacritics and with collapsed spacing."""
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(stripped.split()).casefold()


def read_resources(path: Path) -> dict[str, str]:
    """Read one resx into its name and value pairs."""
    if not path.is_file():
        raise SyncError(f"Companion resource file not found: {path}")
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise SyncError(f"Companion resource file is not valid XML: {path}") from error
    values: dict[str, str] = {}
    for node in root.findall("data"):
        name = node.get("name")
        value = node.findtext("value")
        if name is not None and value is not None:
            values[name] = value
    return values


def is_quotable(french: str, english: str) -> bool:
    """Decide whether a resource is a control name a page could quote."""
    if "\n" in french or "{" in french or len(french) > MAXIMUM_LABEL_LENGTH:
        return False
    if len(french) < MINIMUM_LABEL_LENGTH or len(english) < MINIMUM_LABEL_LENGTH:
        return False
    if " " not in french.strip() or " " not in english.strip():
        return False
    return fold(french) != fold(english)


def collect_labels(companion_path: Path) -> list[Label]:
    """Read both resource sets and keep the control names worth guarding."""
    localization = companion_path / LOCALIZATION_RELATIVE
    neutral = read_resources(localization / NEUTRAL_RESOURCE_NAME)
    french = read_resources(localization / FRENCH_RESOURCE_NAME)
    labels = []
    for key in sorted(neutral):
        english_value = neutral[key]
        french_value = french.get(key)
        if french_value and english_value and is_quotable(french_value, english_value):
            labels.append(Label(key=key, french=french_value, english=english_value))
    return labels


def render(labels: list[Label]) -> str:
    """Render the extract exactly as it is stored, so a comparison is a byte comparison."""
    document = {
        "source": EXTRACT_SOURCE,
        "note": EXTRACT_NOTE,
        "labels": [
            {"key": label.key, "fr": label.french, "en": label.english} for label in labels
        ],
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def describe_drift(stored: str, expected: str) -> list[str]:
    """Name what moved, so the failure says which label to look at."""
    try:
        stored_labels = {
            entry["key"]: (entry["fr"], entry["en"])
            for entry in json.loads(stored)["labels"]
        }
    except (json.JSONDecodeError, KeyError, TypeError):
        return ["the stored extract is unreadable and has to be regenerated"]
    expected_labels = {
        entry["key"]: (entry["fr"], entry["en"]) for entry in json.loads(expected)["labels"]
    }
    lines = []
    for key in sorted(set(expected_labels) - set(stored_labels)):
        lines.append(f"  added   {key}: {expected_labels[key][0]!r} / {expected_labels[key][1]!r}")
    for key in sorted(set(stored_labels) - set(expected_labels)):
        lines.append(f"  removed {key}: {stored_labels[key][0]!r} / {stored_labels[key][1]!r}")
    for key in sorted(set(stored_labels) & set(expected_labels)):
        if stored_labels[key] != expected_labels[key]:
            lines.append(
                f"  changed {key}: {stored_labels[key]!r} is now {expected_labels[key]!r}"
            )
    return lines or ["only the surrounding text of the extract differs"]


def main(argv: list[str] | None = None) -> int:
    """Regenerate the extract, or report that it no longer matches."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--companion",
        type=Path,
        default=DEFAULT_COMPANION_PATH,
        help="Path to a CortexCompanion checkout (default: the sibling directory)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Answer non-zero when the extract differs; write nothing",
    )
    arguments = parser.parse_args(argv)

    try:
        labels = collect_labels(arguments.companion)
    except SyncError as error:
        sys.stderr.write(f"Cortex label sync error: {error}\n")
        return 1

    if not labels:
        sys.stderr.write(
            "Cortex label sync error: no quotable label was found; the resource files are "
            "present but unusable, and writing an empty extract would silently disarm the "
            "documentation guard.\n"
        )
        return 1

    expected = render(labels)
    stored = EXTRACT_PATH.read_text(encoding="utf-8") if EXTRACT_PATH.is_file() else ""

    if expected == stored:
        print(f"Companion label extract is current: {len(labels)} labels.")
        return 0

    if not arguments.check:
        EXTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXTRACT_PATH.write_text(expected, encoding="utf-8", newline="\n")
        print(f"Companion label extract regenerated: {len(labels)} labels.")
        return 0

    sys.stderr.write(
        "Cortex label sync error: the stored Companion label extract no longer matches the "
        "labels Companion ships. The documentation guard is checking names that changed.\n"
    )
    for line in describe_drift(stored, expected):
        sys.stderr.write(line + "\n")
    sys.stderr.write(
        "Run: python scripts/sync_companion_labels.py --companion <CortexCompanion>\n"
        "then update every page that quotes a renamed control.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
