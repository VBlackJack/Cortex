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
"""Stable ingestion file names, schema versions, and defaults."""

from __future__ import annotations

SCHEMA_VERSION = 1
CONFIG_SCHEMA_VERSION = 1
DEFAULT_RETENTION_GENERATIONS = 2
DEFAULT_AUTH_EXPIRY_WARNING_DAYS = 14
DEFAULT_LOCK_TIMEOUT_SECONDS = 0.0
DEFAULT_RETRY_ATTEMPTS = 4
DEFAULT_BACKOFF_INITIAL_SECONDS = 1.0
DEFAULT_BACKOFF_MAX_SECONDS = 60.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_BACKOFF_JITTER_RATIO = 0.2
DEFAULT_SCHEDULE_INTERVAL_SECONDS = 86_400.0

INGESTION_DIRECTORY_NAME = "ingestion"
CONFIG_FILE_NAME = "ingestion.toml"
GENERATIONS_DIRECTORY_NAME = "generations"
DOCUMENTS_DIRECTORY_NAME = "documents"
MANIFEST_FILE_NAME = "manifest.json"
HEALTH_FILE_NAME = "source-health.json"
CURRENT_POINTER_FILE_NAME = "current.json"
LOCK_FILE_NAME = "sync.lock"
PENDING_PREFIX = ".pending-"
TEMPORARY_FILE_SUFFIX = ".tmp"

ERROR_ATTEMPT_IN_PROGRESS = "attempt_in_progress"
ERROR_AUTH_EXPIRES_SOON = "credential_expires_soon"
ERROR_AUTH_EXPIRED = "credential_expired"
ERROR_LOCKED = "sync_already_running"
ERROR_PARTIAL_FAILURE = "partial_failure"
ERROR_RUN_FAILED = "run_failed"
ERROR_THRESHOLD_EXCEEDED = "failure_threshold_exceeded"

ACTION_ATTEMPT_IN_PROGRESS = (
    "The previous generation remains active until this ingestion attempt completes."
)
ACTION_RENEW_CREDENTIAL = (
    "Renew the Windows Credential Manager entry interactively, then run ingestion again."
)
ACTION_LOCKED = "Wait for the active ingestion attempt to finish, then retry."

__all__ = [name for name in globals() if name.isupper()]
