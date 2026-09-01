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
"""Stable Confluence writer defaults and frozen schema provenance."""

CONFIG_FILE_NAME = "confluence.toml"
CONFIG_SCHEMA_VERSION = 1
SUPPORTED_CONFIG_SCHEMA_VERSIONS = frozenset({1, 2, 3})
SUBTREE_CONFIG_SCHEMA_VERSION = 3
CONFIG_BACKUP_SUFFIX = ".bak"
CONFIG_MUTATION_LOCK_SUFFIX = ".mutation.lock"
DEFAULT_CONFIG_MUTATION_LOCK_TIMEOUT_SECONDS = 5.0
FRONTMATTER_SCHEMA_VERSION = 2
SOURCE_KIND = "doc"
SOURCE_SYSTEM = "confluence"
DEFAULT_CREDENTIAL_TARGET = "cortex-spike"
DEFAULT_ATTACHMENT_SIZE_MB = 50
DEFAULT_FAILURE_THRESHOLD = 0.10
PAGE_LIMIT = 250
CLI_CONTRACT_VERSION = 1
PAGES_CONTRACT_VERSION = 2

# Stable process exit contract. Existing values 0, 1, and 3 retain their
# historical meanings; the unused values distinguish machine-actionable cases.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOCKED = 2
EXIT_NOT_DUE = 3
EXIT_AUTH = 4
EXIT_REMOTE = 5
EXIT_INVALID_INPUT = 6
EXIT_NOT_FOUND = 7
EXIT_OUTSIDE_ALLOWLIST = 8
EXIT_CONFLICT = 9
EXIT_INTEGRITY = 10

SCHEMA_SOURCE_COMMIT = "fceda69da9246e9cf927ca7b8ad68a330f5a7b9b"
JOB_SCHEMA_SHA256 = "7c9c2ff1452ca5418ab926e5f9e893b426cd0315e0d7621656014c738ec27b57"
RESULT_SCHEMA_SHA256 = "9776128c1a3db9959d7d0b0eb516d42897e29d317b8fee599eb097e4d277c765"

__all__ = [name for name in globals() if name.isupper()]
