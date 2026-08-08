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
"""Setuptools hooks that keep wheel assembly isolated from stale build output."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Final, cast

from setuptools import setup
from setuptools.command.bdist_wheel import bdist_wheel

_REPOSITORY_ROOT: Final[Path] = Path(os.path.abspath(Path(__file__).parent))
_BUILD_ROOT: Final[Path] = _REPOSITORY_ROOT / "build"
_FILE_ATTRIBUTE_REPARSE_POINT: Final[int] = 0x400


class UnsafeBuildPathError(RuntimeError):
    """Raised before cleanup when the dedicated build tree is not plain local data."""


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    attributes = cast("int", getattr(metadata, "st_file_attributes", 0))
    return stat.S_ISLNK(metadata.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _validate_plain_build_tree(path: Path) -> bool:
    """Return whether the build tree exists after a no-follow safety walk."""
    expected = Path(os.path.abspath(_BUILD_ROOT))
    candidate = Path(os.path.abspath(path))
    if candidate != expected or candidate.parent != _REPOSITORY_ROOT:
        raise UnsafeBuildPathError(f"Refusing to clean non-dedicated build path: {candidate}")

    try:
        root_metadata = _REPOSITORY_ROOT.lstat()
    except OSError as exc:
        raise UnsafeBuildPathError(
            f"Could not inspect repository root before wheel build: {exc}"
        ) from exc
    if _is_link_or_reparse(root_metadata) or not stat.S_ISDIR(root_metadata.st_mode):
        raise UnsafeBuildPathError(
            f"Repository root is linked or is not a directory: {_REPOSITORY_ROOT}"
        )

    try:
        build_metadata = candidate.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise UnsafeBuildPathError(f"Could not inspect build directory: {exc}") from exc
    if _is_link_or_reparse(build_metadata) or not stat.S_ISDIR(build_metadata.st_mode):
        raise UnsafeBuildPathError(
            f"Build path is linked or is not a directory: {candidate}"
        )

    pending = [candidate]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise UnsafeBuildPathError(
                            f"Could not inspect build entry {entry.path}: {exc}"
                        ) from exc
                    entry_path = Path(entry.path)
                    if _is_link_or_reparse(metadata):
                        raise UnsafeBuildPathError(
                            f"Build tree contains a link or reparse point: {entry_path}"
                        )
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append(entry_path)
                    elif not stat.S_ISREG(metadata.st_mode):
                        raise UnsafeBuildPathError(
                            f"Build tree contains a non-regular entry: {entry_path}"
                        )
        except UnsafeBuildPathError:
            raise
        except OSError as exc:
            raise UnsafeBuildPathError(f"Could not scan build directory {current}: {exc}") from exc
    return True


def _clean_wheel_build_tree() -> None:
    """Remove only the validated setuptools/PyInstaller build root."""
    if not _validate_plain_build_tree(_BUILD_ROOT):
        return
    try:
        shutil.rmtree(_BUILD_ROOT)
    except OSError as exc:
        raise UnsafeBuildPathError(f"Could not clean build directory: {exc}") from exc


class CleanBdistWheel(bdist_wheel):  # type: ignore[misc]
    """Start every wheel assembly from an empty, guarded build tree."""

    def run(self) -> None:
        _clean_wheel_build_tree()
        super().run()


setup(cmdclass={"bdist_wheel": CleanBdistWheel})
