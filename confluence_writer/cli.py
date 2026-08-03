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
"""Interactive credential storage and scheduled Confluence sync commands."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from confluence_writer.config import (
    ConfluenceConfigError,
    load_confluence_settings,
    require_sync_settings,
)
from confluence_writer.constants import SOURCE_KIND
from confluence_writer.converter import ConverterContractError
from confluence_writer.rest import ConfluenceRestError
from confluence_writer.writer import ConfluenceWriter, ConfluenceWriterError
from ingestion.cli import execute_scheduled_attempt
from ingestion.config import IngestionConfigError, load_ingestion_settings
from ingestion.credentials import (
    CredentialReadError,
    CredentialWriteError,
    SecretValue,
    WindowsCredentialReader,
    WindowsCredentialWriter,
)
from ingestion.engine import GenerationContractError
from ingestion.storage import IngestionStorage, IngestionStorageError

_LOG = logging.getLogger("cortex.confluence_writer.cli")
_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_NOT_DUE = 3


def _rechunk_v2_ready() -> bool:
    """Detect either v2 metadata marker allowed by the parent contract."""
    import config

    metadata_version = getattr(config, "METADATA_SCHEMA_VERSION", 0)
    chunking_version = getattr(config, "CHUNKING_CONTRACT_VERSION", "v3")
    metadata_ready = isinstance(metadata_version, int) and metadata_version >= 2
    return metadata_ready or chunking_version != "v3"


def _store_credential(target_name: str) -> int:
    try:
        secret = SecretValue(getpass.getpass("Confluence PAT: "))
        WindowsCredentialWriter().write(target_name, secret)
    except (CredentialReadError, CredentialWriteError) as exc:
        _LOG.error("confluence_credential_store_failed error_type=%s", type(exc).__name__)
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return _EXIT_ERROR
    sys.stdout.write(f"Credential stored in Windows Credential Manager as '{target_name}'.\n")
    return _EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Store a PAT interactively or run the scheduled Confluence adapter."""
    parser = argparse.ArgumentParser(prog="cortex confluence")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--ingestion-config", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("store-credential")
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--force", action="store_true")
    namespace = parser.parse_args(argv)

    from cortex_logging import configure_logging

    configure_logging()
    try:
        settings = load_confluence_settings(path=namespace.config)
        if namespace.command == "store-credential":
            return _store_credential(settings.credential_target)
        require_sync_settings(settings)
        if not _rechunk_v2_ready():
            sys.stderr.write(
                "Cortex Confluence error: metadata v2 rechunk is not deployed; "
                "real publication is blocked.\n"
            )
            return _EXIT_ERROR
        ingestion_settings = load_ingestion_settings(path=namespace.ingestion_config)
        storage = IngestionStorage(
            ingestion_settings.data_root,
            SOURCE_KIND,
            ingestion_settings.retention_generations,
        )
        writer = ConfluenceWriter(settings, storage)
        result = execute_scheduled_attempt(
            storage,
            ingestion_settings,
            lambda secret: writer.collect(_required_secret(secret)),
            force=namespace.force,
            credential_reader=WindowsCredentialReader(),
            credential_target=settings.credential_target,
            auth_expires_at=settings.auth_expires_at,
        )
    except (
        ConfluenceConfigError,
        ConfluenceRestError,
        ConfluenceWriterError,
        ConverterContractError,
        GenerationContractError,
        IngestionConfigError,
        IngestionStorageError,
    ) as exc:
        _LOG.error("confluence_cli_refused error_type=%s", type(exc).__name__)
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return _EXIT_ERROR
    if result is None:
        sys.stdout.write("Confluence sync is not due.\n")
        return _EXIT_NOT_DUE
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    return _EXIT_OK if result.published else _EXIT_ERROR


def _required_secret(secret: SecretValue | None) -> SecretValue:
    if secret is None:
        raise RuntimeError("Confluence sync requires a credential reader.")
    return secret


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
