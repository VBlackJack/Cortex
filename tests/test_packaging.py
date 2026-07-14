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

# Human CalVer source format: YYYY.MMDD.XX, zero-padded (e.g. 2026.0714.00).
_CALVER_RE = re.compile(r"^\d{4}\.\d{4}\.\d{2}$")


def test_version_is_calver_and_pyproject_uses_the_single_source() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    # Source of truth is the zero-padded human CalVer used for tags and display.
    assert _CALVER_RE.fullmatch(__version__), __version__
    # It must also parse as a valid PEP 440 version. Note: PEP 440 canonical
    # form strips leading zeros from numeric release segments
    # (2026.0714.00 -> 2026.714.0), so we assert validity and value, never
    # string identity with the canonical public form.
    parsed = Version(__version__)
    assert parsed.release[0] == int(__version__.split(".", 1)[0])
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
