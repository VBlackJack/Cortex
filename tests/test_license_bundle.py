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
"""Mutation and inventory tests for the PyInstaller redistribution licenses."""

from __future__ import annotations

import hashlib
import json
import runpy
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "packaging" / "license_bundle.py"
_UPSTREAM_ROOT = _ROOT / "packaging" / "licenses" / "upstream"
_GLOBALS = runpy.run_path(str(_SCRIPT), run_name="license_bundle_test")
_ERROR = cast("type[RuntimeError]", _GLOBALS["LicenseBundleError"])


@dataclass(frozen=True)
class _Surface:
    toc: Path
    output: Path
    candidates: tuple[metadata.Distribution, ...]
    project_license: Path
    python_license: Path


def _make_surface(
    tmp_path: Path,
    *,
    license_header: str | None,
) -> _Surface:
    site = tmp_path / "site-packages"
    site.mkdir()
    module = site / "demo_package.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    dist_info = site / "demo_package-1.0.dist-info"
    dist_info.mkdir()

    metadata_lines = [
        "Metadata-Version: 2.4",
        "Name: demo-package",
        "Version: 1.0",
        "License-Expression: MIT",
    ]
    record_paths = [
        "demo_package.py",
        "demo_package-1.0.dist-info/METADATA",
        "demo_package-1.0.dist-info/RECORD",
    ]
    if license_header is not None:
        metadata_lines.append(f"License-File: {license_header}")
        license_path = dist_info / "licenses" / Path(*license_header.split("/"))
        license_path.parent.mkdir(parents=True)
        license_path.write_text("Redistribution license terms.\n", encoding="utf-8")
        record_paths.append(license_path.relative_to(site).as_posix())

    (dist_info / "METADATA").write_text(
        "\n".join(metadata_lines) + "\n",
        encoding="utf-8",
    )
    (dist_info / "RECORD").write_text(
        "".join(f"{path},,\n" for path in record_paths),
        encoding="utf-8",
    )

    runtime = tmp_path / "python312.dll"
    runtime.write_bytes(b"runtime-bytes")
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(
        repr(
            [
                ("demo_package.py", str(module), "PYMODULE"),
                ("python312.dll", str(runtime), "BINARY"),
            ]
        ),
        encoding="utf-8",
    )
    python_license = tmp_path / "PYTHON-LICENSE.txt"
    python_license.write_text("CPython license terms.\n", encoding="utf-8")
    project_license = tmp_path / "CORTEX-LICENSE.txt"
    project_license.write_text("Apache License, Version 2.0.\n", encoding="utf-8")
    candidates = tuple(metadata.distributions(path=[str(site)]))
    assert len(candidates) == 1
    return _Surface(
        toc=toc,
        output=tmp_path / "licenses",
        candidates=candidates,
        project_license=project_license,
        python_license=python_license,
    )


def _generate(surface: _Surface) -> Path:
    generate = _GLOBALS["generate_license_bundle"]
    return cast(
        "Path",
        generate(
            analysis_toc=surface.toc,
            output_dir=surface.output,
            distribution_candidates=surface.candidates,
            project_license=surface.project_license,
            python_license=surface.python_license,
            safety_root=surface.output.parent,
        ),
    )


def _verify(surface: _Surface) -> None:
    verify = _GLOBALS["verify_license_bundle"]
    verify(
        surface.output,
        analysis_toc=surface.toc,
        distribution_candidates=surface.candidates,
        project_license=surface.project_license,
        python_license=surface.python_license,
    )


def test_vendored_exceptions_are_exact_reviewed_upstream_versions() -> None:
    manifest = json.loads((_UPSTREAM_ROOT / "manifest.json").read_text(encoding="utf-8"))
    actual = {
        item["distribution"]: {
            "version": item["version"],
            "git_ref": item["git_ref"],
            "git_commit": item["git_commit"],
            "sha256": item["sha256"],
        }
        for item in manifest["licenses"]
    }

    assert actual == {
        "flatbuffers": {
            "version": "25.12.19",
            "git_ref": "v25.12.19",
            "git_commit": "7e163021e59cca4f8e1e35a7c828b5c6b7915953",
            "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        },
        "loguru": {
            "version": "0.7.3",
            "git_ref": "0.7.3",
            "git_commit": "ae3bfd1b85b6b4a3db535f69b975687c79498be4",
            "sha256": "b35d026cc7aca9d5859a02eb87ddf7a386a24c986838651bd1f283f94e003327",
        },
        "tokenizers": {
            "version": "0.23.1",
            "git_ref": "v0.23.1",
            "git_commit": "7f1623b90b5adfb9bc327d4c3468d2f70bbce262",
            "sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        },
    }


def test_vendored_exception_hash_mutation_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "upstream"
    shutil.copytree(_UPSTREAM_ROOT, copied)
    license_path = copied / "flatbuffers-25.12.19.LICENSE"
    license_path.write_bytes(license_path.read_bytes() + b"mutation")

    with pytest.raises(_ERROR, match="Vendored license hash mismatch"):
        _GLOBALS["load_vendored_licenses"](copied / "manifest.json")


def test_editable_project_root_does_not_classify_unowned_repo_files_as_site_packages(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    owned = repository / "demo_project.py"
    owned.write_text("VALUE = 1\n", encoding="utf-8")
    launcher = repository / "packaging" / "launcher.py"
    launcher.parent.mkdir()
    launcher.write_text("raise SystemExit(0)\n", encoding="utf-8")
    egg_info = repository / "demo_project.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text(
        "Metadata-Version: 2.4\nName: demo-project\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (egg_info / "SOURCES.txt").write_text(
        "demo_project.py\ndemo_project.egg-info/PKG-INFO\n"
        "demo_project.egg-info/SOURCES.txt\n",
        encoding="utf-8",
    )
    candidates = tuple(metadata.distributions(path=[str(repository)]))
    assert len(candidates) == 1
    snapshots = _GLOBALS["installed_distributions"](candidates)
    toc_entry = _GLOBALS["TocEntry"]

    included = _GLOBALS["distributions_in_toc"](
        (
            toc_entry("demo_project.py", owned, "PYMODULE"),
            toc_entry("packaging/launcher.py", launcher, "PYSOURCE"),
        ),
        snapshots,
    )

    assert [(item.normalized_name, item.version) for item in included] == [
        ("demo-project", "1.0")
    ]


def test_explicit_nested_license_file_covers_and_verifies_exact_surface(
    tmp_path: Path,
) -> None:
    surface = _make_surface(tmp_path, license_header="LICENSES/Apache-2.0.txt")

    manifest_path = _generate(surface)
    _verify(surface)
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    project_license_content = surface.project_license.read_bytes()

    assert [item["normalized_name"] for item in manifest["distributions"]] == [
        "demo-package"
    ]
    assert manifest["project"] == {
        "name": "Cortex",
        "license_expression": "Apache-2.0",
        "license_file": {
            "path": "Cortex-LICENSE.txt",
            "bytes": len(project_license_content),
            "sha256": hashlib.sha256(project_license_content).hexdigest(),
            "source": "repository LICENSE",
        },
    }
    distribution = manifest["distributions"][0]
    assert [item["record_path"] for item in distribution["license_files"]] == [
        "demo_package-1.0.dist-info/licenses/LICENSES/Apache-2.0.txt"
    ]
    assert manifest["python"]["runtime_files"] == [
        {
            "archive_path": "python312.dll",
            "bytes": len(b"runtime-bytes"),
            "sha256": "99235f1c93582c5d7f669de64945af872b90a47e628250eda09a318dcbffeec7",
        }
    ]


@pytest.mark.parametrize("license_header", [None, "AUTHORS", "COPYRIGHT"])
def test_missing_or_supplementary_only_license_is_fail_closed(
    tmp_path: Path,
    license_header: str | None,
) -> None:
    surface = _make_surface(tmp_path, license_header=license_header)

    with pytest.raises(_ERROR, match="No primary local or reviewed vendored license"):
        _generate(surface)


def test_generated_license_byte_mutation_is_rejected(tmp_path: Path) -> None:
    surface = _make_surface(tmp_path, license_header="LICENSE")
    manifest_path = _generate(surface)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    copied_path = surface.output / manifest["distributions"][0]["license_files"][0]["path"]
    copied_path.write_bytes(copied_path.read_bytes() + b"mutation")

    with pytest.raises(_ERROR, match="hash or size mismatch"):
        _verify(surface)


def test_project_license_source_mutation_is_rejected(tmp_path: Path) -> None:
    surface = _make_surface(tmp_path, license_header="LICENSE")
    _generate(surface)
    surface.project_license.write_text("mutated terms\n", encoding="utf-8")

    with pytest.raises(_ERROR, match="project license does not match"):
        _verify(surface)


def test_manifest_schema_and_runtime_surface_mutations_are_rejected(
    tmp_path: Path,
) -> None:
    surface = _make_surface(tmp_path, license_header="LICENSE")
    manifest_path = _generate(surface)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unexpected"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(_ERROR, match="fields are not exact"):
        _verify(surface)

    shutil.rmtree(surface.output)
    manifest_path = _generate(surface)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["python"]["runtime_files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(_ERROR, match="runtime inventory does not match"):
        _verify(surface)


def test_linked_directory_inside_bundle_is_rejected(tmp_path: Path) -> None:
    surface = _make_surface(tmp_path, license_header="LICENSE")
    _generate(surface)
    external = tmp_path / "external"
    external.mkdir()
    linked = surface.output / "linked-directory"

    try:
        if sys.platform == "win32":
            completed = subprocess.run(  # noqa: S603
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(external)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.skip(f"Could not create a Windows junction: {completed.stderr}")
        else:
            linked.symlink_to(external, target_is_directory=True)

        with pytest.raises(_ERROR, match="symbolic link or reparse point"):
            _verify(surface)
    finally:
        if linked.exists():
            if sys.platform == "win32":
                linked.rmdir()
            else:
                linked.unlink()


def test_generation_rejects_a_linked_output_parent(tmp_path: Path) -> None:
    surface = _make_surface(tmp_path, license_header="LICENSE")
    repository = tmp_path / "repository"
    repository.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    linked_parent = repository / "dist"
    output = linked_parent / "licenses"

    try:
        if sys.platform == "win32":
            completed = subprocess.run(  # noqa: S603
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(linked_parent),
                    str(external),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.skip(f"Could not create a Windows junction: {completed.stderr}")
        else:
            linked_parent.symlink_to(external, target_is_directory=True)

        with pytest.raises(_ERROR, match="symbolic link or reparse point"):
            _GLOBALS["generate_license_bundle"](
                analysis_toc=surface.toc,
                output_dir=output,
                distribution_candidates=surface.candidates,
                project_license=surface.project_license,
                python_license=surface.python_license,
                safety_root=repository,
            )
        assert not output.exists()
    finally:
        if linked_parent.exists():
            if sys.platform == "win32":
                linked_parent.rmdir()
            else:
                linked_parent.unlink()


def test_verification_rejects_a_junction_in_its_parent_chain(tmp_path: Path) -> None:
    surface = _make_surface(tmp_path, license_header="LICENSE")
    _generate(surface)
    repository = tmp_path / "repository"
    repository.mkdir()
    linked_parent = repository / "dist"
    linked_output = linked_parent / surface.output.name

    try:
        if sys.platform == "win32":
            completed = subprocess.run(  # noqa: S603
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(linked_parent),
                    str(tmp_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.skip(f"Could not create a Windows junction: {completed.stderr}")
        else:
            linked_parent.symlink_to(tmp_path, target_is_directory=True)

        with pytest.raises(_ERROR, match="symbolic link or reparse point"):
            _GLOBALS["verify_license_bundle"](
                linked_output,
                analysis_toc=surface.toc,
                distribution_candidates=surface.candidates,
                project_license=surface.project_license,
                python_license=surface.python_license,
            )
    finally:
        if linked_parent.exists():
            if sys.platform == "win32":
                linked_parent.rmdir()
            else:
                linked_parent.unlink()
