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
"""Purity and compatibility tests for the extracted index contract."""

from __future__ import annotations

import ast
from pathlib import Path

import config
import embedding_fingerprint
import index_contract

_ROOT = Path(__file__).resolve().parents[1]


def test_index_contract_has_no_local_imports() -> None:
    source = (_ROOT / "index_contract.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.partition(".")[0])
    local = {
        name
        for name in imported
        if (_ROOT / f"{name}.py").is_file() or (_ROOT / name).is_dir()
    }
    assert local == set()


def test_config_reexports_the_complete_index_contract() -> None:
    names = (
        "COLLECTION_NAME",
        "EMBEDDING_MODEL",
        "EMBEDDING_POOLING",
        "CHUNKING_CONTRACT_VERSION",
        "METADATA_SCHEMA_VERSION",
        "LEXICAL_INDEX_CONTRACT_VERSION",
        "LEGACY_INDEX_EMBEDDING_MODEL",
        "LEGACY_INDEX_FASTEMBED_VERSION",
        "LEGACY_INDEX_EMBEDDING_POOLING",
    )
    assert {name: getattr(config, name) for name in names} == {
        name: getattr(index_contract, name) for name in names
    }


def test_embedding_fingerprint_delegates_with_patchable_runtime_version(
    monkeypatch,
) -> None:
    monkeypatch.setattr(embedding_fingerprint.fastembed, "__version__", "fixture-version")
    assert embedding_fingerprint.current_embedding_fingerprint() == {
        "embedding_model": index_contract.EMBEDDING_MODEL,
        "fastembed_version": "fixture-version",
        "pooling": index_contract.EMBEDDING_POOLING,
    }
