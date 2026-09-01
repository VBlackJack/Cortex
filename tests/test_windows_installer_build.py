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
"""Tests for the fail-closed Windows installer build contract."""

from __future__ import annotations

import runpy
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BUILD_SCRIPT = _ROOT / "packaging" / "windows" / "build_installer.py"
_INSTALLER_SCRIPT = _ROOT / "packaging" / "windows" / "cortex-installer.iss"
_RELEASE_WORKFLOW = _ROOT / ".github" / "workflows" / "release.yml"
_SCRIPT_GLOBALS = runpy.run_path(str(_BUILD_SCRIPT), run_name="installer_build_test")
_BUILD_ERROR = cast("type[RuntimeError]", _SCRIPT_GLOBALS["InstallerBuildError"])
_VALIDATE_PAYLOAD = cast(
    "Callable[[Path, str], str]",
    _SCRIPT_GLOBALS["validate_payload"],
)
_VALIDATE_MODEL_PAYLOAD_DIR = cast(
    "Callable[[Path], Path]",
    _SCRIPT_GLOBALS["validate_model_payload_dir"],
)
_VALIDATE_COMPANION_PAYLOAD_DIR = cast(
    "Callable[[Path, str], Path]",
    _SCRIPT_GLOBALS["validate_companion_payload_dir"],
)
_VALIDATE_CONVERTER_PAYLOAD_DIR = cast(
    "Callable[[Path], Path]",
    _SCRIPT_GLOBALS["validate_converter_payload_dir"],
)
_VALIDATE_ISCC_ARGUMENTS = cast(
    "Callable[[Sequence[str]], None]",
    _SCRIPT_GLOBALS["_validate_additional_iscc_arguments"],
)
_VALIDATE_INSTALLER_OUTPUT = cast(
    "Callable[..., Path]",
    _SCRIPT_GLOBALS["_validate_installer_output_path"],
)
_BUILD_INSTALLER = cast("Callable[..., Path]", _SCRIPT_GLOBALS["build_installer"])
_MAIN = cast(
    "Callable[[Sequence[str] | None], int]",
    _SCRIPT_GLOBALS["main"],
)


def _payload(tmp_path: Path) -> Path:
    executable = tmp_path / "cortex.exe"
    executable.write_bytes(b"placeholder")
    return executable


def _companion_payload(tmp_path: Path) -> Path:
    payload_dir = tmp_path / "companion publish"
    payload_dir.mkdir()
    (payload_dir / "CortexCompanion.exe").write_bytes(b"placeholder")
    return payload_dir


def _converter_payload(tmp_path: Path) -> Path:
    payload_dir = tmp_path / "converter publish"
    payload_dir.mkdir()
    (payload_dir / "ConfluenceRAGBuilder.Console.exe").write_bytes(b"placeholder")
    (payload_dir / "LICENSE.txt").write_text("Apache License", encoding="utf-8")
    return payload_dir


def test_invalid_calver_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(_BUILD_ERROR, match="not a Cortex CalVer"):
        _VALIDATE_PAYLOAD(tmp_path / "missing.exe", "2026.721.1")


def test_missing_executable_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "missing.exe"

    with pytest.raises(_BUILD_ERROR, match="Installer payload is missing") as error:
        _VALIDATE_PAYLOAD(missing, "2026.0721.01")
    assert "Rebuild dist/cortex.exe" in str(error.value)


def test_payload_version_accepts_an_exact_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _payload(tmp_path)

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == [str(executable), "--version"]
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=0,
            stdout="2026.0721.01\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _VALIDATE_PAYLOAD(executable, "2026.0721.01") == "2026.0721.01"


def test_payload_version_rejects_a_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _payload(tmp_path)

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=0,
            stdout="2026.0715.01\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(_BUILD_ERROR, match="payload version mismatch") as error:
        _VALIDATE_PAYLOAD(executable, "2026.0721.01")
    assert "expected '2026.0721.01'" in str(error.value)
    assert "got '2026.0715.01'" in str(error.value)
    assert "Rebuild dist/cortex.exe" in str(error.value)


def test_missing_companion_payload_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(_BUILD_ERROR, match="Companion payload directory is missing"):
        _VALIDATE_COMPANION_PAYLOAD_DIR(tmp_path / "missing", "2026.0721.01")


def test_companion_payload_version_rejects_a_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_dir = _companion_payload(tmp_path)

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=0,
            stdout="2026.0715.01\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(_BUILD_ERROR, match="Companion payload version mismatch"):
        _VALIDATE_COMPANION_PAYLOAD_DIR(payload_dir, "2026.0721.01")


@pytest.mark.parametrize(
    "argument",
    [
        "/DAppVersion=2026.0721.99",
        "/DCompanionPayloadDir=C:" + chr(92) + "untrusted",
        "/DCompanionPayloadVersionVerified=2026.0721.99",
        "/DConverterPayloadDir=C:" + chr(92) + "untrusted",
        "/DConverterPayloadVerified=0",
        "/DModelPayloadDir=C:" + chr(92) + "untrusted",
        "/DPayloadVersionVerified=2026.0721.99",
    ],
)
def test_reserved_version_defines_cannot_be_overridden(argument: str) -> None:
    with pytest.raises(_BUILD_ERROR, match="reserved version define"):
        _VALIDATE_ISCC_ARGUMENTS([argument])


def test_missing_model_payload_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(_BUILD_ERROR, match="Model payload directory is missing"):
        _VALIDATE_MODEL_PAYLOAD_DIR(tmp_path / "missing")


def test_converter_payload_requires_a_successful_machine_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_dir = _converter_payload(tmp_path)

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "not-json", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(_BUILD_ERROR, match="did not return valid JSON"):
        _VALIDATE_CONVERTER_PAYLOAD_DIR(payload_dir)


def test_empty_model_payload_directory_is_rejected(tmp_path: Path) -> None:
    model_payload_dir = tmp_path / "model-payload"
    model_payload_dir.mkdir()

    with pytest.raises(_BUILD_ERROR, match="Model payload directory is empty"):
        _VALIDATE_MODEL_PAYLOAD_DIR(model_payload_dir)


def test_compile_requires_the_model_payload_argument(capsys: pytest.CaptureFixture[str]) -> None:
    assert _MAIN(["--app-version", "2026.0721.01"]) == 1
    assert "--model-payload-dir is required" in capsys.readouterr().err


def test_nominal_build_constructs_the_expected_iscc_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _payload(tmp_path)
    companion_payload_dir = _companion_payload(tmp_path)
    converter_payload_dir = _converter_payload(tmp_path)
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"placeholder")
    model_payload_dir = tmp_path / "model payload"
    model_payload_dir.mkdir()
    (model_payload_dir / "manifest.json").write_text("{}", encoding="utf-8")
    installer_output = tmp_path / "dist-installer" / "Cortex-Setup.exe"
    installer_output.parent.mkdir()
    installer_output.write_bytes(b"stale installer")
    build_globals = cast("dict[str, object]", _BUILD_INSTALLER.__globals__)
    monkeypatch.setitem(build_globals, "_REPO_ROOT", tmp_path)
    monkeypatch.setitem(build_globals, "_INSTALLER_OUTPUT", installer_output)
    commands: list[Sequence[str]] = []

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command in (
            [str(executable), "--version"],
            [
                str(companion_payload_dir / "CortexCompanion.exe"),
                "--version",
            ],
        ):
            return subprocess.CompletedProcess(
                args=list(command),
                returncode=0,
                stdout="2026.0721.01\n",
                stderr="",
            )
        if command == [
            str(converter_payload_dir / "ConfluenceRAGBuilder.Console.exe"),
            "--probe",
        ]:
            return subprocess.CompletedProcess(
                args=list(command),
                returncode=0,
                stdout='{"tool_version":"1.2.0","schema_version":1}\n',
                stderr="",
            )
        installer_output.write_bytes(b"installer")
        return subprocess.CompletedProcess(args=list(command), returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _BUILD_INSTALLER(
        app_version="2026.0721.01",
        executable=executable,
        companion_payload_dir=companion_payload_dir,
        converter_payload_dir=converter_payload_dir,
        model_payload_dir=model_payload_dir,
        iscc=compiler,
        additional_iscc_arguments=["/Qp"],
    )

    assert result == installer_output
    assert installer_output.read_bytes() == b"installer"
    assert commands[3] == [
        str(compiler.resolve()),
        "/DAppVersion=2026.0721.01",
        "/DPayloadVersionVerified=2026.0721.01",
        f"/DCompanionPayloadDir={companion_payload_dir.resolve()}",
        "/DCompanionPayloadVersionVerified=2026.0721.01",
        f"/DConverterPayloadDir={converter_payload_dir.resolve()}",
        "/DConverterPayloadVerified=1",
        f"/DModelPayloadDir={model_payload_dir.resolve()}",
        "/Qp",
        str(_INSTALLER_SCRIPT),
    ]


def test_successful_noop_compiler_cannot_reuse_a_stale_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _payload(tmp_path)
    companion_payload_dir = _companion_payload(tmp_path)
    converter_payload_dir = _converter_payload(tmp_path)
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"placeholder")
    model_payload_dir = tmp_path / "model payload"
    model_payload_dir.mkdir()
    (model_payload_dir / "manifest.json").write_text("{}", encoding="utf-8")
    installer_output = tmp_path / "dist-installer" / "Cortex-Setup.exe"
    installer_output.parent.mkdir()
    installer_output.write_bytes(b"stale installer")
    build_globals = cast("dict[str, object]", _BUILD_INSTALLER.__globals__)
    monkeypatch.setitem(build_globals, "_REPO_ROOT", tmp_path)
    monkeypatch.setitem(build_globals, "_INSTALLER_OUTPUT", installer_output)

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command in (
            [str(executable), "--version"],
            [str(companion_payload_dir / "CortexCompanion.exe"), "--version"],
        ):
            return subprocess.CompletedProcess(
                args=list(command),
                returncode=0,
                stdout="2026.0721.01\n",
                stderr="",
            )
        if command == [
            str(converter_payload_dir / "ConfluenceRAGBuilder.Console.exe"),
            "--probe",
        ]:
            return subprocess.CompletedProcess(
                args=list(command),
                returncode=0,
                stdout='{"tool_version":"1.2.0","schema_version":1}\n',
                stderr="",
            )
        return subprocess.CompletedProcess(args=list(command), returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(_BUILD_ERROR, match="reported success but the installer is missing"):
        _BUILD_INSTALLER(
            app_version="2026.0721.01",
            executable=executable,
            companion_payload_dir=companion_payload_dir,
            converter_payload_dir=converter_payload_dir,
            model_payload_dir=model_payload_dir,
            iscc=compiler,
            additional_iscc_arguments=[],
        )
    assert not installer_output.exists()


def test_installer_output_rejects_a_linked_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    output_directory = repository / "dist-installer"

    if sys.platform == "win32":
        completed = subprocess.run(  # noqa: S603
            [
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(output_directory),
                str(external),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"Could not create a Windows junction: {completed.stderr}")
    else:
        output_directory.symlink_to(external, target_is_directory=True)

    with pytest.raises(_BUILD_ERROR, match="symbolic link or reparse point"):
        _VALIDATE_INSTALLER_OUTPUT(
            output_directory / "Cortex-Setup.exe",
            repository_root=repository,
        )


def test_ci_and_iss_require_the_shared_version_guard() -> None:
    installer = _INSTALLER_SCRIPT.read_text(encoding="utf-8")
    workflow = _RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "#ifndef PayloadVersionVerified" in installer
    assert "#if !SameStr(AppVersion, PayloadVersionVerified)" in installer
    assert "#if !SameStr(AppVersion, CompanionPayloadVersionVerified)" in installer
    assert "#ifndef ConverterPayloadVerified" in installer
    assert 'DestDir: "{app}\\Converters"' in installer
    assert "CloseApplications=force" in installer
    assert "CloseApplicationsFilter=cortex.exe,CortexCompanion.exe" in installer
    assert 'DestDir: "{app}\\Companion"' in installer
    assert "packaging\\windows\\build_installer.py" in workflow
    assert "& $iscc" not in workflow
