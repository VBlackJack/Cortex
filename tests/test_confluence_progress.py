# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
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
