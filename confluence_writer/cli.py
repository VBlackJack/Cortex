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
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from confluence_writer.config import (
    ConfluenceConfigError,
    load_confluence_settings,
    require_sync_settings,
)
from confluence_writer.constants import (
    EXIT_AUTH,
    EXIT_ERROR,
    EXIT_INVALID_INPUT,
    EXIT_LOCKED,
    EXIT_NOT_DUE,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_OUTSIDE_ALLOWLIST,
    EXIT_REMOTE,
    SOURCE_KIND,
)
from confluence_writer.converter import ConverterContractError
from confluence_writer.progress import emit_progress
from confluence_writer.resolver import (
    InvalidPageReferenceError,
    OutsideAllowlistError,
    build_pages_contract,
    preview_scope,
    resolve_page,
    validate_page_reference,
)
from confluence_writer.rest import (
    ConfluenceAuthError,
    ConfluenceNotFoundError,
    ConfluenceRestClient,
    ConfluenceRestError,
)
from confluence_writer.writer import ConfluenceWriter, ConfluenceWriterError
from ingestion.cli import execute_scheduled_attempt
from ingestion.config import IngestionConfigError, IngestionSettings, load_ingestion_settings
from ingestion.constants import ERROR_AUTH_EXPIRED, ERROR_LOCKED
from ingestion.credentials import (
    CredentialReadError,
    CredentialWriteError,
    SecretValue,
    WindowsCredentialReader,
    WindowsCredentialWriter,
)
from ingestion.engine import GenerationContractError
from ingestion.models import AttemptResult, GenerationAttempt
from ingestion.scheduling import TransientIngestionError
from ingestion.storage import IngestionStorage, IngestionStorageError
from user_config import CortexConfigError

_LOG = logging.getLogger("cortex.confluence_writer.cli")
_CREDENTIAL_ERROR_CODES = {
    ERROR_AUTH_EXPIRED,
    "credential_unavailable",
}


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
        return EXIT_ERROR
    sys.stdout.write(f"Credential stored in Windows Credential Manager as '{target_name}'.\n")
    return EXIT_OK


def _storage(ingestion_settings: IngestionSettings) -> IngestionStorage:
    return IngestionStorage(
        ingestion_settings.data_root,
        SOURCE_KIND,
        ingestion_settings.retention_generations,
    )


def _sync_result_exit_code(result: AttemptResult) -> int:
    """Map persisted machine error codes without parsing human output."""
    error_code = result.health.error_code
    if result.published:
        return EXIT_OK
    if error_code == ERROR_LOCKED:
        return EXIT_LOCKED
    if error_code in _CREDENTIAL_ERROR_CODES:
        return EXIT_AUTH
    if error_code == "transient_retries_exhausted":
        return EXIT_REMOTE
    return EXIT_ERROR


def _collect_with_progress(
    writer: ConfluenceWriter,
    secret: SecretValue | None,
) -> GenerationAttempt:
    attempt = writer.collect(_required_secret(secret))
    emit_progress("publication", 0, 1)
    return attempt


def _write_json(model: BaseModel) -> None:
    payload = model.model_dump_json(indent=2)
    sys.stdout.write(payload + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Store a PAT interactively or run the scheduled Confluence adapter."""
    parser = argparse.ArgumentParser(prog="cortex confluence")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--ingestion-config", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("store-credential")
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--force", action="store_true")
    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("reference")
    resolve_parser.add_argument("--json", action="store_true", required=True)
    pages_parser = subparsers.add_parser("pages")
    pages_parser.add_argument("--json", action="store_true", required=True)
    preview_parser = subparsers.add_parser("preview")
    preview_parser.add_argument("reference")
    preview_parser.add_argument("--json", action="store_true", required=True)
    namespace = parser.parse_args(argv)

    try:
        from cortex_logging import configure_logging

        configure_logging()
        settings = load_confluence_settings(path=namespace.config)
        if namespace.command == "store-credential":
            return _store_credential(settings.credential_target)
        if namespace.command in {"resolve", "preview"}:
            if settings.base_url is None or settings.auth_expires_at is None:
                raise ConfluenceConfigError(
                    "Confluence resolve requires: base_url, auth_expires_at"
                )
            validate_page_reference(namespace.reference, base_url=settings.base_url)
            if settings.auth_expires_at <= datetime.now(timezone.utc):
                sys.stderr.write("Cortex Confluence error: credential unavailable or expired.\n")
                return EXIT_AUTH
            secret = WindowsCredentialReader().read(settings.credential_target)
            client = ConfluenceRestClient(settings.base_url, secret)
            if namespace.command == "resolve":
                _write_json(resolve_page(namespace.reference, settings=settings, client=client))
                return EXIT_OK
            ingestion_settings = load_ingestion_settings(path=namespace.ingestion_config)
            _write_json(
                preview_scope(
                    namespace.reference,
                    settings=settings,
                    client=client,
                    storage_root=str(ingestion_settings.data_root.resolve()),
                    retention_generations=ingestion_settings.retention_generations,
                )
            )
            return EXIT_OK
        ingestion_settings = load_ingestion_settings(path=namespace.ingestion_config)
        storage = _storage(ingestion_settings)
        if namespace.command == "pages":
            _write_json(build_pages_contract(settings, storage))
            return EXIT_OK
        require_sync_settings(settings)
        if not _rechunk_v2_ready():
            sys.stderr.write(
                "Cortex Confluence error: metadata v2 rechunk is not deployed; "
                "real publication is blocked.\n"
            )
            return EXIT_ERROR
        writer = ConfluenceWriter(settings, storage)
        result = execute_scheduled_attempt(
            storage,
            ingestion_settings,
            lambda secret: _collect_with_progress(writer, secret),
            force=namespace.force,
            credential_reader=WindowsCredentialReader(),
            credential_target=settings.credential_target,
            auth_expires_at=settings.auth_expires_at,
            selection_fingerprint=settings.selection_fingerprint(),
        )
    except CortexConfigError as exc:
        _LOG.error("confluence_invalid_user_configuration")
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return EXIT_INVALID_INPUT
    except InvalidPageReferenceError as exc:
        _LOG.error("confluence_resolve_invalid")
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return EXIT_INVALID_INPUT
    except ConfluenceNotFoundError as exc:
        _LOG.error("confluence_resolve_not_found")
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return EXIT_NOT_FOUND
    except OutsideAllowlistError as exc:
        _LOG.error("confluence_resolve_outside_allowlist")
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return EXIT_OUTSIDE_ALLOWLIST
    except (CredentialReadError, ConfluenceAuthError) as exc:
        _LOG.error("confluence_auth_failed error_type=%s", type(exc).__name__)
        sys.stderr.write("Cortex Confluence error: authentication failed.\n")
        return EXIT_AUTH
    except (TransientIngestionError, ConfluenceRestError) as exc:
        _LOG.error("confluence_remote_failed error_type=%s", type(exc).__name__)
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return EXIT_REMOTE
    except (ConfluenceConfigError, IngestionConfigError) as exc:
        _LOG.error("confluence_invalid_configuration error_type=%s", type(exc).__name__)
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return EXIT_INVALID_INPUT
    except (
        ConfluenceWriterError,
        ConverterContractError,
        GenerationContractError,
        IngestionStorageError,
    ) as exc:
        _LOG.error(
            "confluence_cli_refused error_type=%s reason=%s",
            type(exc).__name__,
            str(exc),
        )
        sys.stderr.write(f"Cortex Confluence error: {exc}\n")
        return EXIT_ERROR
    if result is None:
        sys.stdout.write("Confluence sync is not due.\n")
        return EXIT_NOT_DUE
    if result.published:
        emit_progress("publication", 1, 1)
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    return _sync_result_exit_code(result)


def _required_secret(secret: SecretValue | None) -> SecretValue:
    if secret is None:
        raise RuntimeError("Confluence sync requires a credential reader.")
    return secret


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
