# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Persist and validate the vector-space contract of a Chroma collection."""

from __future__ import annotations

import logging
from typing import Any

import fastembed
from chromadb.errors import NotFoundError

from config import (
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    EMBEDDING_POOLING,
    LEGACY_INDEX_EMBEDDING_MODEL,
    LEGACY_INDEX_EMBEDDING_POOLING,
    LEGACY_INDEX_FASTEMBED_VERSION,
)
from write_lock import chroma_write_lock

_LOG = logging.getLogger("cortex.embedding_fingerprint")
_FINGERPRINT_KEYS = ("embedding_model", "fastembed_version", "pooling")
_IMMUTABLE_COLLECTION_METADATA_KEYS = {"hnsw:space"}


class EmbeddingFingerprintMismatchError(RuntimeError):
    """Raised before access to a collection from another vector space."""

    def __init__(
        self,
        expected: dict[str, str],
        stored: dict[str, object],
    ) -> None:
        self.expected = expected
        self.stored = stored
        self.differences = {
            key: {"stored": stored.get(key, "<missing>"), "runtime": value}
            for key, value in expected.items()
            if stored.get(key) != value
        }
        details = "; ".join(
            f"{key}: index={values['stored']!r}, runtime={values['runtime']!r}"
            for key, values in self.differences.items()
        )
        super().__init__(
            "Cortex embedding fingerprint mismatch. "
            f"{details}. Refusing search and writes because the vector spaces "
            "are incompatible. Rebuild procedure: quit Claude Desktop, delete "
            f"'{CHROMA_PATH}', then run sync.bat."
        )


def current_embedding_fingerprint() -> dict[str, str]:
    """Return the runtime vector-space contract persisted with the index."""
    return {
        "embedding_model": EMBEDDING_MODEL,
        "fastembed_version": fastembed.__version__,
        "pooling": EMBEDDING_POOLING,
    }


def legacy_index_fingerprint() -> dict[str, str]:
    """Return the independently attested contract of the unstamped index."""
    return {
        "embedding_model": LEGACY_INDEX_EMBEDDING_MODEL,
        "fastembed_version": LEGACY_INDEX_FASTEMBED_VERSION,
        "pooling": LEGACY_INDEX_EMBEDDING_POOLING,
    }


def _stored_fingerprint(collection: Any) -> dict[str, object]:
    metadata = collection.metadata or {}
    return {key: metadata[key] for key in _FINGERPRINT_KEYS if key in metadata}


def _validate_fingerprint(collection: Any) -> bool:
    """Validate a complete fingerprint; return False when entirely absent."""
    expected = current_embedding_fingerprint()
    stored = _stored_fingerprint(collection)
    if not stored:
        return False
    if stored != expected:
        _LOG.error(
            "embedding_fingerprint_mismatch collection=%s stored=%s runtime=%s",
            COLLECTION_NAME,
            stored,
            expected,
        )
        raise EmbeddingFingerprintMismatchError(expected, stored)
    return True


def _stamp_legacy_collection(collection: Any) -> None:
    expected = current_embedding_fingerprint()
    attested = legacy_index_fingerprint()
    if expected != attested:
        _LOG.error(
            "embedding_fingerprint_migration_refused collection=%s "
            "attested=%s runtime=%s",
            COLLECTION_NAME,
            attested,
            expected,
        )
        raise EmbeddingFingerprintMismatchError(expected, dict(attested))
    # Chroma forbids passing hnsw:space to modify(); the actual distance
    # configuration remains immutable in the collection schema.
    metadata = {
        key: value
        for key, value in (collection.metadata or {}).items()
        if key not in _IMMUTABLE_COLLECTION_METADATA_KEYS
    }
    metadata.update(attested)
    collection.modify(metadata=metadata)
    _LOG.warning(
        "embedding_fingerprint_migrated collection=%s fingerprint=%s "
        "attestation_date=2026-07-12",
        COLLECTION_NAME,
        attested,
    )


def get_validated_collection(client: Any, embedding_function: Any) -> Any:
    """Open/create a collection, migrate an unstamped legacy index, and validate."""
    try:
        collection = client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=embedding_function,
        )
    except NotFoundError:
        with chroma_write_lock():
            try:
                collection = client.get_collection(
                    name=COLLECTION_NAME,
                    embedding_function=embedding_function,
                )
            except NotFoundError:
                fingerprint = current_embedding_fingerprint()
                collection = client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    embedding_function=embedding_function,
                    metadata={"hnsw:space": "cosine", **fingerprint},
                )
                _LOG.info(
                    "embedding_fingerprint_created collection=%s fingerprint=%s",
                    COLLECTION_NAME,
                    fingerprint,
                )
                return collection

    if _validate_fingerprint(collection):
        return collection

    with chroma_write_lock():
        collection = client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=embedding_function,
        )
        if not _validate_fingerprint(collection):
            _stamp_legacy_collection(collection)
    return collection
