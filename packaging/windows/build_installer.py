#!/usr/bin/env python3
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
"""Build the Windows installer only after validating its executable payload."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEFAULT_PAYLOAD: Final[Path] = _REPO_ROOT / "dist" / "cortex.exe"
_INSTALLER_SCRIPT: Final[Path] = Path(__file__).with_name("cortex-installer.iss")
_INSTALLER_OUTPUT: Final[Path] = _REPO_ROOT / "dist-installer" / "Cortex-Setup.exe"
_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{4}\.\d{4}\.\d{2}$")
_RESERVED_ISCC_DEFINES: Final[tuple[str, ...]] = (
    "/dappversion",
    "/dpayloadversionverified",
)


class InstallerBuildError(RuntimeError):
    """Raised when the installer cannot be built without violating its contract."""


def _default_iscc_path() -> Path:
    """Return the conventional Inno Setup 6 compiler path when available."""
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    if program_files_x86:
        return Path(program_files_x86) / "Inno Setup 6" / "ISCC.exe"
    discovered = shutil.which("ISCC.exe") or shutil.which("iscc")
    return Path(discovered) if discovered else Path("ISCC.exe")


def _validate_app_version(app_version: str) -> None:
    if not _VERSION_PATTERN.fullmatch(app_version):
        raise InstallerBuildError(
            f"AppVersion '{app_version}' is not a Cortex CalVer (YYYY.MMDD.XX)."
        )


def validate_payload(executable: Path, app_version: str) -> str:
    """Return the payload version output after an exact AppVersion match."""
    _validate_app_version(app_version)
    if not executable.is_file():
        raise InstallerBuildError(
            f"Installer payload is missing: {executable}. "
            "Rebuild dist/cortex.exe before compiling the installer."
        )

    try:
        completed = subprocess.run(  # noqa: S603
            [str(executable), "--version"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise InstallerBuildError(
            f"Could not execute installer payload '{executable}': {exc}. "
            "Rebuild dist/cortex.exe before compiling the installer."
        ) from exc

    expected_output = app_version
    actual_output = completed.stdout.strip()
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()
        suffix = f" Output: {diagnostic}" if diagnostic else ""
        raise InstallerBuildError(
            f"Installer payload version check failed with exit code "
            f"{completed.returncode}.{suffix} Rebuild dist/cortex.exe before "
            "compiling the installer."
        )
    if actual_output != expected_output:
        displayed_output = actual_output or "<empty>"
        raise InstallerBuildError(
            f"Installer payload version mismatch: expected '{expected_output}', "
            f"got '{displayed_output}'. Rebuild dist/cortex.exe before "
            "compiling the installer."
        )
    return actual_output


def validate_model_payload_dir(model_payload_dir: Path) -> Path:
    """Return a non-empty model payload directory resolved for ISCC."""
    if not model_payload_dir.is_dir():
        raise InstallerBuildError(
            f"Model payload directory is missing: {model_payload_dir}. "
            "Prepare the verified model payload before compiling the installer."
        )
    try:
        if not any(model_payload_dir.iterdir()):
            raise InstallerBuildError(
                f"Model payload directory is empty: {model_payload_dir}. "
                "Prepare the verified model payload before compiling the installer."
            )
    except OSError as exc:
        raise InstallerBuildError(
            f"Could not inspect model payload directory '{model_payload_dir}': {exc}."
        ) from exc
    return model_payload_dir.resolve()


def _resolve_iscc_path(candidate: Path) -> Path:
    if candidate.is_file():
        return candidate.resolve()
    discovered = shutil.which(str(candidate))
    if discovered:
        return Path(discovered).resolve()
    raise InstallerBuildError(f"Inno Setup compiler not found: {candidate}")


def _validate_additional_iscc_arguments(arguments: Sequence[str]) -> None:
    for argument in arguments:
        folded = argument.casefold()
        if any(folded.startswith(prefix) for prefix in _RESERVED_ISCC_DEFINES):
            raise InstallerBuildError(
                f"ISCC argument '{argument}' attempts to override a reserved version define."
            )


def build_installer(
    *,
    app_version: str,
    executable: Path,
    model_payload_dir: Path,
    iscc: Path,
    additional_iscc_arguments: Sequence[str],
) -> Path:
    """Validate the payloads, invoke ISCC, and return the installer path."""
    validated_output = validate_payload(executable, app_version)
    validated_model_payload_dir = validate_model_payload_dir(model_payload_dir)
    _validate_additional_iscc_arguments(additional_iscc_arguments)
    compiler = _resolve_iscc_path(iscc)
    if not _INSTALLER_SCRIPT.is_file():
        raise InstallerBuildError(f"Installer script is missing: {_INSTALLER_SCRIPT}")

    print(f"[installer] Validated payload: {validated_output}", flush=True)
    command = [
        str(compiler),
        f"/DAppVersion={app_version}",
        f"/DPayloadVersionVerified={app_version}",
        f"/DModelPayloadDir={validated_model_payload_dir}",
        *additional_iscc_arguments,
        str(_INSTALLER_SCRIPT),
    ]
    completed = subprocess.run(command, cwd=_REPO_ROOT, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise InstallerBuildError(
            f"Inno Setup compilation failed with exit code {completed.returncode}."
        )
    if not _INSTALLER_OUTPUT.is_file():
        raise InstallerBuildError(
            f"Inno Setup reported success but the installer is missing: {_INSTALLER_OUTPUT}"
        )
    return _INSTALLER_OUTPUT


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate dist/cortex.exe and build the Windows installer."
    )
    parser.add_argument("--app-version", required=True, help="Expected YYYY.MMDD.XX version.")
    parser.add_argument(
        "--payload",
        type=Path,
        default=_DEFAULT_PAYLOAD,
        help="Executable payload to validate and package.",
    )
    parser.add_argument(
        "--model-payload-dir",
        type=Path,
        help="Existing non-empty verified model payload directory.",
    )
    parser.add_argument(
        "--iscc",
        type=Path,
        default=_default_iscc_path(),
        help="Path to the Inno Setup 6 compiler.",
    )
    parser.add_argument(
        "--iscc-argument",
        action="append",
        default=[],
        help="Additional ISCC argument; repeat for multiple arguments.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the executable payload version without invoking ISCC.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fail-closed installer build."""
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.validate_only:
            validated_output = validate_payload(arguments.payload, arguments.app_version)
            print(f"[installer] Validated payload: {validated_output}")
            return 0
        if arguments.model_payload_dir is None:
            raise InstallerBuildError(
                "--model-payload-dir is required when compiling the installer."
            )
        output = build_installer(
            app_version=arguments.app_version,
            executable=arguments.payload,
            model_payload_dir=arguments.model_payload_dir,
            iscc=arguments.iscc,
            additional_iscc_arguments=arguments.iscc_argument,
        )
        print(f"[installer] Built Windows installer: {output}")
        return 0
    except InstallerBuildError as exc:
        print(f"[installer] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
