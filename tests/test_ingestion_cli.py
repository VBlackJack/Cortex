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
"""Installed console routing tests for generic ingestion commands."""

from __future__ import annotations

import argparse

import pytest

import cli
import ingestion.cli as ingestion_cli


def test_root_cli_routes_ingestion_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[str] = []

    def run(arguments: list[str]) -> int:
        received.extend(arguments)
        return 7

    monkeypatch.setattr(ingestion_cli, "main", run)

    assert cli.main(["ingestion", "status", "fixture-source"]) == 7
    assert received == ["status", "fixture-source"]


def test_confluence_source_alias_resolves_to_canonical_document_health() -> None:
    assert ingestion_cli._canonical_source_kind("doc") == "doc"
    assert ingestion_cli._canonical_source_kind("confluence") == "doc"
    assert ingestion_cli._canonical_source_kind("CONFLUENCE") == "doc"


def test_unknown_source_kind_is_rejected_before_storage_lookup() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="unsupported source kind"):
        ingestion_cli._canonical_source_kind("typo")
