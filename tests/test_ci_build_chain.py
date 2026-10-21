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
"""Keep the CI build-chain rehearsal identical to the release build commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import yaml

_WORKFLOWS: Final[Path] = Path(__file__).resolve().parents[1] / ".github" / "workflows"
_REHEARSAL_JOB: Final[str] = "build-chain"
_RELEASE_VENV_BIN: Final[str] = "wheel-smoke/bin/"
_WINDOWS_VENV_BIN: Final[str] = "wheel-smoke/Scripts/"
_MATRIX_KEYS: Final[tuple[str, ...]] = ("archive", "binary", "binary_name")
_LICENSE_ENV: Final[tuple[str, ...]] = ("CPYTHON_LICENSE_URL", "CPYTHON_LICENSE_SHA256")
_FORBIDDEN_IN_REHEARSAL: Final[tuple[str, ...]] = (
    "actions/upload-artifact@",
    "signtool",
    "ISCC.exe",
    "build_windows_installer",
    "gh-action-pypi-publish",
    "action-gh-release",
    "secrets.",
)


def _workflow(name: str) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", yaml.safe_load((_WORKFLOWS / name).read_text("utf-8")))


def _ci_job() -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", _workflow("ci.yml")["jobs"][_REHEARSAL_JOB])


def _release_job(name: str) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", _workflow("release.yml")["jobs"][name])


def _steps(job: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    return cast("Sequence[Mapping[str, Any]]", job["steps"])


def _step_running(job: Mapping[str, Any], marker: str) -> Mapping[str, Any]:
    matches = [step for step in _steps(job) if marker in str(step.get("run", ""))]
    assert len(matches) == 1, f"Expected one step running {marker!r}, found {len(matches)}."
    return matches[0]


def _command(job: Mapping[str, Any], prefix: str) -> list[str]:
    """Return the command line starting with prefix, with its continuation lines."""
    lines = str(_step_running(job, prefix)["run"]).splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip().startswith(prefix))
    command = [lines[start]]
    while command[-1].rstrip().endswith("\\"):
        command.append(lines[start + len(command)])
    return command


def _release_windows_entry() -> Mapping[str, Any]:
    entries = _release_job("build")["strategy"]["matrix"]["include"]
    return cast(
        "Mapping[str, Any]",
        next(entry for entry in entries if entry["os"] == "windows-latest"),
    )


def test_rehearsal_is_skipped_on_schedule_and_bounded() -> None:
    job = _ci_job()
    assert job["if"] == "github.event_name != 'schedule'"
    assert job["runs-on"] == "windows-latest"
    assert isinstance(job["timeout-minutes"], int)
    assert 0 < job["timeout-minutes"] <= 60
    assert job["permissions"] == {"contents": "read"}


def test_rehearsal_freezes_the_executable_exactly_as_the_release() -> None:
    marker = "python packaging/build_executable.py"
    release = _step_running(_release_job("build"), marker)
    rehearsal = _step_running(_ci_job(), marker)
    assert rehearsal["run"] == release["run"]
    assert rehearsal.get("shell") == release.get("shell")


def test_rehearsal_materializes_the_same_cpython_license() -> None:
    marker = 'os.environ["CPYTHON_LICENSE_URL"]'
    release = _step_running(_release_job("build"), marker)
    rehearsal = _step_running(_ci_job(), marker)
    assert rehearsal["run"] == release["run"]
    release_env = _workflow("release.yml")["env"]
    for name in _LICENSE_ENV:
        assert _ci_job()["env"][name] == release_env[name], name


def test_rehearsal_stages_the_portable_archive_exactly_as_the_release() -> None:
    prefix = "python packaging/archive_portable.py"
    release = _command(_release_job("build"), prefix)
    assert len(release) > 1, "The release archive command lost its arguments."
    assert _command(_ci_job(), prefix) == release
    rehearsal_entries = _ci_job()["strategy"]["matrix"]["include"]
    assert len(rehearsal_entries) == 1
    windows = _release_windows_entry()
    for key in _MATRIX_KEYS:
        assert rehearsal_entries[0][key] == windows[key], key


def test_rehearsal_builds_and_smokes_the_wheel_exactly_as_the_release() -> None:
    build_command = "python -m build --wheel --no-isolation"
    release = _release_job("build-dist")
    rehearsal = _ci_job()
    assert _step_running(rehearsal, build_command)["run"] == build_command
    assert _step_running(release, build_command)["run"] == build_command
    assert "python -m twine check dist/" in str(_step_running(rehearsal, "twine check")["run"])

    marker = "python -m venv wheel-smoke"
    release_smoke = str(_step_running(release, marker)["run"])
    rehearsal_smoke = str(_step_running(rehearsal, marker)["run"])
    assert _RELEASE_VENV_BIN in release_smoke
    assert rehearsal_smoke == release_smoke.replace(_RELEASE_VENV_BIN, _WINDOWS_VENV_BIN)


def test_rehearsal_installs_like_the_gate_with_the_same_pinned_actions() -> None:
    gate = _workflow("ci.yml")["jobs"]["gate"]
    rehearsal = _ci_job()
    marker = "--require-hashes -r requirements-dev.lock"
    assert _step_running(rehearsal, marker)["run"] == _step_running(gate, marker)["run"]
    gate_actions = {step["uses"] for step in _steps(gate) if "uses" in step}
    rehearsal_actions = {step["uses"] for step in _steps(rehearsal) if "uses" in step}
    assert rehearsal_actions == gate_actions
    setup = next(step for step in _steps(rehearsal) if "setup-python" in step.get("uses", ""))
    gate_setup = next(step for step in _steps(gate) if "setup-python" in step.get("uses", ""))
    assert setup["with"]["cache"] == gate_setup["with"]["cache"]
    assert setup["with"]["cache-dependency-path"] == gate_setup["with"]["cache-dependency-path"]
    assert setup["with"]["python-version"] == "3.13"


def test_rehearsal_publishes_and_signs_nothing() -> None:
    text = yaml.safe_dump(dict(_ci_job()))
    for forbidden in _FORBIDDEN_IN_REHEARSAL:
        assert forbidden not in text, forbidden
