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
"""Resolve where a section lives on disk without loading the user configuration.

A section is normally the folder of the same name under ``kb_path``. The
``[section_roots]`` table mounts a section on another absolute directory. Only
the filesystem location moves: the logical path stored in chunk metadata and
used in chunk ids stays ``<section>/<path inside the section root>``, exactly as
if the section still lived under ``kb_path``, so an index built before a move
remains valid after the mount.

Every caller that walks files, computes a logical path, or turns a logical path
back into a file goes through this module, so the two directions cannot drift.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_LOGICAL_SEPARATOR = "/"


@dataclass(frozen=True)
class SectionLocation:
    """Where one section's files live and how they map to logical paths.

    ``directory`` holds the files. Logical paths are computed relative to
    ``base`` and prefixed with ``prefix`` when one is set: an unmounted section
    keeps ``base = kb_path`` and no prefix, which is the historical behaviour;
    a mounted section uses its mount as ``base`` and its name as the prefix.
    """

    section: str
    directory: Path
    base: Path
    prefix: str | None
    mounted: bool

    def logical_path(self, path: Path) -> str:
        """Return the POSIX logical path of a file found under ``directory``."""
        relative = path.relative_to(self.base).as_posix()
        if self.prefix is None:
            return relative
        return f"{self.prefix}{_LOGICAL_SEPARATOR}{relative}"


def locate_section(
    kb_root: Path,
    section: str,
    section_roots: Mapping[str, str],
) -> SectionLocation:
    """Return the location of ``section``: its mount when it has one, else under kb_root."""
    mount = section_roots.get(section)
    if mount is not None:
        directory = Path(mount)
        return SectionLocation(
            section=section,
            directory=directory,
            base=directory,
            prefix=section,
            mounted=True,
        )
    return SectionLocation(
        section=section,
        directory=kb_root / section,
        base=kb_root,
        prefix=None,
        mounted=False,
    )


def section_root(kb_root: Path, section: str, section_roots: Mapping[str, str]) -> Path:
    """Return the directory that holds ``section``'s files."""
    return locate_section(kb_root, section, section_roots).directory


def resolve_logical_path(
    kb_root: Path,
    logical_path: str,
    section_roots: Mapping[str, str],
) -> tuple[Path, Path]:
    """Turn a logical path back into a file and the root it must stay inside.

    Returns ``(file, containment_root)``. A path whose first segment names a
    mounted section resolves inside that mount; any other path resolves under
    ``kb_root``, as it always did.
    """
    parts = PurePosixPath(logical_path.replace("\\", _LOGICAL_SEPARATOR)).parts
    if len(parts) > 1 and parts[0] in section_roots:
        mount = Path(section_roots[parts[0]])
        return mount.joinpath(*parts[1:]), mount
    return kb_root / logical_path, kb_root


def logical_source_path(
    file_path: Path,
    kb_root: Path,
    section_roots: Mapping[str, str],
) -> str | None:
    """Return the logical path of an absolute source file, or None when it has none.

    A mount is matched before ``kb_root``, the deepest mount first, so a section
    mounted inside the knowledge base still gets its section name as prefix.
    """
    for section, mount in sorted(
        section_roots.items(), key=lambda item: len(Path(item[1]).parts), reverse=True
    ):
        try:
            relative = file_path.relative_to(mount)
        except ValueError:
            continue
        return f"{section}{_LOGICAL_SEPARATOR}{relative.as_posix()}"
    try:
        return file_path.relative_to(kb_root).as_posix()
    except ValueError:
        return None


__all__ = [
    "SectionLocation",
    "locate_section",
    "logical_source_path",
    "resolve_logical_path",
    "section_root",
]
