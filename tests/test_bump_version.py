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
