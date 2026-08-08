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
"""Transitive source and built-wheel coverage for the Cortex distribution."""

from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 acceptance
    import tomli as tomllib

from _version import __version__

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_DEFERRED_MODULES = (
    "bundle_export",
    "bundle_recovery",
    "bundle_restore",
    "config_transaction",
    "lock_safety",
)


def _distribution_sources(setuptools: dict[str, object]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for module in setuptools["py-modules"]:
        assert isinstance(module, str)
        source = _ROOT.joinpath(*module.split(".")).with_suffix(".py")
        assert source.is_file(), module
        sources[module] = source
    for package in setuptools["packages"]:
        assert isinstance(package, str)
        package_root = _ROOT.joinpath(*package.split("."))
        assert (package_root / "__init__.py").is_file(), package
        for source in package_root.glob("*.py"):
            module = package if source.name == "__init__.py" else f"{package}.{source.stem}"
            sources[module] = source
    return sources


def _imported_modules(module: str, source: Path) -> set[str]:
    imported: set[str] = set()
    package = module if source.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_name = f"{'.' * node.level}{node.module or ''}"
                base = importlib.util.resolve_name(relative_name, package)
            else:
                base = node.module
            if base:
                imported.add(base)
            for alias in node.names:
                if alias.name != "*":
                    imported.add(f"{base}.{alias.name}" if base else alias.name)
    return imported


def _is_local_module(module: str) -> bool:
    path = _ROOT.joinpath(*module.split("."))
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def _project_setuptools() -> dict[str, object]:
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return project["tool"]["setuptools"]


def _copy_wheel_project(destination: Path, sources: dict[str, Path]) -> None:
    destination.mkdir()
    for name in (
        "LICENSE",
        "README.en.md",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
    ):
        shutil.copy2(_ROOT / name, destination / name)
    for source in sources.values():
        target = destination / source.relative_to(_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for schema in (_ROOT / "confluence_writer" / "resources").glob("*.schema.json"):
        target = destination / schema.relative_to(_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(schema, target)


def test_all_distributed_modules_close_over_local_imports() -> None:
    sources = _distribution_sources(_project_setuptools())
    missing: dict[str, list[str]] = {}

    for module, source in sources.items():
        local_imports = {
            imported
            for imported in _imported_modules(module, source)
            if _is_local_module(imported)
        }
        undeclared = sorted(local_imports - sources.keys())
        if undeclared:
            missing[module] = undeclared

    assert not missing, missing


def test_built_wheel_installs_and_imports_outside_the_source_tree(tmp_path: Path) -> None:
    sources = _distribution_sources(_project_setuptools())
    project_dir = tmp_path / "project"
    wheel_dir = tmp_path / "wheel"
    install_dir = tmp_path / "installed"
    _copy_wheel_project(project_dir, sources)
    stale_build = project_dir / "build" / "lib"
    stale_build.mkdir(parents=True)
    for module in _DEFERRED_MODULES:
        (stale_build / f"{module}.py").write_text(
            "raise RuntimeError('stale module must not ship')\n",
            encoding="utf-8",
        )
    wheel_dir.mkdir()

    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--disable-pip-version-check",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=project_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as archive:
        wheel_files = set(archive.namelist())
        metadata_files = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        assert len(metadata_files) == 1, metadata_files
        metadata = archive.read(metadata_files[0]).decode("utf-8")
        entry_point_files = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/entry_points.txt")
        ]
        assert len(entry_point_files) == 1, entry_point_files
        entry_points = archive.read(entry_point_files[0]).decode("utf-8")
    for module in _DEFERRED_MODULES:
        assert f"{module}.py" not in wheel_files
    assert "<!-- mcp-name: io.github.VBlackJack/cortex -->" in metadata
    assert "cortex = cli:main" in entry_points
    assert "cortex-local-rag = cli:main" in entry_points

    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-compile",
            "--no-deps",
            "--target",
            str(install_dir),
            str(wheels[0]),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    script_directory = install_dir / "bin"
    alias_name = "cortex-local-rag.exe" if sys.platform == "win32" else "cortex-local-rag"
    registry_alias = script_directory / alias_name
    assert registry_alias.is_file(), registry_alias
    alias_environment = os.environ.copy()
    alias_environment["PYTHONPATH"] = str(install_dir)
    alias_smoke = subprocess.run(  # noqa: S603
        [str(registry_alias), "--version"],
        cwd=tmp_path,
        env=alias_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert alias_smoke.returncode == 0, alias_smoke.stdout + alias_smoke.stderr
    assert alias_smoke.stdout.strip() == __version__

    for source in sources.values():
        assert (install_dir / source.relative_to(_ROOT)).is_file(), source

    probe = "\n".join(
        (
            "import importlib",
            "import pathlib",
            "import sys",
            f"site = pathlib.Path({str(install_dir)!r}).resolve()",
            "sys.path.insert(0, str(site))",
            "module = importlib.import_module('cli')",
            "origin = pathlib.Path(module.__file__).resolve()",
            "assert origin.is_relative_to(site), origin",
            "print(origin)",
        )
    )
    imported = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert imported.returncode == 0, imported.stdout + imported.stderr
    assert str(install_dir.resolve()) in imported.stdout
