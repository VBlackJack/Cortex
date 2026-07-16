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
"""Offline tests for the pinned model payload acquisition contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from offline_models import ModelManifestError, verify_manifest
from scripts.model_payload import (
    ModelPayloadError,
    fetch_models,
    generate_attestation,
    load_lock,
    prepare_payload,
    run_offline_smoke,
)


def _write_lock(path: Path) -> tuple[str, str]:
    embedding_revision = "a" * 40
    reranker_revision = "b" * 40
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fastembed_version": "0.8.0",
                "huggingface_hub_version": "1.2.3",
                "models": [
                    {
                        "role": "embedding",
                        "product_id": "sentence-transformers/test-embedding",
                        "repository": "qdrant/test-embedding-onnx",
                        "revision": embedding_revision,
                        "license": "apache-2.0",
                        "required_files": [
                            "config.json",
                            "model.onnx",
                            "special_tokens_map.json",
                            "tokenizer.json",
                            "tokenizer_config.json",
                        ],
                    },
                    {
                        "role": "reranker",
                        "product_id": "jinaai/test-reranker",
                        "repository": "jinaai/test-reranker",
                        "revision": reranker_revision,
                        "license": "apache-2.0",
                        "required_files": [
                            "config.json",
                            "onnx/model.onnx",
                            "special_tokens_map.json",
                            "tokenizer.json",
                            "tokenizer_config.json",
                        ],
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return embedding_revision, reranker_revision


def _snapshot(root: Path, repository: str, revision: str, files: dict[str, bytes]) -> None:
    cache = root / f"models--{repository.replace('/', '--')}"
    (cache / "refs").mkdir(parents=True)
    (cache / "refs" / "main").write_bytes(revision.encode("ascii"))
    snapshot = cache / "snapshots" / revision
    for relative, content in files.items():
        target = snapshot.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _complete_snapshot(root: Path, lock_path: Path) -> None:
    embedding_revision, reranker_revision = _write_lock(lock_path)
    _snapshot(
        root,
        "qdrant/test-embedding-onnx",
        embedding_revision,
        {
            "config.json": b"{}",
            "model.onnx": b"embedding",
            "special_tokens_map.json": b"{}",
            "tokenizer.json": b"{}",
            "tokenizer_config.json": b"{}",
        },
    )
    _snapshot(
        root,
        "jinaai/test-reranker",
        reranker_revision,
        {
            "config.json": b"{}",
            "onnx/model.onnx": b"reranker",
            "special_tokens_map.json": b"{}",
            "tokenizer.json": b"{}",
            "tokenizer_config.json": b"{}",
        },
    )


def test_repository_model_lock_pins_exact_sources() -> None:
    lock = load_lock()

    assert lock.fastembed_version == "0.8.0"
    assert lock.huggingface_hub_version == "1.9.2"
    assert [(pin.repository, pin.revision, pin.license_id) for pin in lock.models] == [
        (
            "qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q",
            "faf4aa4225822f3bc6376869cb1164e8e3feedd0",
            "apache-2.0",
        ),
        (
            "jinaai/jina-reranker-v1-tiny-en",
            "aca45de6945b5dc6399abcd2a9c55ded5dc9111f",
            "apache-2.0",
        ),
    ]


def test_fetch_materializes_portable_cache_without_network_in_test(tmp_path: Path) -> None:
    lock_path = tmp_path / "models.lock"
    embedding_revision, reranker_revision = _write_lock(lock_path)
    source_files = {
        "qdrant/test-embedding-onnx": {
            "config.json": b"{}",
            "model.onnx": b"e",
            "special_tokens_map.json": b"{}",
            "tokenizer.json": b"{}",
            "tokenizer_config.json": b"{}",
        },
        "jinaai/test-reranker": {
            "config.json": b"{}",
            "onnx/model.onnx": b"r",
            "special_tokens_map.json": b"{}",
            "tokenizer.json": b"{}",
            "tokenizer_config.json": b"{}",
        },
    }

    requested_patterns: dict[str, set[str]] = {}

    def downloader(
        *,
        repo_id: str,
        revision: str,
        cache_dir: Path,
        allow_patterns: list[str],
    ) -> str:
        requested_patterns[repo_id] = set(allow_patterns)
        snapshot = Path(cache_dir) / "raw" / repo_id.replace("/", "--") / revision
        for relative, content in source_files[repo_id].items():
            target = snapshot.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return str(snapshot)

    output = fetch_models(
        tmp_path / "portable",
        lock_path=lock_path,
        downloader=downloader,
    )

    assert (
        output / "models--qdrant--test-embedding-onnx" / "refs" / "main"
    ).read_text(encoding="ascii").strip() == embedding_revision
    assert (
        output
        / "models--jinaai--test-reranker"
        / "snapshots"
        / reranker_revision
        / "onnx"
        / "model.onnx"
    ).read_bytes() == b"r"
    assert not list(output.rglob("blobs"))
    assert requested_patterns == {
        "qdrant/test-embedding-onnx": {
            "config.json",
            "model.onnx",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        },
        "jinaai/test-reranker": {
            "config.json",
            "onnx/model.onnx",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        },
    }


def test_generation_is_deterministic_and_external_manifest_verifies(tmp_path: Path) -> None:
    lock_path = tmp_path / "models.lock"
    snapshot = tmp_path / "snapshot"
    _complete_snapshot(snapshot, lock_path)
    first_manifest = tmp_path / "first" / "manifest.json"
    first_inventory = tmp_path / "first" / "INVENTORY.md"
    second_manifest = tmp_path / "second" / "manifest.json"
    second_inventory = tmp_path / "second" / "INVENTORY.md"

    first = generate_attestation(
        snapshot,
        first_manifest,
        first_inventory,
        lock_path=lock_path,
    )
    second = generate_attestation(
        snapshot,
        second_manifest,
        second_inventory,
        lock_path=lock_path,
    )

    assert first == second
    assert first_manifest.read_bytes() == second_manifest.read_bytes()
    assert first_inventory.read_bytes() == second_inventory.read_bytes()
    assert verify_manifest(snapshot, first_manifest) == first_manifest.resolve()
    assert "embedding_fingerprint.py" in first_inventory.read_text(encoding="utf-8")
    assert json.loads(first_manifest.read_text(encoding="utf-8"))["runtime"] == {
        "fastembed_version": "0.8.0"
    }


def test_offline_smoke_proves_registry_contract_and_real_inference_shape(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "models.lock"
    snapshot = tmp_path / "snapshot"
    _complete_snapshot(snapshot, lock_path)
    proof = tmp_path / "OFFLINE_SMOKE.md"
    constructor_calls: list[tuple[str, str, bool]] = []

    class FakeEmbedding:
        @classmethod
        def list_supported_models(cls) -> list[dict[str, object]]:
            return [
                {
                    "model": "sentence-transformers/test-embedding",
                    "sources": {"hf": "qdrant/test-embedding-onnx"},
                    "model_file": "model.onnx",
                    "additional_files": [],
                    "dim": 2,
                }
            ]

        def __init__(
            self,
            model_name: str,
            *,
            cache_dir: str,
            local_files_only: bool,
        ) -> None:
            constructor_calls.append((model_name, cache_dir, local_files_only))

        def embed(self, _documents: list[str]) -> list[list[float]]:
            return [[0.25, -0.5]]

    class FakeReranker:
        @classmethod
        def list_supported_models(cls) -> list[dict[str, object]]:
            return [
                {
                    "model": "jinaai/test-reranker",
                    "sources": {"hf": "jinaai/test-reranker"},
                    "model_file": "onnx/model.onnx",
                    "additional_files": [],
                }
            ]

        def __init__(
            self,
            model_name: str,
            *,
            cache_dir: str,
            local_files_only: bool,
        ) -> None:
            constructor_calls.append((model_name, cache_dir, local_files_only))

        def rerank(self, _query: str, _documents: list[str]) -> list[float]:
            return [0.9, 0.1]

    dimension, score_count = run_offline_smoke(
        snapshot,
        proof,
        lock_path=lock_path,
        embedding_class=FakeEmbedding,
        reranker_class=FakeReranker,
        installed_fastembed_version="0.8.0",
    )

    assert (dimension, score_count) == (2, 2)
    assert constructor_calls == [
        ("sentence-transformers/test-embedding", str(snapshot.resolve()), True),
        ("jinaai/test-reranker", str(snapshot.resolve()), True),
    ]
    proof_text = proof.read_text(encoding="utf-8")
    assert "Result: **PASS**" in proof_text
    assert "Socket connect/connect_ex/create_connection blocked" in proof_text


def test_portable_layout_is_resolved_by_huggingface_hub_without_network(
    tmp_path: Path,
) -> None:
    from huggingface_hub import snapshot_download

    lock_path = tmp_path / "models.lock"
    snapshot = tmp_path / "snapshot"
    embedding_revision, reranker_revision = _write_lock(lock_path)
    _complete_snapshot(snapshot, lock_path)

    embedding = Path(
        snapshot_download(
            repo_id="qdrant/test-embedding-onnx",
            cache_dir=snapshot,
            local_files_only=True,
            allow_patterns=["config.json", "model.onnx"],
        )
    )
    reranker = Path(
        snapshot_download(
            repo_id="jinaai/test-reranker",
            cache_dir=snapshot,
            local_files_only=True,
            allow_patterns=["config.json", "onnx/model.onnx"],
        )
    )

    assert embedding.name == embedding_revision
    assert reranker.name == reranker_revision
    assert (embedding / "model.onnx").is_file()
    assert (reranker / "onnx" / "model.onnx").is_file()


def test_prepare_uses_local_fallback_and_copies_only_declared_files(tmp_path: Path) -> None:
    lock_path = tmp_path / "models.lock"
    snapshot = tmp_path / "snapshot"
    _complete_snapshot(snapshot, lock_path)
    manifest = tmp_path / "attestation" / "manifest.json"
    inventory = tmp_path / "attestation" / "INVENTORY.md"
    generate_attestation(snapshot, manifest, inventory, lock_path=lock_path)
    (snapshot / "not-attested.bin").write_bytes(b"never bundle this")

    output, _total_bytes = prepare_payload(
        tmp_path / "payload",
        manifest_path=manifest,
        lock_path=lock_path,
        environ={"CORTEX_MODEL_SNAPSHOT_DIR": str(snapshot)},
    )

    assert (output / "manifest.json").read_bytes() == manifest.read_bytes()
    assert not (output / "not-attested.bin").exists()
    assert verify_manifest(output) == output / "manifest.json"


def test_prepare_fails_hard_on_corrupt_local_snapshot(tmp_path: Path) -> None:
    lock_path = tmp_path / "models.lock"
    snapshot = tmp_path / "snapshot"
    _complete_snapshot(snapshot, lock_path)
    manifest = tmp_path / "manifest.json"
    inventory = tmp_path / "INVENTORY.md"
    generate_attestation(snapshot, manifest, inventory, lock_path=lock_path)
    model_file = next(snapshot.rglob("model.onnx"))
    model_file.write_bytes(b"corrupt")

    with pytest.raises(ModelManifestError, match="failed SHA-256 verification"):
        prepare_payload(
            tmp_path / "payload",
            source_dir=snapshot,
            manifest_path=manifest,
            lock_path=lock_path,
            environ={},
        )


def test_prepare_requires_precommitted_manifest_before_fetch(tmp_path: Path) -> None:
    lock_path = tmp_path / "models.lock"
    _write_lock(lock_path)
    called = False

    def downloader(**_kwargs: object) -> str:
        nonlocal called
        called = True
        return "unreachable"

    with pytest.raises(ModelPayloadError, match="Committed model manifest is missing"):
        prepare_payload(
            tmp_path / "payload",
            manifest_path=tmp_path / "missing-manifest.json",
            lock_path=lock_path,
            environ={},
            downloader=downloader,
        )

    assert called is False


def test_manifest_hashes_cover_model_bytes_not_vector_contract(tmp_path: Path) -> None:
    lock_path = tmp_path / "models.lock"
    snapshot = tmp_path / "snapshot"
    _complete_snapshot(snapshot, lock_path)
    manifest = tmp_path / "manifest.json"
    inventory = tmp_path / "INVENTORY.md"
    generate_attestation(snapshot, manifest, inventory, lock_path=lock_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    relative = next(path for path in data["files"] if path.endswith("model.onnx"))
    file_path = snapshot.joinpath(*relative.split("/"))

    assert data["files"][relative] == hashlib.sha256(file_path.read_bytes()).hexdigest()
