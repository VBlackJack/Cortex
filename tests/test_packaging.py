# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Packaging, version, dependency and source-policy contract tests."""

from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 acceptance
    import tomli as tomllib

from _version import __version__

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"


def test_version_is_semver_and_pyproject_uses_the_single_source() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert Version(__version__).public == __version__
    assert "version" in project["project"]["dynamic"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "_version.__version__"
    }


def test_requirements_is_the_single_runtime_dependency_source() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dynamic = project["tool"]["setuptools"]["dynamic"]
    requirement_lines = [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    parsed = [Requirement(line) for line in requirement_lines]

    assert "dependencies" in project["project"]["dynamic"]
    assert dynamic["dependencies"] == {"file": ["requirements.txt"]}
    assert {requirement.name for requirement in parsed} == {
        "mcp",
        "chromadb",
        "fastembed",
        "pydantic",
        "pdfplumber",
        "filelock",
        "tomli",
    }
    assert all(str(requirement.specifier).startswith("==") for requirement in parsed)
    assert next(requirement for requirement in parsed if requirement.name == "tomli").marker


def test_every_python_source_has_apache_header() -> None:
    excluded_parts = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "local",
    }
    missing: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part in excluded_parts for part in path.parts):
            continue
        opening = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
        if (
            "Copyright 2026 Julien Bombled" not in opening
            or "Licensed under the Apache License" not in opening
        ):
            missing.append(path.relative_to(ROOT).as_posix())

    assert missing == []


def test_no_duplicated_chroma_offset_loops_remain() -> None:
    consumers = [
        ROOT / "freshness.py",
        ROOT / "sync_hash_aware.py",
        ROOT / "sync_summary.py",
        ROOT / "scripts" / "b2_delete_missing.py",
    ]
    offset_loop = re.compile(r"\boffset\s*(?:=|\+=)")

    assert {
        path.relative_to(ROOT).as_posix()
        for path in consumers
        if offset_loop.search(path.read_text(encoding="utf-8"))
    } == set()
