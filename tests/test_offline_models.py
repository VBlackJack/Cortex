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
"""Hermetic model-cache, offline activation and integrity tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastembed.rerank import cross_encoder

import doctor
import indexer
import offline_models
import reranker
from config import RERANKER_MODEL
from offline_models import ModelManifestError, ModelRuntime

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def reset_model_runtime() -> Iterable[None]:
    offline_models._reset_for_tests()
    indexer.FastEmbedFunction._instance = None
    indexer.FastEmbedFunction._initialized = False
    reranker._reset_for_tests()
    yield
    offline_models._reset_for_tests()
    indexer.FastEmbedFunction._instance = None
    indexer.FastEmbedFunction._initialized = False
    reranker._reset_for_tests()


def _environment(tmp_path: Path) -> dict[str, str]:
    return {"LOCALAPPDATA": str(tmp_path)}


def _write_manifest(cache_dir: Path, files: dict[str, bytes]) -> Path:
    declared: dict[str, str] = {}
    for relative_path, content in files.items():
        target = cache_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        declared[relative_path] = hashlib.sha256(content).hexdigest()
    manifest_path = cache_dir / offline_models.MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": offline_models.MANIFEST_SCHEMA_VERSION,
                "files": declared,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_valid_manifest_activates_embedded_mode_without_network(tmp_path: Path) -> None:
    environ = _environment(tmp_path)
    cache_dir = offline_models.model_cache_dir(environ)
    manifest_path = _write_manifest(
        cache_dir,
        {
            "models--qdrant--embedding/snapshots/abc/model.onnx": b"embedding",
            "models--jinaai--reranker/snapshots/def/model.onnx": b"reranker",
        },
    )

    runtime = offline_models.activate_if_embedded(environ)

    assert runtime == ModelRuntime(cache_dir.resolve(), True, manifest_path.resolve())
    assert runtime.local_files_only is True
    assert environ["HF_HUB_OFFLINE"] == "1"


def test_absent_manifest_preserves_online_behavior_with_stable_cache(tmp_path: Path) -> None:
    environ = _environment(tmp_path)

    runtime = offline_models.activate_if_embedded(environ)

    assert runtime.cache_dir == (tmp_path / "Cortex" / "models").resolve()
    assert runtime.embedded is False
    assert runtime.local_files_only is False
    assert runtime.manifest_path is None
    assert "HF_HUB_OFFLINE" not in environ


def test_corrupt_payload_is_rejected_before_offline_activation(tmp_path: Path) -> None:
    environ = _environment(tmp_path)
    cache_dir = offline_models.model_cache_dir(environ)
    _write_manifest(cache_dir, {"models--org--name/model.onnx": b"expected"})
    (cache_dir / "models--org--name" / "model.onnx").write_bytes(b"tampered")

    with pytest.raises(ModelManifestError, match="failed SHA-256 verification"):
        offline_models.activate_if_embedded(environ)

    assert "HF_HUB_OFFLINE" not in environ


def test_missing_manifest_file_is_rejected_without_fallback(tmp_path: Path) -> None:
    environ = _environment(tmp_path)
    cache_dir = offline_models.model_cache_dir(environ)
    manifest_path = cache_dir / offline_models.MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": offline_models.MANIFEST_SCHEMA_VERSION,
                "files": {"models--org--name/missing.onnx": "0" * 64},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ModelManifestError, match="is missing"):
        offline_models.activate_if_embedded(environ)

    assert "HF_HUB_OFFLINE" not in environ


def test_manifest_rejects_paths_outside_the_cache(tmp_path: Path) -> None:
    cache_dir = offline_models.model_cache_dir(_environment(tmp_path))
    manifest_path = cache_dir / offline_models.MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": offline_models.MANIFEST_SCHEMA_VERSION,
                "files": {"../escape.onnx": "0" * 64},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ModelManifestError, match="unsafe path"):
        offline_models.verify_manifest(cache_dir)


@pytest.mark.parametrize("embedded", [False, True])
def test_indexer_uses_shared_cache_and_manifest_gated_network_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    embedded: bool,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeTextEmbedding:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    runtime = ModelRuntime(
        tmp_path / "models",
        embedded,
        tmp_path / "models" / "manifest.json" if embedded else None,
    )
    monkeypatch.setattr(indexer, "TextEmbedding", FakeTextEmbedding)
    monkeypatch.setattr(indexer, "_MODEL_RUNTIME", runtime)

    indexer.FastEmbedFunction("embedding-model")

    assert calls == [
        {
            "model_name": "embedding-model",
            "cache_dir": str(runtime.cache_dir),
            "local_files_only": embedded,
        }
    ]


@pytest.mark.parametrize("embedded", [False, True])
def test_reranker_uses_shared_cache_and_manifest_gated_network_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    embedded: bool,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeCrossEncoder:
        def rerank(
            self,
            _query: str,
            documents: Sequence[str],
            batch_size: int = 64,
        ) -> Iterable[float]:
            del batch_size
            return [0.0] * len(documents)

    def fake_cross_encoder(model_name: str, **kwargs: Any) -> FakeCrossEncoder:
        calls.append((model_name, kwargs))
        return FakeCrossEncoder()

    runtime = ModelRuntime(
        tmp_path / "models",
        embedded,
        tmp_path / "models" / "manifest.json" if embedded else None,
    )
    monkeypatch.setattr(reranker, "TextCrossEncoder", fake_cross_encoder)
    monkeypatch.setattr(reranker, "_MODEL_RUNTIME", runtime)

    assert reranker.warmup_reranker() is None
    assert calls == [
        (
            RERANKER_MODEL,
            {
                "cache_dir": str(runtime.cache_dir),
                "threads": None,
                "cuda": False,
                "local_files_only": embedded,
            },
        )
    ]


def test_doctor_uses_shared_cache_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    cache_dir = tmp_path / "models"
    model_cache = cache_dir / f"models--{RERANKER_MODEL.replace('/', '--')}"
    model_cache.mkdir(parents=True)
    runtime = ModelRuntime(cache_dir, embedded=True, manifest_path=cache_dir / "manifest.json")

    class FakeCrossEncoder:
        def __init__(self, *_args: object, **kwargs: Any) -> None:
            calls.append(kwargs)

        def rerank(
            self,
            _query: str,
            documents: Sequence[str],
            batch_size: int = 64,
        ) -> Iterable[float]:
            del batch_size
            return [0.0] * len(documents)

    monkeypatch.setattr(offline_models, "activate_if_embedded", lambda: runtime)
    monkeypatch.setattr(cross_encoder, "TextCrossEncoder", FakeCrossEncoder)

    check = doctor._default_reranker_probe()

    assert check.status == "OK"
    assert check.details["cache_path"] == str(model_cache)
    assert calls == [
        {
            "cache_dir": str(cache_dir),
            "threads": None,
            "cuda": False,
            "local_files_only": True,
        }
    ]


def test_offline_activation_precedes_fastembed_imports() -> None:
    indexer_source = (ROOT / "indexer.py").read_text(encoding="utf-8")
    reranker_source = (ROOT / "reranker.py").read_text(encoding="utf-8")
    doctor_source = (ROOT / "doctor.py").read_text(encoding="utf-8")

    assert indexer_source.index("_MODEL_RUNTIME = activate_if_embedded()") < (
        indexer_source.index("from fastembed import TextEmbedding")
    )
    assert reranker_source.index("_MODEL_RUNTIME = activate_if_embedded()") < (
        reranker_source.index("from fastembed.rerank.cross_encoder import TextCrossEncoder")
    )
    assert doctor_source.index("model_runtime = activate_if_embedded()") < (
        doctor_source.index("from fastembed.rerank.cross_encoder import TextCrossEncoder")
    )
