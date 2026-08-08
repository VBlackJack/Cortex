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
"""Create one self-contained portable archive with its verified licenses."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Final

from license_bundle import LicenseBundleError, verify_license_bundle

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_DEFAULT_LICENSES: Final[Path] = _REPO_ROOT / "dist" / "licenses"
_ANALYSIS_TOC: Final[Path] = _REPO_ROOT / "build" / "pyinstaller" / "cortex" / "Analysis-00.toc"
_OUTPUT_ROOT: Final[Path] = _REPO_ROOT / "out"
_ZIP_TIMESTAMP: Final[tuple[int, int, int, int, int, int]] = (1980, 1, 1, 0, 0, 0)


class PortableArchiveError(RuntimeError):
    """Raised when a portable release archive is incomplete or unsafe."""


def _reject_linked_path_chain(candidate: Path, *, root: Path, label: str) -> Path:
    lexical_root = Path(os.path.abspath(root))
    lexical_candidate = Path(os.path.abspath(candidate))
    try:
        relative = lexical_candidate.relative_to(lexical_root)
    except ValueError as exc:
        raise PortableArchiveError(
            f"{label} must remain under {lexical_root}: {lexical_candidate}"
        ) from exc
    current = lexical_root
    components = [current]
    for part in relative.parts:
        current /= part
        components.append(current)
    for component in components:
        try:
            component_status = component.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PortableArchiveError(
                f"Could not inspect {label} component {component}: {exc}"
            ) from exc
        file_attributes = int(getattr(component_status, "st_file_attributes", 0))
        if stat.S_ISLNK(component_status.st_mode) or file_attributes & 0x400:
            raise PortableArchiveError(
                f"{label} contains a symbolic link or reparse point: {component}"
            )
    return lexical_candidate


def _regular_file(path: Path, *, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PortableArchiveError(f"Could not inspect {label} {path}: {exc}") from exc
    file_attributes = int(getattr(metadata, "st_file_attributes", 0))
    if stat.S_ISLNK(metadata.st_mode) or file_attributes & 0x400:
        raise PortableArchiveError(f"{label} is a symbolic link or reparse point: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise PortableArchiveError(f"{label} is not a regular file: {path}")
    return path


def _license_files(
    license_dir: Path,
    *,
    python_license: Path | None = None,
) -> tuple[Path, ...]:
    try:
        verify_license_bundle(
            license_dir,
            analysis_toc=_ANALYSIS_TOC,
            python_license=python_license,
        )
    except LicenseBundleError as exc:
        raise PortableArchiveError(f"License bundle verification failed: {exc}") from exc
    files: list[Path] = []
    for path in license_dir.rglob("*"):
        try:
            path_status = path.lstat()
        except OSError as exc:
            raise PortableArchiveError(
                f"Could not inspect license bundle entry {path}: {exc}"
            ) from exc
        file_attributes = int(getattr(path_status, "st_file_attributes", 0))
        if stat.S_ISLNK(path_status.st_mode) or file_attributes & 0x400:
            raise PortableArchiveError(
                f"License bundle contains a symbolic link or reparse point: {path}"
            )
        if stat.S_ISDIR(path_status.st_mode):
            continue
        files.append(_regular_file(path, label="license bundle file"))
    if not files:
        raise PortableArchiveError(f"License bundle is empty: {license_dir}")
    return tuple(sorted(files, key=lambda path: path.relative_to(license_dir).as_posix()))


def _zip_info(name: PurePosixPath, *, executable: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name.as_posix(), date_time=_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info


def _write_zip_file(
    archive: zipfile.ZipFile,
    source: Path,
    destination: PurePosixPath,
    *,
    executable: bool,
) -> None:
    with source.open("rb") as input_stream, archive.open(
        _zip_info(destination, executable=executable),
        "w",
    ) as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)


def create_portable_archive(
    *,
    binary: Path,
    binary_name: str,
    license_dir: Path,
    output: Path,
    python_license: Path | None = None,
) -> Path:
    """Create and re-open a portable ZIP with an exact file inventory."""
    source_binary = _regular_file(binary, label="portable executable")
    archive_binary = PurePosixPath(binary_name)
    if (
        archive_binary.is_absolute()
        or len(archive_binary.parts) != 1
        or archive_binary.name not in {"cortex", "cortex.exe"}
    ):
        raise PortableArchiveError(f"Invalid portable executable name: {binary_name!r}")
    license_files = _license_files(
        license_dir,
        python_license=python_license,
    )
    expected_names = [archive_binary.as_posix()]
    expected_names.extend(
        f"licenses/{path.relative_to(license_dir).as_posix()}" for path in license_files
    )

    output = _reject_linked_path_chain(
        output,
        root=output.parent,
        label="Portable archive output",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            _write_zip_file(
                archive,
                source_binary,
                archive_binary,
                executable=True,
            )
            for license_file in license_files:
                relative = PurePosixPath(
                    "licenses",
                    *license_file.relative_to(license_dir).parts,
                )
                _write_zip_file(
                    archive,
                    license_file,
                    relative,
                    executable=False,
                )
        with zipfile.ZipFile(temporary, mode="r") as archive:
            if archive.namelist() != expected_names:
                raise PortableArchiveError("Portable archive file inventory is not exact.")
            corrupt = archive.testzip()
            if corrupt is not None:
                raise PortableArchiveError(f"Portable archive CRC failed for {corrupt}.")
        if output.exists() or output.is_symlink():
            _regular_file(output, label="prior portable archive").unlink()
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _validate_cli_output(path: Path) -> Path:
    lexical = Path(os.path.abspath(path))
    expected_root = Path(os.path.abspath(_OUTPUT_ROOT))
    if lexical.parent != expected_root or lexical.suffix.casefold() != ".zip":
        raise PortableArchiveError(
            f"Portable archive must be one ZIP directly under {expected_root}: {lexical}"
        )
    return _reject_linked_path_chain(
        lexical,
        root=_REPO_ROOT,
        label="Portable archive output",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--binary-name", choices=("cortex", "cortex.exe"), required=True)
    parser.add_argument("--licenses", type=Path, default=_DEFAULT_LICENSES)
    parser.add_argument(
        "--python-license",
        type=Path,
        help="Explicit CPython runtime license used to verify the license bundle.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Create the canonical self-contained portable archive."""
    arguments = _build_parser().parse_args(argv)
    try:
        output = _validate_cli_output(arguments.output)
        result = create_portable_archive(
            binary=arguments.binary,
            binary_name=arguments.binary_name,
            license_dir=arguments.licenses,
            output=output,
            python_license=arguments.python_license,
        )
        print(f"[portable] Built archive with verified licenses: {result}")
        return 0
    except (LicenseBundleError, PortableArchiveError, OSError, zipfile.BadZipFile) as exc:
        print(f"[portable] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
