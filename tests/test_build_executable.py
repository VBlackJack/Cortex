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
"""Tests for the canonical PyInstaller distribution-surface builder."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import setuptools

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "packaging" / "build_executable.py"
_GLOBALS = runpy.run_path(str(_SCRIPT), run_name="build_executable_test")
_BUILD_ERROR = cast("type[RuntimeError]", _GLOBALS["ExecutableBuildError"])
_DECLARED_SURFACE = cast(
    "Callable[[Mapping[str, object]], tuple[tuple[str, ...], tuple[str, ...]]]",
    _GLOBALS["declared_distribution_surface"],
)
_ARGUMENTS = cast("Callable[[Path], list[str]]", _GLOBALS["pyinstaller_arguments"])
_DEDICATED_BUILD_PATH = cast("Callable[..., Path]", _GLOBALS["_dedicated_build_path"])
_ASSERT_CLEAN_ANALYSIS_TOC = cast(
    "Callable[[Path], None]",
    _GLOBALS["_assert_clean_analysis_toc"],
)
_BUILD_EXECUTABLE = cast("Callable[..., Path]", _GLOBALS["build_executable"])
_RUNTIME_GLOBALS = cast(
    "dict[str, object]",
    cast("object", _BUILD_EXECUTABLE).__getattribute__("__globals__"),
)


def _values_after(arguments: list[str], option: str) -> set[str]:
    return {
        arguments[index + 1]
        for index, value in enumerate(arguments[:-1])
        if value == option
    }


def test_declared_surface_rejects_an_empty_module_list() -> None:
    metadata: Mapping[str, object] = {
        "tool": {"setuptools": {"packages": ["ingestion"], "py-modules": []}}
    }

    with pytest.raises(_BUILD_ERROR, match="py-modules must be a non-empty list"):
        _DECLARED_SURFACE(metadata)


def test_pyinstaller_arguments_cover_every_distributed_module_and_package() -> None:
    pyproject = cast("Mapping[str, object]", _GLOBALS["_load_pyproject"]())
    packages, modules = _DECLARED_SURFACE(pyproject)
    arguments = _ARGUMENTS(_ROOT / "dist")
    hidden_imports = _values_after(arguments, "--hidden-import")
    collected_packages = _values_after(arguments, "--collect-all")

    assert set(modules) <= hidden_imports
    assert {package.split(".", maxsplit=1)[0] for package in packages} <= collected_packages
    assert {"chromadb", "fastembed", "onnxruntime", "tokenizers"} <= collected_packages
    assert _values_after(arguments, "--copy-metadata") == {"fastembed"}
    assert arguments[-1] == str(_ROOT / "packaging" / "cortex_launcher.py")


def test_analysis_toc_rejects_every_deferred_bundle_module(tmp_path: Path) -> None:
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text("([('bundle_command', 'bundle_command.py', 'PYMODULE')],)\n", encoding="utf-8")
    _ASSERT_CLEAN_ANALYSIS_TOC(toc)

    deferred = cast("tuple[str, ...]", _GLOBALS["_DEFERRED_BUNDLE_MODULES"])
    for module in deferred:
        toc.write_text(
            repr(([(module, f"C:/stale/{module}.py", "PYMODULE")],)),
            encoding="utf-8",
        )
        with pytest.raises(_BUILD_ERROR, match=f"deferred module: {module}"):
            _ASSERT_CLEAN_ANALYSIS_TOC(toc)


def test_build_paths_are_restricted_to_the_exact_dedicated_directory(
    tmp_path: Path,
) -> None:
    expected = _ROOT / "dist"
    assert (
        _DEDICATED_BUILD_PATH(expected, expected=expected, label="Output directory")
        == Path(os.path.abspath(expected))
    )

    for unsafe in (tmp_path, _ROOT, _ROOT / "packaging", _ROOT / "dist-other"):
        with pytest.raises(_BUILD_ERROR, match="must be the dedicated build directory"):
            _DEDICATED_BUILD_PATH(
                unsafe,
                expected=expected,
                label="Output directory",
            )


def test_build_path_rejects_a_link_to_an_external_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    expected = repository / "dist"
    external = tmp_path / "external"
    external.mkdir()

    try:
        if sys.platform == "win32":
            completed = subprocess.run(  # noqa: S603
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(expected), str(external)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.skip(f"Could not create a Windows junction: {completed.stderr}")
        else:
            expected.symlink_to(external, target_is_directory=True)

        dedicated_path = cast("Callable[..., Path]", _GLOBALS["_dedicated_build_path"])
        with pytest.raises(_BUILD_ERROR, match="symbolic link or reparse point"):
            dedicated_path(
                expected,
                expected=expected,
                label="Output directory",
                root=repository,
            )
    finally:
        if expected.exists():
            if sys.platform == "win32":
                expected.rmdir()
            else:
                expected.unlink()


def test_wheel_cleanup_rejects_a_linked_build_tree_without_touching_external_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(setuptools, "setup", lambda **_kwargs: None)
    setup_globals = runpy.run_path(str(_ROOT / "setup.py"), run_name="wheel_setup_test")
    clean = cast("Callable[[], None]", setup_globals["_clean_wheel_build_tree"])
    unsafe_error = cast("type[RuntimeError]", setup_globals["UnsafeBuildPathError"])
    runtime_globals = cast(
        "dict[str, object]",
        cast("object", clean).__getattribute__("__globals__"),
    )

    repository = tmp_path / "repository"
    repository.mkdir()
    build = repository / "build"
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel.bin"
    sentinel.write_bytes(b"must remain unchanged")
    try:
        if sys.platform == "win32":
            completed = subprocess.run(  # noqa: S603
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(build), str(external)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.skip(f"Could not create a Windows junction: {completed.stderr}")
        else:
            build.symlink_to(external, target_is_directory=True)

        monkeypatch.setitem(runtime_globals, "_REPOSITORY_ROOT", repository)
        monkeypatch.setitem(runtime_globals, "_BUILD_ROOT", build)
        with pytest.raises(unsafe_error, match="linked or is not a directory"):
            clean()
        assert sentinel.read_bytes() == b"must remain unchanged"
    finally:
        if os.path.lexists(build):
            if sys.platform == "win32":
                build.rmdir()
            else:
                build.unlink()


def test_builder_runs_the_license_generator_after_pyinstaller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    output = repository / "dist"
    work = repository / "build" / "pyinstaller"
    entry = repository / "packaging" / "cortex_launcher.py"
    license_script = repository / "packaging" / "license_bundle.py"
    entry.parent.mkdir()
    entry.write_text("raise SystemExit(0)\n", encoding="utf-8")
    license_script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    analysis = work / "cortex" / "Analysis-00.toc"
    license_output = output / "licenses"
    license_manifest = license_output / "THIRD_PARTY_LICENSES.json"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if len(calls) == 1:
            output.mkdir(parents=True)
            executable = output / ("cortex.exe" if sys.platform == "win32" else "cortex")
            executable.write_bytes(b"executable")
            analysis.parent.mkdir(parents=True)
            analysis.write_text("([], )\n", encoding="utf-8")
        else:
            license_output.mkdir(parents=True)
            license_manifest.write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setitem(_RUNTIME_GLOBALS, "_REPO_ROOT", repository)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_DEFAULT_OUTPUT_DIR", output)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_WORK_DIR", work)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_ENTRY_PATH", entry)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_ANALYSIS_TOC", analysis)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_LICENSE_BUNDLE_SCRIPT", license_script)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_LICENSE_OUTPUT_DIR", license_output)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_LICENSE_MANIFEST", license_manifest)
    monkeypatch.setitem(
        _RUNTIME_GLOBALS,
        "_dedicated_build_path",
        lambda candidate, **_kwargs: Path(candidate),
    )
    monkeypatch.setitem(_RUNTIME_GLOBALS, "pyinstaller_arguments", lambda _output: ["build"])
    monkeypatch.setitem(_RUNTIME_GLOBALS, "subprocess", SimpleNamespace(run=fake_run))

    result = _BUILD_EXECUTABLE(output_dir=output, clean=False)

    assert result.is_file()
    assert calls == [
        [sys.executable, "build"],
        [
            sys.executable,
            str(license_script),
            "--analysis-toc",
            str(analysis),
            "--output-dir",
            str(license_output),
        ],
    ]


def test_builder_fails_closed_when_license_generation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    output = repository / "dist"
    work = repository / "build" / "pyinstaller"
    entry = repository / "packaging" / "cortex_launcher.py"
    license_script = repository / "packaging" / "license_bundle.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("raise SystemExit(0)\n", encoding="utf-8")
    license_script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    calls = 0

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            output.mkdir(parents=True)
            executable = output / ("cortex.exe" if sys.platform == "win32" else "cortex")
            executable.write_bytes(b"executable")
            analysis = work / "cortex" / "Analysis-00.toc"
            analysis.parent.mkdir(parents=True)
            analysis.write_text("([], )\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setitem(_RUNTIME_GLOBALS, "_REPO_ROOT", repository)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_DEFAULT_OUTPUT_DIR", output)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_WORK_DIR", work)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_ENTRY_PATH", entry)
    monkeypatch.setitem(
        _RUNTIME_GLOBALS,
        "_ANALYSIS_TOC",
        work / "cortex" / "Analysis-00.toc",
    )
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_LICENSE_BUNDLE_SCRIPT", license_script)
    monkeypatch.setitem(_RUNTIME_GLOBALS, "_LICENSE_OUTPUT_DIR", output / "licenses")
    monkeypatch.setitem(
        _RUNTIME_GLOBALS,
        "_LICENSE_MANIFEST",
        output / "licenses" / "THIRD_PARTY_LICENSES.json",
    )
    monkeypatch.setitem(
        _RUNTIME_GLOBALS,
        "_dedicated_build_path",
        lambda candidate, **_kwargs: Path(candidate),
    )
    monkeypatch.setitem(_RUNTIME_GLOBALS, "pyinstaller_arguments", lambda _output: ["build"])
    monkeypatch.setitem(_RUNTIME_GLOBALS, "subprocess", SimpleNamespace(run=fake_run))

    with pytest.raises(_BUILD_ERROR, match="license generation failed with exit code 7"):
        _BUILD_EXECUTABLE(output_dir=output, clean=False)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell contract")
def test_powershell_wrapper_falls_back_when_repository_venv_is_absent() -> None:
    completed = subprocess.run(  # noqa: S603
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_ROOT / "scripts" / "build_installer.ps1"),
            "-WhatIf",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "falling back to 'python' on PATH" in " ".join(completed.stdout.split())
