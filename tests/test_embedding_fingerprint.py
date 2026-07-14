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
"""Embedding fingerprint creation, migration and refusal tests."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import pytest
from chromadb.errors import NotFoundError

import embedding_fingerprint
import server
from embedding_fingerprint import (
    EmbeddingFingerprintMismatchError,
    current_embedding_fingerprint,
    get_validated_collection,
)
from indexer import FastEmbedFunction


class Collection:
    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = dict(metadata)
        self.modify_calls = 0

    def modify(self, metadata: dict[str, Any]) -> None:
        self.modify_calls += 1
        self.metadata = dict(metadata)


class Client:
    def __init__(self, collection: Collection | None = None) -> None:
        self.collection = collection
        self.create_calls = 0

    def get_collection(self, **_kwargs: object) -> Collection:
        if self.collection is None:
            raise NotFoundError("collection not found")
        return self.collection

    def get_or_create_collection(
        self, metadata: dict[str, Any], **_kwargs: object
    ) -> Collection:
        self.create_calls += 1
        if self.collection is None:
            self.collection = Collection(metadata)
        return self.collection


@pytest.fixture(autouse=True)
def isolated_write_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        embedding_fingerprint,
        "chroma_write_lock",
        lambda: nullcontext(),
    )


def test_new_collection_is_created_with_fingerprint() -> None:
    client = Client()

    collection = get_validated_collection(client, embedding_function=object())

    assert client.create_calls == 1
    assert collection.metadata == {
        "hnsw:space": "cosine",
        **current_embedding_fingerprint(),
    }
    assert collection.modify_calls == 0


def test_unstamped_collection_is_migrated_exactly_once() -> None:
    collection = Collection({"hnsw:space": "cosine", "owner": "cortex"})
    client = Client(collection)

    first = get_validated_collection(client, embedding_function=object())
    second = get_validated_collection(client, embedding_function=object())

    assert first is second
    assert collection.modify_calls == 1
    assert collection.metadata == {
        "owner": "cortex",
        **current_embedding_fingerprint(),
    }


def test_unstamped_collection_refuses_non_attested_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = Collection({"hnsw:space": "cosine"})
    client = Client(collection)
    monkeypatch.setattr(embedding_fingerprint.fastembed, "__version__", "0.9.0")

    with pytest.raises(EmbeddingFingerprintMismatchError) as raised:
        get_validated_collection(client, embedding_function=object())

    assert "fastembed_version" in str(raised.value)
    assert collection.modify_calls == 0


@pytest.mark.parametrize(
    ("field", "stored_value"),
    [
        ("fastembed_version", "0.5.1"),
        ("pooling", "cls"),
    ],
)
def test_mismatch_refuses_access_with_actionable_message(
    field: str,
    stored_value: str,
) -> None:
    metadata: dict[str, Any] = current_embedding_fingerprint()
    metadata[field] = stored_value
    client = Client(Collection(metadata))

    with pytest.raises(EmbeddingFingerprintMismatchError) as raised:
        get_validated_collection(client, embedding_function=object())

    message = str(raised.value)
    assert field in message
    assert stored_value in message
    assert "delete" in message
    assert "sync.bat" in message


def test_fastembed_function_has_stable_name() -> None:
    assert FastEmbedFunction.name() == "cortex-fastembed"


def test_fastembed_function_config_is_serializable_without_model_load() -> None:
    function = object.__new__(FastEmbedFunction)
    function._model_name = "test-model"

    assert function.get_config() == {"model_name": "test-model"}


def test_cortex_search_returns_clean_fingerprint_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = current_embedding_fingerprint()
    stored = {**expected, "pooling": "cls"}

    def refuse_search(**_kwargs: object) -> list[dict[str, object]]:
        raise EmbeddingFingerprintMismatchError(expected, stored)

    monkeypatch.setattr(server, "search", refuse_search)

    response = server.cortex_search("query")

    assert response.startswith("## Cortex search refused")
    assert "pooling" in response
    assert "sync.bat" in response


def test_cortex_sync_returns_clean_fingerprint_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = current_embedding_fingerprint()
    stored = {**expected, "fastembed_version": "0.5.1"}

    def refuse_sync(**_kwargs: object) -> dict[str, int]:
        raise EmbeddingFingerprintMismatchError(expected, stored)

    monkeypatch.setattr(server, "sync", refuse_sync)

    response = server.cortex_sync()

    assert response.startswith("## Cortex sync refused")
    assert "fastembed_version" in response
    assert "sync.bat" in response


@pytest.mark.asyncio
async def test_server_lifespan_refuses_mismatched_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = current_embedding_fingerprint()
    stored = {**expected, "pooling": "cls"}

    def refuse_collection() -> None:
        raise EmbeddingFingerprintMismatchError(expected, stored)

    monkeypatch.setattr(server, "get_collection", refuse_collection)

    with pytest.raises(EmbeddingFingerprintMismatchError):
        async with server.app_lifespan(None):
            raise AssertionError("lifespan must not yield on mismatch")
