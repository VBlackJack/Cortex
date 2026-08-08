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
"""Compute and apply the next Calendar Version (YYYY.MMDD.XX) for Cortex.

CalVer removes the need to *choose* a version number: the UTC date is the
version, and a two-digit counter disambiguates multiple builds on the same day.
The next version is derived from the current one in ``_version.py`` at the
repository root, so cutting a release never requires a human to pick a number.

Usage:
    python scripts/bump_version.py            # write the next version to _version.py
    python scripts/bump_version.py --dry-run  # just print the next version
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from re import Pattern
from re import compile as re_compile

_VERSION_PATH: Path = Path(__file__).resolve().parent.parent / "_version.py"
_SERVER_JSON_PATH: Path = Path(__file__).resolve().parent.parent / "server.json"
_VERSION_RE: Pattern[str] = re_compile(
    r'(?P<prefix>__version__\s*=\s*")(?P<value>[^"]*)(?P<suffix>")'
)
_CALVER_RE: Pattern[str] = re_compile(r"(?P<year>\d{4})\.(?P<mmdd>\d{4})\.(?P<counter>\d+)")
_STRICT_CALVER_RE: Pattern[str] = re_compile(
    r"(?P<year>\d{4})\.(?P<month>\d{2})(?P<day>\d{2})\.(?P<counter>\d{2})"
)


def next_calver(current: str, today: date) -> str:
    """Return the next CalVer for ``today`` given the ``current`` version.

    Same UTC day as the current version -> increment its counter; a new day (or a
    current version that is not CalVer) -> counter ``00``.
    """
    date_part = f"{today.year:04d}.{today.month:02d}{today.day:02d}"
    counter = 0
    match = _CALVER_RE.fullmatch(current.strip())
    if match is not None and f"{match['year']}.{match['mmdd']}" == date_part:
        counter = int(match["counter"]) + 1
    return f"{date_part}.{counter:02d}"


def read_current_version(version_path: Path) -> str:
    """Read the ``__version__`` literal from ``version_path``."""
    match = _VERSION_RE.search(version_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"No __version__ assignment found in {version_path}")
    return match["value"]


def write_version(version_path: Path, new_version: str) -> None:
    """Replace the single ``__version__`` literal in ``version_path``."""
    text = version_path.read_text(encoding="utf-8")
    updated, replaced = _VERSION_RE.subn(rf"\g<prefix>{new_version}\g<suffix>", text)
    if replaced != 1:
        raise ValueError(f"Expected exactly one __version__ in {version_path}, found {replaced}")
    version_path.write_text(updated, encoding="utf-8", newline="\n")


def normalize_calver(version: str) -> str:
    """Return the PEP 440 normalized form of a Cortex calendar version."""
    match = _STRICT_CALVER_RE.fullmatch(version)
    if match is None:
        raise ValueError(f"Invalid Cortex CalVer {version!r}; expected YYYY.MMDD.XX")
    year = int(match["year"])
    month = int(match["month"])
    day = int(match["day"])
    counter = int(match["counter"])
    date(year, month, day)
    return f"{year}.{int(f'{month:02d}{day:02d}')}.{counter}"


def write_server_version(server_path: Path, new_version: str) -> None:
    """Write the normalized package version to both MCP Registry fields."""
    raw: object = json.loads(server_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{server_path} must contain a JSON object")
    packages = raw.get("packages")
    if not isinstance(packages, list) or len(packages) != 1:
        raise ValueError(f"{server_path} must contain exactly one package object")
    package = packages[0]
    if not isinstance(package, dict):
        raise ValueError(f"{server_path} package entry must contain a JSON object")

    normalized = normalize_calver(new_version)
    raw["version"] = normalized
    package["version"] = normalized
    rendered = json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
    server_path.write_text(rendered, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: compute the next CalVer and (unless dry-run) write it."""
    parser = argparse.ArgumentParser(description="Bump Cortex to the next CalVer (YYYY.MMDD.XX).")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the next version; write nothing."
    )
    parser.add_argument(
        "--current", help="Override the current version (default: read _version.py)."
    )
    parser.add_argument("--date", help="Override today as YYYY-MM-DD UTC (for testing).")
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.date) if args.date else datetime.now(tz=timezone.utc).date()
    current = args.current if args.current else read_current_version(_VERSION_PATH)
    new_version = next_calver(current, today)

    if args.dry_run:
        print(new_version)
        return 0

    write_version(_VERSION_PATH, new_version)
    write_server_version(_SERVER_JSON_PATH, new_version)
    print(f"Bumped __version__: {current} -> {new_version}")
    print(f"Now release: git tag -a v{new_version} -m 'Cortex {new_version}'")
    print(f"            then: git push origin v{new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
