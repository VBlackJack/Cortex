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
"""Publication-contract tests for PyPI and the MCP Registry."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from packaging.version import Version

from _version import __version__

_ROOT = Path(__file__).resolve().parents[1]
_SERVER_JSON = _ROOT / "server.json"
_CI_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"
_RELEASE_WORKFLOW = _ROOT / ".github" / "workflows" / "release.yml"
_PUBLISH_SCRIPT = _ROOT / "scripts" / "mcp_registry_publish.sh"
_DEV_LOCK = _ROOT / "requirements-dev.lock"
_MODEL_LOCK = _ROOT / "requirements-model.lock"
_WORKFLOW_DIRECTORY = _ROOT / ".github" / "workflows"


def _find_gnu_bash() -> str:
    candidates: list[Path] = []
    discovered = shutil.which("bash")
    if discovered is not None:
        candidates.append(Path(discovered))
    program_files = os.environ.get("ProgramFiles")
    if program_files is not None:
        git_root = Path(program_files) / "Git"
        candidates.extend((git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"))

    checked: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key in checked or not candidate.is_file():
            continue
        checked.add(key)
        completed = subprocess.run(
            [str(candidate), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and "GNU bash" in completed.stdout:
            return str(candidate)

    raise AssertionError("A runnable GNU Bash executable is required.")


def test_server_descriptor_matches_distribution_contract() -> None:
    raw: object = json.loads(_SERVER_JSON.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw["name"] == "io.github.VBlackJack/cortex"
    assert raw["version"] == str(Version(__version__))
    packages = raw["packages"]
    assert isinstance(packages, list)
    assert len(packages) == 1
    package = packages[0]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == "cortex-local-rag"
    assert package["version"] == str(Version(__version__))
    assert package["packageArguments"] == [{"type": "positional", "value": "serve"}]


def test_publish_workflow_is_oidc_only_and_ordered() -> None:
    workflow = _RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "environment: pypi" in workflow
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish@" in workflow
    assert "PYPI_API_TOKEN" not in workflow
    assert "password:" not in workflow
    assert workflow.index("build-dist:") < workflow.index("publish-pypi:")
    assert workflow.index("publish-pypi:") < workflow.index("publish-mcp-registry:")
    assert workflow.index("publish-mcp-registry:") < workflow.index("\n  release:")
    assert "needs: publish-pypi" in workflow
    assert "MCP_SERVER_NAME: io.github.VBlackJack/cortex" in workflow
    assert "PYPI_PACKAGE: cortex-local-rag" in workflow
    assert "MCP_PUBLISHER_VERSION: v1.8.1" in workflow
    assert (
        "MCP_PUBLISHER_SHA256: a06c9096dcb9727c13555b6be26c7effa707b01f06a4c561ba7a3635443cf2cc"
    ) in workflow
    assert "bash scripts/mcp_registry_publish.sh --validate-only" in workflow
    assert "workflow_call:" not in workflow
    assert "uses: ./.github/workflows/publish-pypi.yml" not in workflow
    assert 'tags: ["v*"]' in workflow
    assert "group: release-${{ github.ref }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "SOURCE_DATE_EPOCH=${source_date_epoch}" in workflow
    assert "print(Version(__version__))" in workflow
    assert "python -m build --wheel --no-isolation" in workflow
    assert "Verify exact PyPI publication state" in workflow
    assert "published != local" in workflow
    assert "if: steps.pypi-state.outputs.exists != 'true'" in workflow

    assert "group: ${{ github.workflow }}-${{ github.ref }}" not in workflow
    assert "needs: build" in workflow
    assert "needs: [build-dist, publish-mcp-registry]" in workflow


def test_ci_and_release_jobs_install_only_hash_locked_dependencies() -> None:
    for workflow_path in (_CI_WORKFLOW, _RELEASE_WORKFLOW):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "--require-hashes -r requirements-dev.lock" in workflow
        assert "--no-build-isolation --no-deps -e ." in workflow
        assert 'pip install -e ".[dev' not in workflow

    release = _RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in release
    assert 'pip install --no-deps "${wheel}"' in release
    assert "--require-hashes `\n            -r requirements-model.lock" in release
    assert 'pip install "huggingface-hub==' not in release


def test_dependency_audit_covers_oldest_and_release_python_variants() -> None:
    workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
    release = _RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert 'python-version: ["3.10", "3.12"]' in workflow
    for lock in (
        "requirements.lock",
        "requirements-dev.lock",
        "requirements-model.lock",
    ):
        command = f"python -m pip_audit -r {lock}"
        assert command in workflow
        assert command in release


def test_combined_release_requires_the_matching_companion_tag_and_version() -> None:
    workflow = _RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "repository: VBlackJack/CortexCompanion" in workflow
    assert "github.ref_type == 'tag' && github.ref_name" in workflow
    assert "working-directory: companion-source" in workflow
    assert "dotnet format CortexCompanion.sln --no-restore --verify-no-changes" in workflow
    assert ".\\tools\\ci-csharp-style.ps1" in workflow
    assert "dotnet build CortexCompanion.sln `" in workflow
    assert "-warnaserror" in workflow
    assert "dotnet test CortexCompanion.sln `" in workflow
    assert "--no-build `" in workflow
    assert "-p:PublishProfile=win-x64" in workflow
    assert "[System.Diagnostics.ProcessStartInfo]::new()" in workflow
    assert '$startInfo.ArgumentList.Add("--version")' in workflow
    assert "$startInfo.UseShellExecute = $false" in workflow
    assert "$startInfo.RedirectStandardOutput = $true" in workflow
    assert "$startInfo.RedirectStandardError = $true" in workflow
    assert "$startInfo.CreateNoWindow = $true" in workflow
    assert "$process.WaitForExit()" in workflow
    assert "$versionProcess.WaitForExit()" in workflow
    assert "Get-CompanionVersion" in workflow
    assert "(& .\\dist-companion\\CortexCompanion.exe --version).Trim()" not in workflow
    assert "(& $installedCompanion --version).Trim()" not in workflow
    assert "--companion-payload-dir dist-companion" in workflow


def test_release_asset_names_are_guarded_by_the_live_runner_architecture() -> None:
    workflow = _RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "expected_machine: AMD64" in workflow
    assert "expected_machine: arm64" in workflow
    assert "expected_machine: x86_64" in workflow
    assert "EXPECTED_MACHINE: ${{ matrix.expected_machine }}" in workflow
    assert "actual = platform.machine()" in workflow
    assert "actual.casefold() != expected.casefold()" in workflow


def test_release_publishes_only_self_contained_portable_archives() -> None:
    workflow = _RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "python packaging/archive_portable.py" in workflow
    for archive in (
        "cortex-windows-x64.zip",
        "cortex-macos-arm64.zip",
        "cortex-linux-x64.zip",
    ):
        assert f"archive: {archive}" in workflow
        assert f'"{archive}",' in workflow
    assert 'cp "${{ matrix.binary }}" "out/${{ matrix.artifact }}"' not in workflow
    assert '"Cortex-Setup.exe",' in workflow
    assert "merge-multiple: true" in workflow


def test_locked_build_tools_match_the_declared_exact_versions() -> None:
    lock = _DEV_LOCK.read_text(encoding="utf-8")

    for requirement in (
        "build==1.5.0",
        "pip-audit==2.10.1",
        "pyinstaller==6.21.0",
        "twine==7.0.0",
        "wheel==0.47.0",
    ):
        assert f"{requirement} \\" in lock


def test_model_tool_lock_matches_the_version_committed_in_models_lock() -> None:
    models = json.loads((_ROOT / "models.lock").read_text(encoding="utf-8"))
    requirement = (_ROOT / "requirements-model.txt").read_text(encoding="utf-8")
    lock = _MODEL_LOCK.read_text(encoding="utf-8")
    expected = (
        f"fastembed=={models['fastembed_version']}",
        f"huggingface-hub=={models['huggingface_hub_version']}",
    )

    for pinned_requirement in expected:
        assert pinned_requirement in requirement
        assert f"{pinned_requirement} \\" in lock


def test_every_external_workflow_action_is_pinned_to_an_immutable_commit() -> None:
    action = re.compile(r"^\s*uses[:]\s+([^\s@]+)@([^\s#]+)")
    mutable: list[str] = []

    for workflow_path in sorted(_WORKFLOW_DIRECTORY.glob("*.yml")):
        for line_number, line in enumerate(
            workflow_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            match = action.match(line)
            if match is None or match.group(1).startswith("./"):
                continue
            if re.fullmatch(r"[0-9a-f]{40}", match.group(2)) is None:
                mutable.append(
                    f"{workflow_path.name}:{line_number}:{match.group(1)}@{match.group(2)}"
                )

    assert mutable == []


def test_registry_script_has_safe_bash_syntax() -> None:
    completed = subprocess.run(
        [_find_gnu_bash(), "-n", "scripts/mcp_registry_publish.sh"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    script = _PUBLISH_SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    assert "--dry-run" in script
    assert "--validate-only" in script
    assert 'validate "${MCP_SERVER_JSON_PATH}"' in script
    assert "github-oidc" in script
    assert "sha256sum --check --status" in script
