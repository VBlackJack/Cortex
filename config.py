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
"""Cortex product contracts and resolved per-user configuration."""

from pathlib import Path

from user_config import (
    CortexConfigError,
    load_user_config,
    local_data_home,
    require_kb_path,
)

_SCRIPT_DIR = Path(__file__).parent.resolve()
_USER_CONFIG = load_user_config(script_dir=_SCRIPT_DIR)

# Resolved per-user configuration. KB_PATH remains optional at import time so
# the MCP server can search an existing index without source-vault access.
KB_PATH = _USER_CONFIG.kb_path
CHROMA_PATH = _USER_CONFIG.chroma_path
INDEX_WHOLE_FOLDER = _USER_CONFIG.index_whole_folder
INCLUDED_SECTIONS = _USER_CONFIG.included_sections
EXCLUDED_DIRS = _USER_CONFIG.excluded_dirs
EXCLUDE_FILES = _USER_CONFIG.exclude_files
MAX_MARKDOWN_FILE_SIZE_BYTES = _USER_CONFIG.max_markdown_file_size_bytes
MAX_PDF_SIZE_BYTES = _USER_CONFIG.max_pdf_size_bytes
CORTEX_WRITE_LOCK_PATH = _USER_CONFIG.write_lock_path
CORTEX_WRITE_LOCK_TIMEOUT_SECONDS = _USER_CONFIG.write_lock_timeout_seconds
CORTEX_DATA_HOME = str(local_data_home())
CORTEX_LOG_DIR = str(Path(CORTEX_DATA_HOME) / "logs")
LEGACY_CHROMA_PATH = str(_SCRIPT_DIR / "chroma_db")

# Product contracts. Changing these values requires an explicit index contract
# migration; they are intentionally not user-configurable.
COLLECTION_NAME = "cortex"
ROOT_SECTION = "."
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Explicit contract: FastEmbed exposes no reliable pooling introspection.
# Mean pooling has applied to this model since qdrant/fastembed#436 (v0.6.0).
EMBEDDING_POOLING = "mean"

# Independent attestation of the legacy unstamped index on 2026-07-12.
LEGACY_INDEX_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
LEGACY_INDEX_FASTEMBED_VERSION = "0.8.0"
LEGACY_INDEX_EMBEDDING_POOLING = "mean"

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNK_MIN_CHARS = 300
SEARCH_TOP_K_MIN = 1
SEARCH_TOP_K_MAX = 10

FRESHNESS_CONTRACT_ID = "freshness-contract-v1"
FRESHNESS_CONTRACT_VERSION = "v1"
CHUNKING_CONTRACT_VERSION = "v3"
METADATA_SCHEMA_VERSION = 2
LEXICAL_INDEX_CONTRACT_VERSION = "v2"
SEARCH_RRF_K = 60
SEARCH_HYBRID_CANDIDATES = 40
SEARCH_RERANK_CANDIDATES = 20
RERANKER_MODEL = "jinaai/jina-reranker-v1-tiny-en"

LOG_FILE_NAME = "cortex.log"
LOG_MAX_BYTES = 5_000_000
LOG_BACKUP_COUNT = 5

__all__ = [
    "CHROMA_PATH",
    "CHUNKING_CONTRACT_VERSION",
    "CHUNK_MIN_CHARS",
    "CHUNK_OVERLAP",
    "CHUNK_SIZE",
    "COLLECTION_NAME",
    "CORTEX_DATA_HOME",
    "CORTEX_LOG_DIR",
    "CORTEX_WRITE_LOCK_PATH",
    "CORTEX_WRITE_LOCK_TIMEOUT_SECONDS",
    "CortexConfigError",
    "EMBEDDING_MODEL",
    "EMBEDDING_POOLING",
    "EXCLUDED_DIRS",
    "EXCLUDE_FILES",
    "FRESHNESS_CONTRACT_ID",
    "FRESHNESS_CONTRACT_VERSION",
    "INCLUDED_SECTIONS",
    "INDEX_WHOLE_FOLDER",
    "KB_PATH",
    "LEGACY_INDEX_EMBEDDING_MODEL",
    "LEGACY_INDEX_EMBEDDING_POOLING",
    "LEGACY_INDEX_FASTEMBED_VERSION",
    "LEGACY_CHROMA_PATH",
    "LEXICAL_INDEX_CONTRACT_VERSION",
    "LOG_BACKUP_COUNT",
    "LOG_FILE_NAME",
    "LOG_MAX_BYTES",
    "MAX_MARKDOWN_FILE_SIZE_BYTES",
    "MAX_PDF_SIZE_BYTES",
    "METADATA_SCHEMA_VERSION",
    "RERANKER_MODEL",
    "ROOT_SECTION",
    "SEARCH_RERANK_CANDIDATES",
    "SEARCH_TOP_K_MAX",
    "SEARCH_TOP_K_MIN",
    "SEARCH_HYBRID_CANDIDATES",
    "SEARCH_RRF_K",
    "require_kb_path",
]
