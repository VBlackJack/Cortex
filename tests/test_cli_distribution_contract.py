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
"""Distribution coverage tests for the Cortex CLI dispatcher imports."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 acceptance
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parents[1]
_CLI = _ROOT / "cli.py"
_PYPROJECT = _ROOT / "pyproject.toml"


def _imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def _is_local_import(module: str) -> bool:
    return (_ROOT / f"{module}.py").is_file() or (_ROOT / module).is_dir()


def test_cli_local_imports_are_declared_in_the_distribution() -> None:
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    setuptools = project["tool"]["setuptools"]
    distributed_roots = set(setuptools["py-modules"])
    distributed_roots.update(package.partition(".")[0] for package in setuptools["packages"])

    imported_roots = _imported_roots(_CLI.read_text(encoding="utf-8"))
    local_imports = {
        module
        for module in imported_roots
        if module not in sys.stdlib_module_names and _is_local_import(module)
    }

    assert local_imports <= distributed_roots, sorted(local_imports - distributed_roots)
