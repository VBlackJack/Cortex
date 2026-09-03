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
"""Stable stderr progress protocol tests."""

from __future__ import annotations

import json

import pytest

from confluence_writer.progress import PROGRESS_PREFIX, emit_progress


def test_progress_is_one_flush_safe_machine_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_progress("staging", 700, 1594)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(PROGRESS_PREFIX)
    assert json.loads(captured.err.removeprefix(PROGRESS_PREFIX)) == {
        "contract_version": 1,
        "current": 700,
        "phase": "staging",
        "total": 1594,
    }


def test_progress_rejects_impossible_counters() -> None:
    with pytest.raises(ValueError, match="0 <= current <= total"):
        emit_progress("conversion", 2, 1)
