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
"""Pure product contracts that describe a compatible Cortex index."""

from __future__ import annotations

from typing import Literal

COLLECTION_NAME = "cortex"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_POOLING = "mean"

LEGACY_INDEX_EMBEDDING_MODEL = EMBEDDING_MODEL
LEGACY_INDEX_FASTEMBED_VERSION = "0.8.0"
LEGACY_INDEX_EMBEDDING_POOLING = "mean"

CHUNKING_CONTRACT_VERSION = "v3"
METADATA_SCHEMA_VERSION = 2
LEXICAL_INDEX_CONTRACT_VERSION = "v2"

# The source kinds a chunk may carry. They live here, not next to the chunker,
# because the search command line offers them as choices and must be buildable
# without loading the user configuration the chunker depends on.
SOURCE_KINDS = frozenset({"note", "doc", "message"})

RetrievalMode = Literal["vector", "hybrid", "rerank"]
RETRIEVAL_MODES: tuple[RetrievalMode, ...] = ("vector", "hybrid", "rerank")
# The bilingual evaluation favors multilingual semantic retrieval. Keep the
# lexical/English-reranker strategies explicit until validated for a corpus.
DEFAULT_RETRIEVAL_MODE: RetrievalMode = "vector"


def build_embedding_fingerprint(fastembed_version: str) -> dict[str, str]:
    """Build the runtime vector-space fingerprint without loading user configuration."""
    return {
        "embedding_model": EMBEDDING_MODEL,
        "fastembed_version": fastembed_version,
        "pooling": EMBEDDING_POOLING,
    }


__all__ = [
    "CHUNKING_CONTRACT_VERSION",
    "COLLECTION_NAME",
    "DEFAULT_RETRIEVAL_MODE",
    "EMBEDDING_MODEL",
    "EMBEDDING_POOLING",
    "LEGACY_INDEX_EMBEDDING_MODEL",
    "LEGACY_INDEX_EMBEDDING_POOLING",
    "LEGACY_INDEX_FASTEMBED_VERSION",
    "LEXICAL_INDEX_CONTRACT_VERSION",
    "METADATA_SCHEMA_VERSION",
    "RETRIEVAL_MODES",
    "RetrievalMode",
    "SOURCE_KINDS",
    "build_embedding_fingerprint",
]
