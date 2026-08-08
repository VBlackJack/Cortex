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
"""Tests for portable archives that keep executable and licenses together."""

from __future__ import annotations

import hashlib
import runpy
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGING = _ROOT / "packaging"
sys.path.insert(0, str(_PACKAGING))
try:
    _GLOBALS = runpy.run_path(
        str(_PACKAGING / "archive_portable.py"),
        run_name="portable_archive_test",
    )
finally:
    sys.path.remove(str(_PACKAGING))
_ERROR = cast("type[RuntimeError]", _GLOBALS["PortableArchiveError"])
_RUNTIME_GLOBALS = cast(
    "dict[str, object]",
    cast("Any", _GLOBALS["create_portable_archive"]).__globals__,
)


def _license_tree(tmp_path: Path) -> Path:
    root = tmp_path / "licenses"
    (root / "python-packages" / "demo").mkdir(parents=True)
    (root / "Cortex-LICENSE.txt").write_text("Cortex terms\n", encoding="utf-8")
    (root / "PYTHON_LICENSE.txt").write_text("CPython terms\n", encoding="utf-8")
    (root / "THIRD_PARTY_LICENSES.json").write_text("{}\n", encoding="utf-8")
    (root / "SHA256SUMS").write_text("checksums\n", encoding="utf-8")
    (root / "python-packages" / "demo" / "LICENSE.txt").write_text(
        "Demo terms\n",
        encoding="utf-8",
    )
    return root


def test_portable_archive_has_exact_layout_permissions_and_stable_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        _RUNTIME_GLOBALS,
        "verify_license_bundle",
        lambda *_args, **_kwargs: None,
    )
    binary = tmp_path / "cortex"
    binary.write_bytes(b"executable")
    licenses = _license_tree(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    create = _GLOBALS["create_portable_archive"]

    create(binary=binary, binary_name="cortex", license_dir=licenses, output=first)
    create(binary=binary, binary_name="cortex", license_dir=licenses, output=second)

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == [
            "cortex",
            "licenses/Cortex-LICENSE.txt",
            "licenses/PYTHON_LICENSE.txt",
            "licenses/SHA256SUMS",
            "licenses/THIRD_PARTY_LICENSES.json",
            "licenses/python-packages/demo/LICENSE.txt",
        ]
        assert stat.S_IMODE(archive.getinfo("cortex").external_attr >> 16) == 0o755
        for name in archive.namelist()[1:]:
            assert stat.S_IMODE(archive.getinfo(name).external_attr >> 16) == 0o644
        assert archive.testzip() is None


def test_portable_archive_verifies_the_explicit_python_license(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[Path | None] = []

    def verify(*_args: object, **kwargs: object) -> None:
        received.append(cast("Path | None", kwargs.get("python_license")))

    monkeypatch.setitem(_RUNTIME_GLOBALS, "verify_license_bundle", verify)
    binary = tmp_path / "cortex"
    binary.write_bytes(b"executable")
    python_license = tmp_path / "CPython-LICENSE.txt"
    python_license.write_text("CPython terms\n", encoding="utf-8")

    _GLOBALS["create_portable_archive"](
        binary=binary,
        binary_name="cortex",
        license_dir=_license_tree(tmp_path),
        output=tmp_path / "portable.zip",
        python_license=python_license,
    )

    assert received == [python_license]


@pytest.mark.parametrize("binary_name", ["Cortex.exe", "../cortex", "cortex.bin"])
def test_portable_archive_rejects_noncanonical_binary_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binary_name: str,
) -> None:
    monkeypatch.setitem(
        _RUNTIME_GLOBALS,
        "verify_license_bundle",
        lambda *_args, **_kwargs: None,
    )
    binary = tmp_path / "cortex"
    binary.write_bytes(b"executable")

    with pytest.raises(_ERROR, match="Invalid portable executable name"):
        _GLOBALS["create_portable_archive"](
            binary=binary,
            binary_name=binary_name,
            license_dir=_license_tree(tmp_path),
            output=tmp_path / "portable.zip",
        )


def test_archive_inventory_rejects_a_linked_license_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        _RUNTIME_GLOBALS,
        "verify_license_bundle",
        lambda *_args, **_kwargs: None,
    )
    licenses = _license_tree(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    linked = licenses / "linked-directory"

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
            _GLOBALS["_license_files"](licenses)
    finally:
        if linked.exists():
            if sys.platform == "win32":
                linked.rmdir()
            else:
                linked.unlink()


def test_cli_output_rejects_a_junction_in_the_output_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    output_root = repository / "out"
    output = output_root / "cortex-windows-x64.zip"

    try:
        if sys.platform == "win32":
            completed = subprocess.run(  # noqa: S603
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(output_root),
                    str(external),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                pytest.skip(f"Could not create a Windows junction: {completed.stderr}")
        else:
            output_root.symlink_to(external, target_is_directory=True)

        monkeypatch.setitem(_RUNTIME_GLOBALS, "_REPO_ROOT", repository)
        monkeypatch.setitem(_RUNTIME_GLOBALS, "_OUTPUT_ROOT", output_root)
        with pytest.raises(_ERROR, match="symbolic link or reparse point"):
            _GLOBALS["_validate_cli_output"](output)
    finally:
        if output_root.exists():
            if sys.platform == "win32":
                output_root.rmdir()
            else:
                output_root.unlink()
