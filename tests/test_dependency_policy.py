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
"""Bind the audited pins to the advisories the CI scan suppresses.

The four chromadb advisories were assessed against one exact chromadb release:
they all need the ChromaDB HTTP server, which Cortex never starts. The eight
Pillow advisories were assessed against one exact Pillow release: they all sit
in image decoders that Cortex never reaches. Each assessment is only valid for
the version it was made against, so bumping a pin must fail here and force the
ignore list to be re-derived. The release workflow replays the CI scan, so both
workflows must suppress the same advisories for the same lock file.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_AUDITED_CHROMADB_PIN = "chromadb==1.5.7"
_AUDITED_PILLOW_PIN = "pillow==12.3.0"
_LOCK_FILES = ("requirements.lock", "requirements-dev.lock", "requirements-model.lock")
_CHROMADB_ADVISORIES = frozenset(
    {
        "PYSEC-2026-311",
        "CVE-2026-45830",
        "CVE-2026-45831",
        "CVE-2026-45833",
    }
)
_PILLOW_ADVISORIES = frozenset(
    {
        "CVE-2026-112395",
        "CVE-2026-112397",
        "CVE-2026-112400",
        "CVE-2026-112404",
        "CVE-2026-112895",
        "CVE-2026-112896",
        "CVE-2026-112897",
        "CVE-2026-112899",
    }
)
_ASSESSED_ADVISORIES = _CHROMADB_ADVISORIES | _PILLOW_ADVISORIES
_AUDIT_INVOCATION_RE = re.compile(
    r"pip_audit -r (?P<lock>\S+)(?P<ignores>(?:\s*\\\s*--ignore-vuln\s+\S+)*)"
)
_IGNORE_RE = re.compile(r"--ignore-vuln\s+(\S+)")


def _requirements() -> list[str]:
    return (_REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()


def _workflow(name: str = "ci.yml") -> str:
    return (_WORKFLOWS / name).read_text(encoding="utf-8")


def _ignores_by_lock(workflow: str) -> dict[str, frozenset[str]]:
    invocations: dict[str, frozenset[str]] = {}
    for match in _AUDIT_INVOCATION_RE.finditer(workflow):
        lock = match.group("lock")
        assert lock not in invocations, f"{lock} is audited twice in one workflow."
        invocations[lock] = frozenset(_IGNORE_RE.findall(match.group("ignores")))
    return invocations


def test_chromadb_pin_matches_the_assessed_release() -> None:
    assert _AUDITED_CHROMADB_PIN in _requirements(), (
        "The chromadb pin changed. Re-audit the suppressed advisories in ci.yml "
        f"against the new release before updating {_AUDITED_CHROMADB_PIN!r} here."
    )


def test_pillow_pin_matches_the_assessed_release_in_every_lock() -> None:
    for lock in _LOCK_FILES:
        lines = (_REPO_ROOT / lock).read_text(encoding="utf-8").splitlines()
        pins = [line.split()[0] for line in lines if line.startswith("pillow==")]
        assert pins == [_AUDITED_PILLOW_PIN], (
            f"The Pillow pin in {lock} changed. Re-audit the suppressed Pillow "
            f"advisories in ci.yml before updating {_AUDITED_PILLOW_PIN!r} here."
        )


def test_ci_suppresses_exactly_the_assessed_advisories() -> None:
    suppressed = set(_IGNORE_RE.findall(_workflow()))
    assert suppressed == _ASSESSED_ADVISORIES, (
        "The pip-audit ignore list drifted from the assessed advisories. Record "
        "the new assessment in ci.yml and in this test together."
    )


def test_ci_audits_every_lock_with_its_assessed_ignores() -> None:
    expected = {
        "requirements.lock": _ASSESSED_ADVISORIES,
        "requirements-dev.lock": _ASSESSED_ADVISORIES,
        "requirements-model.lock": _PILLOW_ADVISORIES,
    }
    assert _ignores_by_lock(_workflow()) == expected


def test_release_audit_suppresses_the_same_advisories_as_ci() -> None:
    ci = _ignores_by_lock(_workflow("ci.yml"))
    release = _ignores_by_lock(_workflow("release.yml"))
    assert set(ci) == set(_LOCK_FILES), f"ci.yml audits {sorted(ci)}."
    assert release == ci, (
        "release.yml replays the CI vulnerability scan; its pip-audit ignore "
        "lists must match ci.yml lock file by lock file."
    )


def test_every_workflow_declares_least_privilege_permissions() -> None:
    workflows = sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "No workflow was discovered."
    missing = [
        path.name
        for path in workflows
        if not re.search(r"^permissions:", path.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert not missing, f"Workflows without a top-level permissions block: {missing}"
