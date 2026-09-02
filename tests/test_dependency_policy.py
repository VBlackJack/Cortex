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
"""Bind the audited chromadb pin to the advisories the CI scan suppresses.

The four suppressed advisories were assessed against one exact chromadb
release: they all need the ChromaDB HTTP server, which Cortex never starts.
That assessment is only valid for the version it was made against, so bumping
the pin must fail here and force the ignore list to be re-derived.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AUDITED_CHROMADB_PIN = "chromadb==1.5.7"
_ASSESSED_ADVISORIES = frozenset(
    {
        "PYSEC-2026-311",
        "CVE-2026-45830",
        "CVE-2026-45831",
        "CVE-2026-45833",
    }
)


def _requirements() -> list[str]:
    return (_REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()


def _workflow() -> str:
    return (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_chromadb_pin_matches_the_assessed_release() -> None:
    assert _AUDITED_CHROMADB_PIN in _requirements(), (
        "The chromadb pin changed. Re-audit the suppressed advisories in ci.yml "
        f"against the new release before updating {_AUDITED_CHROMADB_PIN!r} here."
    )


def test_ci_suppresses_exactly_the_assessed_advisories() -> None:
    suppressed = set(re.findall(r"--ignore-vuln\s+(\S+)", _workflow()))
    assert suppressed == _ASSESSED_ADVISORIES, (
        "The pip-audit ignore list drifted from the assessed advisories. Record "
        "the new assessment in ci.yml and in this test together."
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
