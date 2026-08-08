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
"""Generate and verify licenses for the exact PyInstaller distribution surface."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import sys
import sysconfig
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Final, cast

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_DEFAULT_TOC: Final[Path] = _REPO_ROOT / "build" / "pyinstaller" / "cortex" / "Analysis-00.toc"
_DEFAULT_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "dist" / "licenses"
_VENDORED_ROOT: Final[Path] = Path(__file__).with_name("licenses") / "upstream"
_VENDORED_MANIFEST: Final[Path] = _VENDORED_ROOT / "manifest.json"
_BUNDLE_MANIFEST_NAME: Final[str] = "THIRD_PARTY_LICENSES.json"
_CHECKSUMS_NAME: Final[str] = "SHA256SUMS"
_PROJECT_LICENSE: Final[Path] = _REPO_ROOT / "LICENSE"
_PROJECT_LICENSE_NAME: Final[str] = "Cortex-LICENSE.txt"
_PYTHON_LICENSE_NAME: Final[str] = "PYTHON_LICENSE.txt"
_HEX_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_HEX_COMMIT: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_LICENSE_BASENAME: Final[re.Pattern[str]] = re.compile(
    r"^(?:license|licence|copying|notice|copyright|authors)(?:[._-].*)?$",
    re.IGNORECASE,
)
_PRIMARY_LICENSE_BASENAME: Final[re.Pattern[str]] = re.compile(
    r"^(?:license|licence|copying|notice)(?:[._-].*)?$",
    re.IGNORECASE,
)
_THIRD_PARTY_NOTICE: Final[re.Pattern[str]] = re.compile(
    r"^third(?:[_ -]?party)?[_ -]?notices?(?:[._-].*)?$",
    re.IGNORECASE,
)
_TEXT_LICENSE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {"", ".license", ".md", ".rst", ".txt"}
)


class LicenseBundleError(RuntimeError):
    """Raised when redistribution license coverage cannot be proven."""


@dataclass(frozen=True)
class TocEntry:
    """One destination/source/type tuple from PyInstaller Analysis."""

    destination: str
    source: Path
    kind: str


@dataclass(frozen=True)
class InstalledDistribution:
    """Installed metadata and RECORD surface for one Python distribution."""

    name: str
    normalized_name: str
    version: str
    license_expression: str | None
    license_file_headers: tuple[str, ...]
    distribution: metadata.Distribution
    files: tuple[metadata.PackagePath, ...]
    root: Path


@dataclass(frozen=True)
class LocalLicense:
    """One installed license/notice file and whether it proves coverage."""

    record_path: PurePosixPath
    source: Path
    primary: bool


@dataclass(frozen=True)
class VendoredLicense:
    """Pinned upstream license used only when the exact wheel has no text."""

    distribution: str
    version: str
    file: str
    source_url: str
    git_ref: str
    git_commit: str
    sha256: str
    path: Path


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_distribution_name(name: str) -> str:
    normalized = re.sub(r"[-_.]+", "-", name).lower()
    if not normalized or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) is None:
        raise LicenseBundleError(f"Invalid distribution name in metadata: {name!r}")
    return normalized


def _absolute_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _safe_record_path(value: object, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise LicenseBundleError(f"{label} must be a non-empty relative path.")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise LicenseBundleError(f"{label} escapes its distribution: {value!r}")
    return path


def _walk_toc(value: object) -> Iterator[TocEntry]:
    if not isinstance(value, (list, tuple)):
        return
    if (
        len(value) == 3
        and isinstance(value[0], str)
        and isinstance(value[1], str)
        and isinstance(value[2], str)
    ):
        yield TocEntry(value[0], Path(value[1]), value[2])
    for child in value:
        yield from _walk_toc(child)


def parse_analysis_toc(path: Path) -> tuple[TocEntry, ...]:
    """Return every file-bearing entry from a PyInstaller Analysis TOC."""
    try:
        raw = ast.literal_eval(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        raise LicenseBundleError(
            f"Could not parse PyInstaller Analysis TOC {path}: {exc}"
        ) from exc
    entries = tuple(_walk_toc(raw))
    if not entries:
        raise LicenseBundleError(f"PyInstaller Analysis TOC has no file entries: {path}")
    return entries


def _first_metadata_value(
    distribution: metadata.Distribution,
    key: str,
) -> str | None:
    values = distribution.metadata.get_all(key) or ()
    return values[0] if values else None


def _single_line_license_expression(distribution: metadata.Distribution) -> str | None:
    expression = _first_metadata_value(distribution, "License-Expression")
    if expression:
        return expression.strip()
    legacy = _first_metadata_value(distribution, "License")
    if legacy:
        stripped = legacy.strip()
        if stripped and "\n" not in stripped and "\r" not in stripped and len(stripped) <= 200:
            return stripped
    return None


def installed_distributions(
    candidates: Iterable[metadata.Distribution] | None = None,
) -> tuple[InstalledDistribution, ...]:
    """Snapshot installed distributions with complete RECORD information."""
    source = metadata.distributions() if candidates is None else candidates
    snapshots: list[InstalledDistribution] = []
    identities: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for distribution in source:
        raw_name = _first_metadata_value(distribution, "Name")
        if not raw_name:
            continue
        name = raw_name.strip()
        normalized = _normalized_distribution_name(name)
        version = distribution.version
        if not version:
            raise LicenseBundleError(f"Installed distribution {name!r} has no version.")
        files = tuple(distribution.files or ())
        if not files:
            continue
        headers = tuple(distribution.metadata.get_all("License-File") or ())
        root = Path(str(distribution.locate_file("")))
        identity = (
            normalized,
            version,
            _absolute_key(root),
            tuple(sorted(str(item) for item in files)),
        )
        if identity in identities:
            continue
        identities.add(identity)
        snapshots.append(
            InstalledDistribution(
                name=name,
                normalized_name=normalized,
                version=version,
                license_expression=_single_line_license_expression(distribution),
                license_file_headers=headers,
                distribution=distribution,
                files=files,
                root=root,
            )
        )
    if not snapshots:
        raise LicenseBundleError("No installed distributions with RECORD data were found.")
    return tuple(sorted(snapshots, key=lambda item: item.normalized_name))


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(root)))
    except ValueError:
        return False
    return True


def _is_package_install_root(path: Path) -> bool:
    """Return whether unowned files below this root imply a broken RECORD."""
    return path.name.casefold() in {"site-packages", "dist-packages"}


def _reject_linked_path_chain(candidate: Path, *, root: Path, label: str) -> Path:
    """Return a lexical path after rejecting every existing linked component."""
    lexical_root = Path(os.path.abspath(root))
    lexical_candidate = Path(os.path.abspath(candidate))
    try:
        relative = lexical_candidate.relative_to(lexical_root)
    except ValueError as exc:
        raise LicenseBundleError(
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
            raise LicenseBundleError(
                f"Could not inspect {label} component {component}: {exc}"
            ) from exc
        file_attributes = int(getattr(component_status, "st_file_attributes", 0))
        if stat.S_ISLNK(component_status.st_mode) or file_attributes & 0x400:
            raise LicenseBundleError(
                f"{label} contains a symbolic link or reparse point: {component}"
            )
    return lexical_candidate


def distributions_in_toc(
    entries: Sequence[TocEntry],
    distributions: Sequence[InstalledDistribution],
) -> tuple[InstalledDistribution, ...]:
    """Map every site-packages TOC source to its exact RECORD owner."""
    owners_by_path: dict[str, InstalledDistribution] = {}
    for distribution in distributions:
        for record_path in distribution.files:
            source = Path(str(distribution.distribution.locate_file(record_path)))
            key = _absolute_key(source)
            previous = owners_by_path.get(key)
            if previous is not None and previous.normalized_name != distribution.normalized_name:
                raise LicenseBundleError(
                    f"Installed file has multiple distribution owners: {source}: "
                    f"{previous.name}, {distribution.name}"
                )
            owners_by_path[key] = distribution

    included: dict[str, InstalledDistribution] = {}
    roots = tuple(
        {
            Path(os.path.abspath(item.root))
            for item in distributions
            if _is_package_install_root(item.root)
        }
    )
    for entry in entries:
        owner = owners_by_path.get(_absolute_key(entry.source))
        if owner is not None:
            previous = included.get(owner.normalized_name)
            if previous is not None and previous.version != owner.version:
                raise LicenseBundleError(
                    f"PyInstaller included multiple versions of {owner.normalized_name}: "
                    f"{previous.version}, {owner.version}."
                )
            included[owner.normalized_name] = owner
            continue
        if any(_path_is_within(entry.source, root) for root in roots):
            raise LicenseBundleError(
                "PyInstaller included a site-packages file absent from every installed "
                f"RECORD: {entry.source}"
            )
    if not included:
        raise LicenseBundleError("The PyInstaller TOC contains no owned Python distributions.")
    return tuple(included[name] for name in sorted(included))


def _is_dist_info_license(path: PurePosixPath) -> bool:
    folded = tuple(part.casefold() for part in path.parts)
    return any(
        part.endswith(".dist-info")
        and index + 1 < len(folded)
        and folded[index + 1] == "licenses"
        for index, part in enumerate(folded)
    )


def _is_named_license(path: PurePosixPath) -> bool:
    leaf = path.name
    suffix = PurePosixPath(leaf).suffix.casefold()
    return suffix in _TEXT_LICENSE_SUFFIXES and (
        _LICENSE_BASENAME.fullmatch(leaf) is not None
        or _THIRD_PARTY_NOTICE.fullmatch(leaf) is not None
    )


def _is_primary_license(path: PurePosixPath) -> bool:
    leaf = path.name
    suffix = PurePosixPath(leaf).suffix.casefold()
    return suffix in _TEXT_LICENSE_SUFFIXES and (
        _PRIMARY_LICENSE_BASENAME.fullmatch(leaf) is not None
        or _THIRD_PARTY_NOTICE.fullmatch(leaf) is not None
    )


def distribution_license_files(
    distribution: InstalledDistribution,
) -> tuple[LocalLicense, ...]:
    """Return every declared or conventionally named local license text."""
    records: dict[PurePosixPath, Path] = {}
    primary_records: set[PurePosixPath] = set()
    all_paths: list[tuple[PurePosixPath, Path]] = []
    for package_path in distribution.files:
        raw_record_path = PurePosixPath(str(package_path).replace("\\", "/"))
        if raw_record_path.is_absolute() or ".." in raw_record_path.parts:
            continue
        record_path = _safe_record_path(
            raw_record_path.as_posix(),
            label=f"RECORD path for {distribution.name}",
        )
        source = Path(str(distribution.distribution.locate_file(package_path)))
        all_paths.append((record_path, source))
        if _is_dist_info_license(record_path) or _is_named_license(record_path):
            records[record_path] = source
            if _is_primary_license(record_path):
                primary_records.add(record_path)

    for header in distribution.license_file_headers:
        declared = _safe_record_path(
            header,
            label=f"License-File for {distribution.name}",
        )
        matches = [
            (record_path, source)
            for record_path, source in all_paths
            if record_path == declared
            or (
                len(record_path.parts) >= len(declared.parts) + 1
                and record_path.parts[-len(declared.parts) :] == declared.parts
                and record_path.parts[-len(declared.parts) - 1]
                .casefold()
                .endswith(".dist-info")
            )
            or (
                len(record_path.parts) >= len(declared.parts) + 2
                and record_path.parts[-len(declared.parts) :] == declared.parts
                and record_path.parts[-len(declared.parts) - 1].casefold() == "licenses"
                and record_path.parts[-len(declared.parts) - 2]
                .casefold()
                .endswith(".dist-info")
            )
        ]
        if not matches:
            raise LicenseBundleError(
                f"{distribution.name}=={distribution.version} declares License-File "
                f"{header!r}, but the installed RECORD cannot locate it."
            )
        records.update(matches)
        declared_is_primary = (
            _LICENSE_BASENAME.fullmatch(declared.name) is None
            or _is_primary_license(declared)
        )
        if declared_is_primary:
            primary_records.update(record_path for record_path, _source in matches)

    return tuple(
        LocalLicense(
            record_path=path,
            source=records[path],
            primary=path in primary_records,
        )
        for path in sorted(records, key=str)
    )


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LicenseBundleError(f"{label} must be a JSON object.")
    return cast("Mapping[str, object]", value)


def _require_string(mapping: Mapping[str, object], key: str, *, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise LicenseBundleError(f"{label}.{key} must be a non-empty string.")
    return value


def load_vendored_licenses(
    manifest_path: Path = _VENDORED_MANIFEST,
) -> Mapping[str, VendoredLicense]:
    """Load and hash-verify the offline upstream-license exception set."""
    try:
        raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LicenseBundleError(f"Could not read vendored-license manifest: {exc}") from exc
    root = _require_mapping(raw, label="vendored manifest")
    if set(root) != {"schema_version", "licenses"} or root.get("schema_version") != 1:
        raise LicenseBundleError("Vendored-license manifest schema is not exactly version 1.")
    raw_licenses = root.get("licenses")
    if not isinstance(raw_licenses, list) or not raw_licenses:
        raise LicenseBundleError(
            "Vendored-license manifest must contain a non-empty licenses list."
        )

    result: dict[str, VendoredLicense] = {}
    expected_keys = {
        "distribution",
        "version",
        "file",
        "source_url",
        "git_ref",
        "git_commit",
        "sha256",
    }
    for index, raw_license in enumerate(raw_licenses):
        label = f"vendored manifest licenses[{index}]"
        item = _require_mapping(raw_license, label=label)
        if set(item) != expected_keys:
            raise LicenseBundleError(f"{label} has unexpected or missing fields.")
        distribution = _normalized_distribution_name(
            _require_string(item, "distribution", label=label)
        )
        version = _require_string(item, "version", label=label)
        file = _require_string(item, "file", label=label)
        if Path(file).name != file:
            raise LicenseBundleError(f"{label}.file must be a single filename.")
        source_url = _require_string(item, "source_url", label=label)
        git_ref = _require_string(item, "git_ref", label=label)
        git_commit = _require_string(item, "git_commit", label=label)
        sha256 = _require_string(item, "sha256", label=label).lower()
        if not source_url.startswith("https://raw.githubusercontent.com/"):
            raise LicenseBundleError(f"{label}.source_url is not an official raw GitHub URL.")
        if f"/{git_ref}/" not in source_url:
            raise LicenseBundleError(f"{label}.source_url does not use its exact git_ref.")
        if _HEX_COMMIT.fullmatch(git_commit) is None:
            raise LicenseBundleError(f"{label}.git_commit is not an exact commit SHA.")
        if _HEX_SHA256.fullmatch(sha256) is None:
            raise LicenseBundleError(f"{label}.sha256 is not a SHA-256 value.")
        path = manifest_path.parent / file
        if not path.is_file():
            raise LicenseBundleError(f"Vendored license is missing: {path}")
        actual_hash = _sha256_file(path)
        if actual_hash != sha256:
            raise LicenseBundleError(
                f"Vendored license hash mismatch for {distribution}=={version}: "
                f"expected {sha256}, got {actual_hash}."
            )
        if path.stat().st_size == 0:
            raise LicenseBundleError(f"Vendored license is empty: {path}")
        if distribution in result:
            raise LicenseBundleError(f"Duplicate vendored license for {distribution}.")
        result[distribution] = VendoredLicense(
            distribution=distribution,
            version=version,
            file=file,
            source_url=source_url,
            git_ref=git_ref,
            git_commit=git_commit,
            sha256=sha256,
            path=path,
        )
    return result


def _python_license_path(explicit: Path | None = None) -> Path:
    candidates = [] if explicit is None else [explicit]
    if explicit is None:
        stdlib = Path(sysconfig.get_path("stdlib"))
        data_root = Path(sysconfig.get_path("data"))
        candidates.extend(
            (
                Path(sys.base_prefix) / "LICENSE.txt",
                Path(sys.base_prefix) / "LICENSE",
                Path(sys.prefix) / "LICENSE.txt",
                Path(sys.executable).parent / "LICENSE.txt",
                data_root / "LICENSE.txt",
                stdlib.parent.parent / "LICENSE.txt",
            )
        )
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    displayed = ", ".join(str(path) for path in candidates)
    raise LicenseBundleError(f"CPython runtime license was not found locally: {displayed}")


def _python_runtime_entries(entries: Sequence[TocEntry]) -> tuple[TocEntry, ...]:
    result: list[TocEntry] = []
    for entry in entries:
        destination = Path(entry.destination).name.casefold()
        source_text = entry.source.as_posix().casefold()
        is_library = (
            re.fullmatch(r"python3(?:\d+)?\.dll", destination) is not None
            or re.fullmatch(r"libpython3(?:\.\d+)+(?:\.so(?:\.\d+)*)?", destination)
            is not None
            or re.fullmatch(r"libpython3(?:\.\d+)+\.dylib", destination) is not None
            or (destination == "python" and "/python.framework/" in source_text)
        )
        if is_library and entry.source.is_file():
            result.append(entry)
    if not result:
        raise LicenseBundleError(
            "PyInstaller TOC contains no identifiable CPython runtime library."
        )
    return tuple(sorted(result, key=lambda item: item.destination.casefold()))


def _safe_file_bytes(path: Path, *, label: str) -> bytes:
    try:
        file_status = path.lstat()
    except OSError as exc:
        raise LicenseBundleError(f"Could not inspect {label} {path}: {exc}") from exc
    file_attributes = int(getattr(file_status, "st_file_attributes", 0))
    if stat.S_ISLNK(file_status.st_mode) or file_attributes & 0x400:
        raise LicenseBundleError(f"{label} is a symbolic link or reparse point: {path}")
    if not stat.S_ISREG(file_status.st_mode):
        raise LicenseBundleError(f"{label} is not a regular file: {path}")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise LicenseBundleError(f"Could not read {label} {path}: {exc}") from exc
    if not content:
        raise LicenseBundleError(f"{label} is empty: {path}")
    return content


def _write_licensed_file(
    staging: Path,
    relative_path: PurePosixPath,
    content: bytes,
    occupied: set[str],
) -> Mapping[str, object]:
    folded = relative_path.as_posix().casefold()
    if folded in occupied:
        raise LicenseBundleError(f"Duplicate output license path: {relative_path}")
    occupied.add(folded)
    destination = staging.joinpath(*relative_path.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        "path": relative_path.as_posix(),
        "bytes": len(content),
        "sha256": _sha256_bytes(content),
    }


def _replace_output_directory(
    staging: Path,
    output_dir: Path,
    *,
    safety_root: Path,
) -> None:
    _reject_linked_path_chain(
        output_dir,
        root=safety_root,
        label="License bundle output",
    )
    if output_dir.exists() or output_dir.is_symlink():
        try:
            output_status = output_dir.lstat()
        except OSError as exc:
            raise LicenseBundleError(f"Could not inspect prior license bundle: {exc}") from exc
        file_attributes = int(getattr(output_status, "st_file_attributes", 0))
        if stat.S_ISLNK(output_status.st_mode) or file_attributes & 0x400:
            raise LicenseBundleError(
                f"Refusing to replace a linked license bundle directory: {output_dir}"
            )
        if not stat.S_ISDIR(output_status.st_mode):
            raise LicenseBundleError(f"License bundle output is not a directory: {output_dir}")
        shutil.rmtree(output_dir)
    os.replace(staging, output_dir)


def generate_license_bundle(
    *,
    analysis_toc: Path,
    output_dir: Path,
    distribution_candidates: Iterable[metadata.Distribution] | None = None,
    project_license: Path = _PROJECT_LICENSE,
    python_license: Path | None = None,
    vendored_manifest: Path = _VENDORED_MANIFEST,
    safety_root: Path | None = None,
) -> Path:
    """Generate an offline, hash-verified redistribution-license bundle."""
    frozen_candidates = (
        None if distribution_candidates is None else tuple(distribution_candidates)
    )
    entries = parse_analysis_toc(analysis_toc)
    snapshots = installed_distributions(frozen_candidates)
    included = distributions_in_toc(entries, snapshots)
    vendored = load_vendored_licenses(vendored_manifest)
    runtime_entries = _python_runtime_entries(entries)
    python_license_path = _python_license_path(python_license)

    safety_anchor = output_dir.parent if safety_root is None else safety_root
    _reject_linked_path_chain(
        output_dir,
        root=safety_anchor,
        label="License bundle output",
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".cortex-licenses-", dir=output_dir.parent))
    moved = False
    try:
        occupied: set[str] = set()
        project_content = _safe_file_bytes(project_license, label="Cortex project license")
        project_file = dict(
            _write_licensed_file(
                staging,
                PurePosixPath(_PROJECT_LICENSE_NAME),
                project_content,
                occupied,
            )
        )
        project_file["source"] = "repository LICENSE"
        python_content = _safe_file_bytes(python_license_path, label="CPython license")
        python_file = dict(
            _write_licensed_file(
                staging,
                PurePosixPath(_PYTHON_LICENSE_NAME),
                python_content,
                occupied,
            )
        )
        python_file["source"] = "CPython runtime installation"
        python_file["source_url"] = (
            f"https://docs.python.org/{sys.version_info.major}.{sys.version_info.minor}/license.html"
        )

        distribution_items: list[Mapping[str, object]] = []
        for distribution in included:
            license_items: list[Mapping[str, object]] = []
            local_files = distribution_license_files(distribution)
            has_primary_local_text = any(item.primary for item in local_files)
            for local_file in local_files:
                record_path = local_file.record_path
                source = local_file.source
                content = _safe_file_bytes(
                    source,
                    label=f"license for {distribution.name}=={distribution.version}",
                )
                output_path = PurePosixPath(
                    "python-packages",
                    distribution.normalized_name,
                    *record_path.parts,
                )
                item = dict(_write_licensed_file(staging, output_path, content, occupied))
                item["source_kind"] = "installed-record"
                item["record_path"] = record_path.as_posix()
                license_items.append(item)

            upstream = vendored.get(distribution.normalized_name)
            if upstream is not None:
                if upstream.version != distribution.version:
                    raise LicenseBundleError(
                        f"Vendored license for {distribution.normalized_name} covers "
                        f"{upstream.version}, but PyInstaller embedded {distribution.version}."
                    )
                content = _safe_file_bytes(
                    upstream.path,
                    label=(
                        f"vendored license for {distribution.name}=={distribution.version}"
                    ),
                )
                output_path = PurePosixPath(
                    "python-packages",
                    distribution.normalized_name,
                    "vendored",
                    upstream.file,
                )
                item = dict(_write_licensed_file(staging, output_path, content, occupied))
                item.update(
                    {
                        "source_kind": "vendored-upstream",
                        "source_url": upstream.source_url,
                        "git_ref": upstream.git_ref,
                        "git_commit": upstream.git_commit,
                    }
                )
                license_items.append(item)

            if not has_primary_local_text and upstream is None:
                raise LicenseBundleError(
                    f"No primary local or reviewed vendored license text covers "
                    f"{distribution.name}=={distribution.version}."
                )
            distribution_items.append(
                {
                    "name": distribution.name,
                    "normalized_name": distribution.normalized_name,
                    "version": distribution.version,
                    "license_expression": distribution.license_expression,
                    "license_files": sorted(
                        license_items,
                        key=lambda value: cast("str", value["path"]),
                    ),
                }
            )

        runtime_items = [
            {
                "archive_path": entry.destination.replace("\\", "/"),
                "bytes": entry.source.stat().st_size,
                "sha256": _sha256_file(entry.source),
            }
            for entry in runtime_entries
        ]
        manifest: Mapping[str, object] = {
            "schema_version": 1,
            "project": {
                "name": "Cortex",
                "license_expression": "Apache-2.0",
                "license_file": project_file,
            },
            "python": {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
                "runtime_files": runtime_items,
                "license_file": python_file,
            },
            "distributions": distribution_items,
        }
        manifest_content = (
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        manifest_relative = PurePosixPath(_BUNDLE_MANIFEST_NAME)
        manifest_file = _write_licensed_file(
            staging,
            manifest_relative,
            manifest_content,
            occupied,
        )

        checksum_entries: list[tuple[str, str]] = [
            (cast("str", project_file["sha256"]), cast("str", project_file["path"])),
            (cast("str", python_file["sha256"]), cast("str", python_file["path"])),
            (cast("str", manifest_file["sha256"]), cast("str", manifest_file["path"])),
        ]
        for distribution_item in distribution_items:
            files = cast(
                "Sequence[Mapping[str, object]]",
                distribution_item["license_files"],
            )
            checksum_entries.extend(
                (cast("str", item["sha256"]), cast("str", item["path"])) for item in files
            )
        checksums = "".join(
            f"{digest}  {path}\n" for digest, path in sorted(checksum_entries, key=lambda x: x[1])
        ).encode("ascii")
        _write_licensed_file(
            staging,
            PurePosixPath(_CHECKSUMS_NAME),
            checksums,
            occupied,
        )

        verify_license_bundle(
            staging,
            analysis_toc=analysis_toc,
            distribution_candidates=frozen_candidates,
            project_license=project_license,
            python_license=python_license,
            vendored_manifest=vendored_manifest,
        )
        _replace_output_directory(
            staging,
            output_dir,
            safety_root=safety_anchor,
        )
        moved = True
    finally:
        if not moved and staging.exists():
            shutil.rmtree(staging)
    return output_dir / _BUNDLE_MANIFEST_NAME


def _require_exact_fields(
    mapping: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(mapping) != expected:
        raise LicenseBundleError(
            f"{label} fields are not exact: expected={sorted(expected)}, "
            f"actual={sorted(mapping)}."
        )


def _validate_file_hash_fields(item: Mapping[str, object], *, label: str) -> None:
    path = _require_string(item, "path", label=label)
    _safe_record_path(path, label=f"{label}.path")
    digest = _require_string(item, "sha256", label=label)
    size = item.get("bytes")
    if _HEX_SHA256.fullmatch(digest) is None or not isinstance(size, int) or size <= 0:
        raise LicenseBundleError(f"{label} has an invalid hash or byte count.")


def _manifest_file_entries(
    manifest: Mapping[str, object],
) -> tuple[
    tuple[Mapping[str, object], ...],
    Mapping[str, Mapping[str, object]],
    Mapping[str, Mapping[str, object]],
    Mapping[str, object],
    Mapping[str, object],
]:
    _require_exact_fields(
        manifest,
        {"schema_version", "project", "python", "distributions"},
        label="bundle manifest",
    )
    if manifest.get("schema_version") != 1:
        raise LicenseBundleError("Generated license manifest schema is not version 1.")

    project = _require_mapping(manifest.get("project"), label="bundle manifest project")
    _require_exact_fields(
        project,
        {"name", "license_expression", "license_file"},
        label="bundle manifest project",
    )
    if project.get("name") != "Cortex" or project.get("license_expression") != "Apache-2.0":
        raise LicenseBundleError("Cortex project license identity is not exact.")
    project_license = _require_mapping(
        project.get("license_file"),
        label="bundle manifest project.license_file",
    )
    _require_exact_fields(
        project_license,
        {"path", "bytes", "sha256", "source"},
        label="bundle manifest project.license_file",
    )
    _validate_file_hash_fields(
        project_license,
        label="bundle manifest project.license_file",
    )
    if (
        project_license.get("path") != _PROJECT_LICENSE_NAME
        or project_license.get("source") != "repository LICENSE"
    ):
        raise LicenseBundleError("Cortex project license source is not canonical.")

    python = _require_mapping(manifest.get("python"), label="bundle manifest python")
    _require_exact_fields(
        python,
        {"implementation", "version", "runtime_files", "license_file"},
        label="bundle manifest python",
    )
    _require_string(python, "implementation", label="bundle manifest python")
    _require_string(python, "version", label="bundle manifest python")
    python_license = _require_mapping(
        python.get("license_file"),
        label="bundle manifest python.license_file",
    )
    _require_exact_fields(
        python_license,
        {"path", "bytes", "sha256", "source", "source_url"},
        label="bundle manifest python.license_file",
    )
    _validate_file_hash_fields(
        python_license,
        label="bundle manifest python.license_file",
    )
    if python_license.get("path") != _PYTHON_LICENSE_NAME:
        raise LicenseBundleError("CPython license path in the bundle manifest is not canonical.")
    _require_string(
        python_license,
        "source",
        label="bundle manifest python.license_file",
    )
    python_source_url = _require_string(
        python_license,
        "source_url",
        label="bundle manifest python.license_file",
    )
    if not python_source_url.startswith("https://docs.python.org/"):
        raise LicenseBundleError("CPython license source URL is not official.")

    raw_runtime_files = python.get("runtime_files")
    if not isinstance(raw_runtime_files, list) or not raw_runtime_files:
        raise LicenseBundleError("Bundle manifest runtime_files must be a non-empty list.")
    runtime_files: dict[str, Mapping[str, object]] = {}
    runtime_names: list[str] = []
    for index, raw_runtime in enumerate(raw_runtime_files):
        label = f"bundle manifest runtime_files[{index}]"
        runtime = _require_mapping(raw_runtime, label=label)
        _require_exact_fields(
            runtime,
            {"archive_path", "bytes", "sha256"},
            label=label,
        )
        archive_path = _require_string(runtime, "archive_path", label=label)
        _safe_record_path(archive_path, label=f"{label}.archive_path")
        digest = _require_string(runtime, "sha256", label=label)
        size = runtime.get("bytes")
        if _HEX_SHA256.fullmatch(digest) is None or not isinstance(size, int) or size <= 0:
            raise LicenseBundleError(f"{label} has an invalid hash or byte count.")
        folded = archive_path.casefold()
        if folded in runtime_files:
            raise LicenseBundleError(f"Duplicate CPython runtime entry: {archive_path}")
        runtime_files[folded] = runtime
        runtime_names.append(archive_path)
    if runtime_names != sorted(runtime_names, key=str.casefold):
        raise LicenseBundleError("CPython runtime inventory is not sorted.")

    raw_distributions = manifest.get("distributions")
    if not isinstance(raw_distributions, list) or not raw_distributions:
        raise LicenseBundleError("Bundle manifest distributions must be a non-empty list.")
    files: list[Mapping[str, object]] = [project_license, python_license]
    distributions: dict[str, Mapping[str, object]] = {}
    names: list[str] = []
    for index, raw_distribution in enumerate(raw_distributions):
        label = f"bundle manifest distributions[{index}]"
        distribution = _require_mapping(raw_distribution, label=label)
        _require_exact_fields(
            distribution,
            {
                "name",
                "normalized_name",
                "version",
                "license_expression",
                "license_files",
            },
            label=label,
        )
        display_name = _require_string(distribution, "name", label=label)
        name = _require_string(distribution, "normalized_name", label=label)
        if _normalized_distribution_name(display_name) != name:
            raise LicenseBundleError(f"{label} has an inconsistent normalized name.")
        _require_string(distribution, "version", label=label)
        expression = distribution.get("license_expression")
        if expression is not None and not isinstance(expression, str):
            raise LicenseBundleError(f"{label}.license_expression must be text or null.")
        if name in distributions:
            raise LicenseBundleError(f"Duplicate distribution in bundle manifest: {name}")
        distributions[name] = distribution
        names.append(name)
        raw_files = distribution.get("license_files")
        if not isinstance(raw_files, list) or not raw_files:
            raise LicenseBundleError(f"Bundle manifest distribution {name} has no licenses.")
        file_names: list[str] = []
        for file_index, raw_file in enumerate(raw_files):
            file_label = f"bundle manifest license {name}[{file_index}]"
            license_file = _require_mapping(raw_file, label=file_label)
            source_kind = _require_string(license_file, "source_kind", label=file_label)
            if source_kind == "installed-record":
                expected_fields = {
                    "path",
                    "bytes",
                    "sha256",
                    "source_kind",
                    "record_path",
                }
                _require_exact_fields(license_file, expected_fields, label=file_label)
                _safe_record_path(
                    _require_string(license_file, "record_path", label=file_label),
                    label=f"{file_label}.record_path",
                )
            elif source_kind == "vendored-upstream":
                expected_fields = {
                    "path",
                    "bytes",
                    "sha256",
                    "source_kind",
                    "source_url",
                    "git_ref",
                    "git_commit",
                }
                _require_exact_fields(license_file, expected_fields, label=file_label)
                source_url = _require_string(license_file, "source_url", label=file_label)
                git_ref = _require_string(license_file, "git_ref", label=file_label)
                git_commit = _require_string(license_file, "git_commit", label=file_label)
                if (
                    not source_url.startswith("https://raw.githubusercontent.com/")
                    or f"/{git_ref}/" not in source_url
                    or _HEX_COMMIT.fullmatch(git_commit) is None
                ):
                    raise LicenseBundleError(f"{file_label} provenance is not exact.")
            else:
                raise LicenseBundleError(
                    f"{file_label} has unsupported source_kind {source_kind!r}."
                )
            _validate_file_hash_fields(license_file, label=file_label)
            output_path = _require_string(license_file, "path", label=file_label)
            expected_prefix = f"python-packages/{name}/"
            if not output_path.startswith(expected_prefix):
                raise LicenseBundleError(f"{file_label} is outside {expected_prefix}.")
            file_names.append(output_path)
            files.append(license_file)
        if file_names != sorted(file_names):
            raise LicenseBundleError(f"License file inventory for {name} is not sorted.")
    if names != sorted(names) or len(names) != len(set(names)):
        raise LicenseBundleError("Bundle manifest distribution inventory is not exact and sorted.")
    return tuple(files), distributions, runtime_files, python, project


def _verify_manifest_against_surface(
    distributions: Mapping[str, Mapping[str, object]],
    runtime_files: Mapping[str, Mapping[str, object]],
    python: Mapping[str, object],
    project: Mapping[str, object],
    *,
    analysis_toc: Path,
    distribution_candidates: Iterable[metadata.Distribution] | None,
    project_license: Path,
    python_license: Path | None,
    vendored_manifest: Path,
) -> None:
    entries = parse_analysis_toc(analysis_toc)
    snapshots = installed_distributions(distribution_candidates)
    included = distributions_in_toc(entries, snapshots)
    expected_names = {item.normalized_name for item in included}
    if set(distributions) != expected_names:
        raise LicenseBundleError(
            "License manifest distribution set does not match the PyInstaller TOC: "
            f"expected={sorted(expected_names)}, actual={sorted(distributions)}."
        )
    vendored = load_vendored_licenses(vendored_manifest)
    for installed in included:
        declared = distributions[installed.normalized_name]
        if declared.get("name") != installed.name or declared.get("version") != installed.version:
            raise LicenseBundleError(
                f"License manifest identity mismatch for {installed.normalized_name}."
            )
        declared_files = cast(
            "Sequence[Mapping[str, object]]",
            declared["license_files"],
        )
        local_by_record = {
            cast("str", item["record_path"]): item
            for item in declared_files
            if item["source_kind"] == "installed-record"
        }
        expected_local = distribution_license_files(installed)
        expected_records = {item.record_path.as_posix() for item in expected_local}
        if set(local_by_record) != expected_records:
            raise LicenseBundleError(
                f"License-File/NOTICE set mismatch for {installed.name}=={installed.version}."
            )
        for local_file in expected_local:
            record = local_file.record_path
            source = local_file.source
            content = _safe_file_bytes(
                source,
                label=f"installed license for {installed.name}=={installed.version}",
            )
            declared_file = local_by_record[record.as_posix()]
            if (
                declared_file.get("sha256") != _sha256_bytes(content)
                or declared_file.get("bytes") != len(content)
            ):
                raise LicenseBundleError(
                    f"Installed license source changed for {installed.name}: {record}."
                )

        upstream = vendored.get(installed.normalized_name)
        declared_upstream = [
            item for item in declared_files if item["source_kind"] == "vendored-upstream"
        ]
        expected_upstream_count = 1 if upstream is not None else 0
        if len(declared_upstream) != expected_upstream_count:
            raise LicenseBundleError(
                f"Vendored-license set mismatch for {installed.name}=={installed.version}."
            )
        if upstream is not None:
            if installed.version != upstream.version:
                raise LicenseBundleError(
                    f"Vendored license version mismatch for {installed.normalized_name}."
                )
            item = declared_upstream[0]
            content = _safe_file_bytes(upstream.path, label="vendored upstream license")
            expected_path = (
                f"python-packages/{installed.normalized_name}/vendored/{upstream.file}"
            )
            if (
                item.get("path") != expected_path
                or item.get("sha256") != upstream.sha256
                or item.get("bytes") != len(content)
                or item.get("source_url") != upstream.source_url
                or item.get("git_ref") != upstream.git_ref
                or item.get("git_commit") != upstream.git_commit
            ):
                raise LicenseBundleError(
                    f"Vendored-license provenance mismatch for {installed.normalized_name}."
                )

    current_project_license = _safe_file_bytes(
        project_license,
        label="Cortex project license",
    )
    declared_project_license = cast("Mapping[str, object]", project["license_file"])
    if (
        declared_project_license.get("sha256") != _sha256_bytes(current_project_license)
        or declared_project_license.get("bytes") != len(current_project_license)
    ):
        raise LicenseBundleError("Cortex project license does not match the tagged source.")

    if python.get("implementation") != platform.python_implementation():
        raise LicenseBundleError("Python implementation does not match the current build surface.")
    if python.get("version") != platform.python_version():
        raise LicenseBundleError("Python version does not match the current build surface.")
    current_python_license = _safe_file_bytes(
        _python_license_path(python_license),
        label="CPython license",
    )
    declared_python_license = cast("Mapping[str, object]", python["license_file"])
    if (
        declared_python_license.get("sha256") != _sha256_bytes(current_python_license)
        or declared_python_license.get("bytes") != len(current_python_license)
    ):
        raise LicenseBundleError("CPython license does not match the current runtime.")

    expected_runtime: dict[str, Mapping[str, object]] = {}
    for entry in _python_runtime_entries(entries):
        archive_path = entry.destination.replace("\\", "/")
        expected_runtime[archive_path.casefold()] = {
            "archive_path": archive_path,
            "bytes": entry.source.stat().st_size,
            "sha256": _sha256_file(entry.source),
        }
    if runtime_files != expected_runtime:
        raise LicenseBundleError("CPython runtime inventory does not match the PyInstaller TOC.")


def verify_license_bundle(
    output_dir: Path,
    *,
    analysis_toc: Path | None = None,
    distribution_candidates: Iterable[metadata.Distribution] | None = None,
    project_license: Path = _PROJECT_LICENSE,
    python_license: Path | None = None,
    vendored_manifest: Path = _VENDORED_MANIFEST,
) -> None:
    """Verify bundle bytes; with a TOC, authenticate the exact build surface."""
    lexical_output = Path(os.path.abspath(output_dir))
    output_dir = _reject_linked_path_chain(
        lexical_output,
        root=Path(lexical_output.anchor),
        label="License bundle verification path",
    )
    try:
        root_status = output_dir.lstat()
    except OSError as exc:
        raise LicenseBundleError(f"Could not inspect license bundle root: {exc}") from exc
    root_attributes = int(getattr(root_status, "st_file_attributes", 0))
    if (
        stat.S_ISLNK(root_status.st_mode)
        or root_attributes & 0x400
        or not stat.S_ISDIR(root_status.st_mode)
    ):
        raise LicenseBundleError(
            f"License bundle root is linked or is not a directory: {output_dir}"
        )
    manifest_path = output_dir / _BUNDLE_MANIFEST_NAME
    try:
        raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LicenseBundleError(f"Could not read generated license manifest: {exc}") from exc
    manifest = _require_mapping(raw, label="bundle manifest")
    declared_files, distributions, runtime_files, python, project = _manifest_file_entries(
        manifest
    )
    if analysis_toc is not None:
        _verify_manifest_against_surface(
            distributions,
            runtime_files,
            python,
            project,
            analysis_toc=analysis_toc,
            distribution_candidates=distribution_candidates,
            project_license=project_license,
            python_license=python_license,
            vendored_manifest=vendored_manifest,
        )

    expected_hashes: dict[str, str] = {}
    expected_sizes: dict[str, int] = {}
    for item in declared_files:
        declared_path = _require_string(item, "path", label="bundle manifest file")
        relative = _safe_record_path(declared_path, label="bundle manifest file path")
        digest = _require_string(
            item,
            "sha256",
            label=f"bundle manifest file {declared_path}",
        )
        size = item.get("bytes")
        if _HEX_SHA256.fullmatch(digest) is None or not isinstance(size, int) or size <= 0:
            raise LicenseBundleError(
                f"Invalid hash or byte count for bundle file {declared_path}."
            )
        folded = relative.as_posix().casefold()
        if folded in expected_hashes:
            raise LicenseBundleError(
                f"Duplicate file in bundle manifest: {declared_path}"
            )
        expected_hashes[folded] = digest
        expected_sizes[folded] = size

    manifest_relative = _BUNDLE_MANIFEST_NAME.casefold()
    expected_hashes[manifest_relative] = _sha256_file(manifest_path)
    expected_sizes[manifest_relative] = manifest_path.stat().st_size

    actual: dict[str, Path] = {}
    for actual_path in output_dir.rglob("*"):
        try:
            actual_status = actual_path.lstat()
        except OSError as exc:
            raise LicenseBundleError(
                f"Could not inspect license bundle entry {actual_path}: {exc}"
            ) from exc
        file_attributes = int(getattr(actual_status, "st_file_attributes", 0))
        if stat.S_ISLNK(actual_status.st_mode) or file_attributes & 0x400:
            raise LicenseBundleError(
                "License bundle contains a symbolic link or reparse point: "
                f"{actual_path}"
            )
        if stat.S_ISDIR(actual_status.st_mode):
            continue
        if not stat.S_ISREG(actual_status.st_mode):
            raise LicenseBundleError(
                f"License bundle contains a non-regular entry: {actual_path}"
            )
        actual_relative = actual_path.relative_to(output_dir).as_posix()
        folded = actual_relative.casefold()
        if folded == _CHECKSUMS_NAME.casefold():
            continue
        if folded in actual:
            raise LicenseBundleError(
                f"Case-colliding files in license bundle: {actual_relative}"
            )
        actual[folded] = actual_path
    if set(actual) != set(expected_hashes):
        missing = sorted(set(expected_hashes) - set(actual))
        extra = sorted(set(actual) - set(expected_hashes))
        raise LicenseBundleError(
            f"License bundle file set mismatch; missing={missing}, extra={extra}."
        )
    for folded, actual_path in actual.items():
        content = _safe_file_bytes(actual_path, label="generated license bundle file")
        digest = _sha256_bytes(content)
        if digest != expected_hashes[folded] or len(content) != expected_sizes[folded]:
            raise LicenseBundleError(
                f"License bundle hash or size mismatch: {actual_path}"
            )

    checksum_path = output_dir / _CHECKSUMS_NAME
    expected_checksums = "".join(
        f"{expected_hashes[key]}  {actual[key].relative_to(output_dir).as_posix()}\n"
        for key in sorted(actual, key=lambda item: actual[item].relative_to(output_dir).as_posix())
    ).encode("ascii")
    checksum_content = _safe_file_bytes(checksum_path, label="license bundle checksums")
    if checksum_content != expected_checksums:
        raise LicenseBundleError(
            "License bundle SHA256SUMS is not the exact manifest-derived set."
        )


def _validate_cli_path(candidate: Path, *, expected: Path, label: str) -> Path:
    lexical = Path(os.path.abspath(candidate))
    expected_lexical = Path(os.path.abspath(expected))
    if lexical != expected_lexical:
        raise LicenseBundleError(
            f"{label} must be the canonical path {expected_lexical}: {lexical}"
        )
    return _reject_linked_path_chain(
        lexical,
        root=_REPO_ROOT,
        label=label,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-toc", type=Path, default=_DEFAULT_TOC)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--python-license",
        type=Path,
        help="Explicit CPython runtime license when the runtime omits a local copy.",
    )
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate or verify the canonical bundle without network resolution."""
    arguments = _build_parser().parse_args(argv)
    try:
        analysis_toc = _validate_cli_path(
            arguments.analysis_toc,
            expected=_DEFAULT_TOC,
            label="PyInstaller Analysis TOC",
        )
        if arguments.verify_only:
            output_dir = Path(os.path.abspath(arguments.output_dir))
            verify_license_bundle(
                output_dir,
                analysis_toc=analysis_toc,
                python_license=arguments.python_license,
            )
            print(f"[licenses] Verified redistribution license bundle: {output_dir}")
            return 0
        output_dir = _validate_cli_path(
            arguments.output_dir,
            expected=_DEFAULT_OUTPUT_DIR,
            label="License bundle output",
        )
        manifest = generate_license_bundle(
            analysis_toc=analysis_toc,
            output_dir=output_dir,
            python_license=arguments.python_license,
            safety_root=_REPO_ROOT,
        )
        verify_license_bundle(
            output_dir,
            analysis_toc=analysis_toc,
            python_license=arguments.python_license,
        )
        raw = cast(
            "Mapping[str, object]",
            json.loads(manifest.read_text(encoding="utf-8")),
        )
        distributions = cast("Sequence[object]", raw["distributions"])
        print(
            f"[licenses] Covered {len(distributions)} embedded distributions: {manifest}"
        )
        return 0
    except (LicenseBundleError, OSError) as exc:
        print(f"[licenses] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
