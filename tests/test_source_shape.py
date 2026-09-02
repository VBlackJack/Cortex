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
"""Ratchet the size of Cortex functions so the known long ones cannot multiply.

13 functions predate this guard. They sit on the publication, sync,
packaging, and diagnostic paths, where a refactor carries more risk than the
length itself, so they are recorded rather than rewritten. Everything else must
stay under the budget, and shrinking a recorded function below the budget must
remove it from the record.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAXIMUM_FUNCTION_LINES = 120
_SKIPPED_DIRECTORIES = frozenset({".git", "__pycache__", "local", "tests", "eval"})

# Accepted at the time the guard was introduced. Never add an entry without a
# recorded reason; prefer extracting the helper the length is asking for.
_RECORDED_LONG_FUNCTIONS = frozenset(
    {
        "confluence_writer/cli.py::main",
        "confluence_writer/writer.py::collect",
        "doctor.py::_client_checks",
        "doctor.py::_inspect_index",
        "doctor.py::run_doctor",
        "indexer.py::_sync_locked_report",
        "ingestion/cli.py::execute_scheduled_attempt",
        "ingestion/engine.py::_assemble",
        "packaging/license_bundle.py::_manifest_file_entries",
        "packaging/license_bundle.py::_verify_manifest_against_surface",
        "packaging/license_bundle.py::generate_license_bundle",
        "packaging/license_bundle.py::verify_license_bundle",
        "sync_hash_aware.py::_sync_files_locked",
    }
)


def _python_sources() -> list[Path]:
    return [
        path
        for path in sorted(_REPO_ROOT.rglob("*.py"))
        if not _SKIPPED_DIRECTORIES.intersection(path.relative_to(_REPO_ROOT).parts)
    ]


def _long_functions() -> set[str]:
    found: set[str] = set()
    for path in _python_sources():
        module = path.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.end_lineno is None:
                continue
            if node.end_lineno - node.lineno + 1 > _MAXIMUM_FUNCTION_LINES:
                found.add(f"{module}::{node.name}")
    return found


def test_no_new_function_exceeds_the_length_budget() -> None:
    introduced = sorted(_long_functions() - _RECORDED_LONG_FUNCTIONS)
    assert not introduced, (
        f"These functions exceed {_MAXIMUM_FUNCTION_LINES} lines and are not "
        f"recorded as accepted: {introduced}. Extract a helper instead."
    )


def test_recorded_long_functions_are_still_long() -> None:
    resolved = sorted(_RECORDED_LONG_FUNCTIONS - _long_functions())
    assert not resolved, (
        f"These functions now fit the budget: {resolved}. Remove them from "
        "_RECORDED_LONG_FUNCTIONS so the ratchet keeps tightening."
    )
