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
"""Unit tests for the CalVer logic in scripts/bump_version.py."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bump_version.py"


def _load_bump() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bump_version", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump = _load_bump()


def test_new_day_starts_counter_at_zero() -> None:
    assert bump.next_calver("2026.0712.03", date(2026, 7, 14)) == "2026.0714.00"


def test_same_day_increments_counter() -> None:
    assert bump.next_calver("2026.0714.00", date(2026, 7, 14)) == "2026.0714.01"


def test_non_calver_current_starts_at_zero() -> None:
    assert bump.next_calver("0.1.0", date(2026, 7, 14)) == "2026.0714.00"


def test_counter_beyond_nine_keeps_two_digit_padding() -> None:
    assert bump.next_calver("2026.0714.09", date(2026, 7, 14)) == "2026.0714.10"


def test_calver_normalization_matches_pypi() -> None:
    assert bump.normalize_calver("2026.0808.00") == "2026.808.0"


def test_invalid_calendar_date_is_rejected() -> None:
    try:
        bump.normalize_calver("2026.0230.00")
    except ValueError as error:
        assert "day is out of range" in str(error)
    else:
        raise AssertionError("An invalid Cortex calendar date was accepted")


def test_server_versions_are_updated_together(tmp_path: Path) -> None:
    server_path = tmp_path / "server.json"
    server_path.write_bytes(
        b'{"version":"2026.805.0","packages":[{"version":"2026.805.0"}]}\r\n'
    )

    bump.write_server_version(server_path, "2026.0808.00")

    assert b"\r" not in server_path.read_bytes()
    raw = json.loads(server_path.read_text(encoding="utf-8"))
    assert raw["version"] == "2026.808.0"
    assert raw["packages"][0]["version"] == "2026.808.0"
