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
"""Packaging, version, dependency and source-policy contract tests."""

from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path
from types import ModuleType

import pytest
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
LAUNCHER = ROOT / "packaging" / "cortex_launcher.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
WINDOWS_BUILD_SCRIPT = ROOT / "scripts" / "build_installer.ps1"
POSIX_BUILD_SCRIPT = ROOT / "scripts" / "build_installer.sh"
MODEL_MANIFEST_WORKFLOW = ROOT / ".github" / "workflows" / "generate-model-manifest.yml"

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
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "_version.__version__"}


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
        "truststore",
        "tomli",
    }
    assert all(str(requirement.specifier).startswith("==") for requirement in parsed)
    assert next(requirement for requirement in parsed if requirement.name == "tomli").marker


def test_standalone_distribution_contract_is_declared() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    launcher = LAUNCHER.read_text(encoding="utf-8")
    release = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert project["project"]["optional-dependencies"]["build"] == ["pyinstaller>=6.0"]
    assert "from cli import main" in launcher
    assert launcher.index("truststore.inject_into_ssl()") < launcher.index("from cli import main")
    assert launcher.index("activate_if_embedded()") < launcher.index("from cli import main")
    assert 'tags: ["v*"]' in release
    assert "--hidden-import truststore" in release
    assert "--hidden-import offline_models" in release
    assert '"truststore"' in WINDOWS_BUILD_SCRIPT.read_text(encoding="utf-8")
    assert '"offline_models"' in WINDOWS_BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "--hidden-import truststore" in POSIX_BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "--hidden-import offline_models" in POSIX_BUILD_SCRIPT.read_text(encoding="utf-8")
    for artifact in (
        "cortex-windows-x64.exe",
        "cortex-macos-arm64",
        "cortex-linux-x64",
    ):
        assert artifact in release


def test_model_manifest_workflow_is_manual_and_uploads_only_attestation() -> None:
    workflow = MODEL_MANIFEST_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "scripts/model_payload.py fetch" in workflow
    assert "scripts/model_payload.py smoke" in workflow
    assert "scripts/model_payload.py generate" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "path: model-attestation" in workflow
    upload_step = workflow[workflow.index("uses: actions/upload-artifact@v4") :]
    assert "cortex-model-snapshot" not in upload_step


def test_launcher_injects_truststore_before_importing_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    truststore_module = ModuleType("truststore")
    truststore_module.inject_into_ssl = lambda: calls.append("inject")  # type: ignore[attr-defined]
    offline_models_module = ModuleType("offline_models")

    def activate() -> None:
        calls.append("offline")

    offline_models_module.activate_if_embedded = activate  # type: ignore[attr-defined]
    cli_module = ModuleType("cli")
    cli_module.main = lambda: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "truststore", truststore_module)
    monkeypatch.setitem(sys.modules, "offline_models", offline_models_module)
    monkeypatch.setitem(sys.modules, "cli", cli_module)

    runpy.run_path(str(LAUNCHER), run_name="test_cortex_launcher")

    assert calls == ["inject", "offline"]


def test_launcher_reports_truststore_injection_failure_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    truststore_module = ModuleType("truststore")

    def fail_injection() -> None:
        raise RuntimeError("native store unavailable")

    truststore_module.inject_into_ssl = fail_injection  # type: ignore[attr-defined]
    offline_models_module = ModuleType("offline_models")
    offline_models_module.activate_if_embedded = lambda: None  # type: ignore[attr-defined]
    cli_module = ModuleType("cli")
    cli_module.main = lambda: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "truststore", truststore_module)
    monkeypatch.setitem(sys.modules, "offline_models", offline_models_module)
    monkeypatch.setitem(sys.modules, "cli", cli_module)

    runpy.run_path(str(LAUNCHER), run_name="test_cortex_launcher")

    assert (
        capsys.readouterr().err
        == "[cortex] truststore injection failed: native store unavailable\n"
    )


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
