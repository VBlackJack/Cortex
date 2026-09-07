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
"""Unit tests for the Companion label extract synchronization."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_companion_labels.py"


def _load_sync() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_companion_labels", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_sync()

_RESOURCE_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<root>
  <resheader name="resmimetype"><value>text/microsoft-resx</value></resheader>
"""


def _write_companion(root: Path, neutral: dict[str, str], french: dict[str, str]) -> Path:
    localization = root / "src" / "CortexCompanion" / "Localization"
    localization.mkdir(parents=True)
    for name, values in (("UiStrings.resx", neutral), ("UiStrings.fr.resx", french)):
        body = "".join(
            f'  <data name="{key}" xml:space="preserve"><value>{value}</value></data>\n'
            for key, value in values.items()
        )
        (localization / name).write_text(
            _RESOURCE_HEADER + body + "</root>\n", encoding="utf-8"
        )
    return root


_NEUTRAL = {
    "PagesNavigation": "Confluence pages",
    "SettingsSaveAndConnect": "Save and connect",
    "StatusOk": "ok",
    "AppTitle": "Cortex Companion",
    "SearchMode": "Mode",
}
_FRENCH = {
    "PagesNavigation": "Pages Confluence",
    "SettingsSaveAndConnect": "Enregistrer et connecter",
    "StatusOk": "ok",
    "AppTitle": "Cortex Companion",
    "SearchMode": "Mode",
}


def test_only_multiword_labels_that_differ_are_captured(tmp_path: Path) -> None:
    """A short or single-word value is a configuration key as often as a control name."""
    labels = sync.collect_labels(_write_companion(tmp_path, _NEUTRAL, _FRENCH))

    assert [label.key for label in labels] == ["PagesNavigation", "SettingsSaveAndConnect"]


def test_a_renamed_label_fails_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    companion = _write_companion(tmp_path / "peer", _NEUTRAL, _FRENCH)
    extract = tmp_path / "companion_ui_labels.json"
    monkeypatch.setattr(sync, "EXTRACT_PATH", extract)
    assert sync.main(["--companion", str(companion)]) == 0

    renamed = dict(_NEUTRAL)
    renamed["SettingsSaveAndConnect"] = "Save and reconnect"
    _write_companion(tmp_path / "renamed", renamed, _FRENCH)

    assert sync.main(["--check", "--companion", str(tmp_path / "renamed")]) == 1
    assert sync.main(["--check", "--companion", str(companion)]) == 0


def test_regeneration_is_the_documented_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    companion = _write_companion(tmp_path / "peer", _NEUTRAL, _FRENCH)
    extract = tmp_path / "companion_ui_labels.json"
    monkeypatch.setattr(sync, "EXTRACT_PATH", extract)

    assert sync.main(["--companion", str(companion)]) == 0

    stored = json.loads(extract.read_text(encoding="utf-8"))
    assert [entry["key"] for entry in stored["labels"]] == [
        "PagesNavigation",
        "SettingsSaveAndConnect",
    ]
    assert extract.read_bytes().endswith(b"\n")
    assert b"\r\n" not in extract.read_bytes()


def test_resources_without_a_usable_label_never_disarm_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty extract would silently stop the documentation guard from checking anything."""
    companion = _write_companion(tmp_path / "peer", {"StatusOk": "ok"}, {"StatusOk": "ok"})
    monkeypatch.setattr(sync, "EXTRACT_PATH", tmp_path / "companion_ui_labels.json")

    assert sync.main(["--companion", str(companion)]) == 1


def test_a_missing_resource_file_is_reported_not_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "EXTRACT_PATH", tmp_path / "companion_ui_labels.json")

    assert sync.main(["--check", "--companion", str(tmp_path / "absent")]) == 1


def test_the_committed_extract_matches_the_rules_it_documents() -> None:
    """The stored extract must be reproducible, not hand-edited."""
    stored = json.loads(sync.EXTRACT_PATH.read_text(encoding="utf-8"))

    assert stored["source"] == sync.EXTRACT_SOURCE
    assert stored["note"] == sync.EXTRACT_NOTE
    assert stored["labels"] == sorted(stored["labels"], key=lambda entry: entry["key"])
    for entry in stored["labels"]:
        assert sync.is_quotable(entry["fr"], entry["en"]), entry["key"]
