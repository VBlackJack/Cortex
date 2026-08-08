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
"""Build the standalone Cortex executable from the declared distribution surface."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_PYPROJECT_PATH: Final[Path] = _REPO_ROOT / "pyproject.toml"
_ENTRY_PATH: Final[Path] = _REPO_ROOT / "packaging" / "cortex_launcher.py"
_DEFAULT_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "dist"
_WORK_DIR: Final[Path] = _REPO_ROOT / "build" / "pyinstaller"
_ANALYSIS_TOC: Final[Path] = _WORK_DIR / "cortex" / "Analysis-00.toc"
_LICENSE_BUNDLE_SCRIPT: Final[Path] = _REPO_ROOT / "packaging" / "license_bundle.py"
_LICENSE_OUTPUT_DIR: Final[Path] = _DEFAULT_OUTPUT_DIR / "licenses"
_LICENSE_MANIFEST: Final[Path] = _LICENSE_OUTPUT_DIR / "THIRD_PARTY_LICENSES.json"
_COLLECTED_THIRD_PARTY: Final[tuple[str, ...]] = (
    "chromadb",
    "fastembed",
    "onnxruntime",
    "tokenizers",
)
_ADDITIONAL_HIDDEN_IMPORTS: Final[tuple[str, ...]] = ("truststore",)
_DEFERRED_BUNDLE_MODULES: Final[tuple[str, ...]] = (
    "bundle_export",
    "bundle_recovery",
    "bundle_restore",
    "config_transaction",
    "lock_safety",
)
_MAX_ANALYSIS_TOC_BYTES: Final[int] = 64 * 1024 * 1024


class ExecutableBuildError(RuntimeError):
    """Raised when a standalone build cannot satisfy its fail-closed contract."""


def _load_pyproject(path: Path = _PYPROJECT_PATH) -> Mapping[str, object]:
    try:
        with path.open("rb") as stream:
            return cast("Mapping[str, object]", tomllib.load(stream))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExecutableBuildError(f"Could not read distribution metadata: {path}: {exc}") from exc


def declared_distribution_surface(
    pyproject: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return sorted, non-empty package and module names from setuptools metadata."""
    tool = pyproject.get("tool")
    if not isinstance(tool, Mapping):
        raise ExecutableBuildError("pyproject.toml has no [tool] table.")
    setuptools = tool.get("setuptools")
    if not isinstance(setuptools, Mapping):
        raise ExecutableBuildError("pyproject.toml has no [tool.setuptools] table.")

    raw_packages = setuptools.get("packages")
    raw_modules = setuptools.get("py-modules")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise ExecutableBuildError("[tool.setuptools].packages must be a non-empty list.")
    if not isinstance(raw_modules, list) or not raw_modules:
        raise ExecutableBuildError("[tool.setuptools].py-modules must be a non-empty list.")
    if not all(isinstance(value, str) and value for value in raw_packages):
        raise ExecutableBuildError("Every declared package must be a non-empty string.")
    if not all(isinstance(value, str) and value for value in raw_modules):
        raise ExecutableBuildError("Every declared module must be a non-empty string.")

    packages = tuple(sorted(set(cast("list[str]", raw_packages))))
    modules = tuple(sorted(set(cast("list[str]", raw_modules))))
    return packages, modules


def _dedicated_build_path(
    candidate: Path,
    *,
    expected: Path,
    label: str,
    root: Path = _REPO_ROOT,
) -> Path:
    lexical = Path(os.path.abspath(candidate))
    expected_lexical = Path(os.path.abspath(expected))
    if lexical != expected_lexical:
        raise ExecutableBuildError(
            f"{label} must be the dedicated build directory {expected_lexical}: {lexical}"
        )

    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ExecutableBuildError(
            f"{label} must remain inside the repository: {lexical}"
        ) from exc

    current = root
    components = [current]
    for part in relative.parts:
        current /= part
        components.append(current)
    for component in components:
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ExecutableBuildError(
                f"Could not inspect {label.lower()} component {component}: {exc}"
            ) from exc
        file_attributes = cast("int", getattr(metadata, "st_file_attributes", 0))
        if stat.S_ISLNK(metadata.st_mode) or file_attributes & 0x400:
            raise ExecutableBuildError(
                f"{label} contains a symbolic link or reparse point: {component}"
            )

    return lexical


def pyinstaller_arguments(output_dir: Path) -> list[str]:
    """Return the canonical PyInstaller argument vector for every build surface."""
    packages, modules = declared_distribution_surface(_load_pyproject())
    collected_packages = sorted(
        set(_COLLECTED_THIRD_PARTY).union(
            package.split(".", maxsplit=1)[0] for package in packages
        )
    )
    hidden_imports = sorted(set(modules).union(_ADDITIONAL_HIDDEN_IMPORTS))
    arguments = [
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name",
        "cortex",
        "--paths",
        str(_REPO_ROOT),
        "--copy-metadata",
        "fastembed",
        "--distpath",
        str(output_dir),
        "--workpath",
        str(_WORK_DIR),
        "--specpath",
        str(_WORK_DIR),
    ]
    for package in collected_packages:
        arguments.extend(("--collect-all", package))
    for module in hidden_imports:
        arguments.extend(("--hidden-import", module))
    arguments.append(str(_ENTRY_PATH))
    return arguments


def _assert_clean_analysis_toc(path: Path) -> None:
    """Reject a PyInstaller analysis that retained a deferred bundle module."""
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ExecutableBuildError(f"Could not inspect PyInstaller Analysis TOC: {exc}") from exc
    file_attributes = cast("int", getattr(metadata, "st_file_attributes", 0))
    if (
        stat.S_ISLNK(metadata.st_mode)
        or file_attributes & 0x400
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise ExecutableBuildError(
            f"PyInstaller Analysis TOC is linked or is not a regular file: {path}"
        )
    if metadata.st_size > _MAX_ANALYSIS_TOC_BYTES:
        raise ExecutableBuildError(
            f"PyInstaller Analysis TOC exceeds {_MAX_ANALYSIS_TOC_BYTES} bytes: {path}"
        )
    try:
        content = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise ExecutableBuildError(f"Could not read PyInstaller Analysis TOC: {exc}") from exc
    for module in _DEFERRED_BUNDLE_MODULES:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(module)}(?:\.py[co]?)?(?![A-Za-z0-9_])"
        if re.search(pattern, content):
            raise ExecutableBuildError(
                f"PyInstaller Analysis TOC retained deferred module: {module}"
            )


def build_executable(*, output_dir: Path, clean: bool) -> Path:
    """Build Cortex and return the produced executable after safety checks."""
    resolved_output = _dedicated_build_path(
        output_dir,
        expected=_DEFAULT_OUTPUT_DIR,
        label="Output directory",
    )
    resolved_work = _dedicated_build_path(
        _WORK_DIR,
        expected=_WORK_DIR,
        label="Work directory",
    )
    if not _ENTRY_PATH.is_file():
        raise ExecutableBuildError(f"Entry script is missing: {_ENTRY_PATH}")
    if clean:
        for path in (resolved_work, resolved_output):
            if path.exists():
                shutil.rmtree(path)

    command = [sys.executable, *pyinstaller_arguments(resolved_output)]
    completed = subprocess.run(command, cwd=_REPO_ROOT, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise ExecutableBuildError(
            f"PyInstaller failed with exit code {completed.returncode}."
        )
    _assert_clean_analysis_toc(_ANALYSIS_TOC)

    executable_name = "cortex.exe" if sys.platform == "win32" else "cortex"
    executable = resolved_output / executable_name
    if not executable.is_file():
        raise ExecutableBuildError(
            f"PyInstaller reported success but the executable is missing: {executable}"
        )
    if not _LICENSE_BUNDLE_SCRIPT.is_file():
        raise ExecutableBuildError(
            f"Redistribution license generator is missing: {_LICENSE_BUNDLE_SCRIPT}"
        )
    license_command = [
        sys.executable,
        str(_LICENSE_BUNDLE_SCRIPT),
        "--analysis-toc",
        str(_ANALYSIS_TOC),
        "--output-dir",
        str(_LICENSE_OUTPUT_DIR),
    ]
    license_result = subprocess.run(  # noqa: S603
        license_command,
        cwd=_REPO_ROOT,
        check=False,
    )
    if license_result.returncode != 0:
        raise ExecutableBuildError(
            "Redistribution license generation failed with exit code "
            f"{license_result.returncode}."
        )
    if not _LICENSE_MANIFEST.is_file():
        raise ExecutableBuildError(
            f"License generator reported success but the manifest is missing: "
            f"{_LICENSE_MANIFEST}"
        )
    return executable


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help="Dedicated output directory; must resolve to repository dist.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the dedicated PyInstaller work/output directories first.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the canonical executable build."""
    arguments = _build_parser().parse_args(argv)
    try:
        executable = build_executable(
            output_dir=arguments.output_dir,
            clean=arguments.clean,
        )
    except ExecutableBuildError as exc:
        print(f"[build] ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"[build] Built standalone executable: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
