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
"""Generic ingestion CLI status and scheduled-execution orchestration."""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from ingestion.config import (
    IngestionConfigError,
    IngestionSettings,
    load_ingestion_settings,
)
from ingestion.constants import (
    ACTION_LOCKED,
    ACTION_RENEW_CREDENTIAL,
    ERROR_LOCKED,
    SCHEMA_VERSION,
)
from ingestion.credentials import (
    CredentialReader,
    CredentialReadError,
    SecretValue,
    check_credential,
)
from ingestion.engine import GenerationEngine
from ingestion.locking import IngestionLockedError, source_sync_lock
from ingestion.models import (
    AttemptResult,
    GenerationAttempt,
    HealthCounts,
    HealthStatus,
    SourceHealth,
)
from ingestion.scheduling import (
    RetryPolicy,
    TransientIngestionError,
    catch_up_due,
    run_with_backoff,
)
from ingestion.storage import IngestionStorage, IngestionStorageError

_LOG = logging.getLogger("cortex.ingestion.cli")
_COMMAND_STATUS = "status"
_COMMAND_DUE = "due"
_EXIT_OK = 0
_EXIT_NOT_DUE = 3
_EXIT_ERROR = 1


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _retry_policy(settings: IngestionSettings) -> RetryPolicy:
    return RetryPolicy(
        attempts=settings.retry_attempts,
        initial_seconds=settings.backoff_initial_seconds,
        maximum_seconds=settings.backoff_max_seconds,
        multiplier=settings.backoff_multiplier,
        jitter_ratio=settings.backoff_jitter_ratio,
    )


def _failed_health(
    storage: IngestionStorage,
    *,
    now: datetime,
    error_code: str,
    action_required: str,
    auth_expires_at: datetime | None = None,
) -> SourceHealth:
    previous = storage.load_health()
    health = SourceHealth(
        schema_version=SCHEMA_VERSION,
        source_kind=storage.source_kind,
        last_attempt_at=now,
        last_success_at=None if previous is None else previous.last_success_at,
        remote_cursor=None,
        auth_expires_at=auth_expires_at,
        status=HealthStatus.ERROR,
        error_code=error_code,
        action_required=action_required,
        counts=HealthCounts(),
        selection_fingerprint=(None if previous is None else previous.selection_fingerprint),
        scope_summaries=() if previous is None else previous.scope_summaries,
    )
    storage.write_health(health)
    return health


def execute_scheduled_attempt(
    storage: IngestionStorage,
    settings: IngestionSettings,
    attempt_factory: Callable[[SecretValue | None], GenerationAttempt],
    *,
    now: datetime | None = None,
    force: bool = False,
    credential_reader: CredentialReader | None = None,
    credential_target: str | None = None,
    auth_expires_at: datetime | None = None,
    selection_fingerprint: str | None = None,
    sleep: Callable[[float], None] | None = None,
    random_unit: Callable[[], float] | None = None,
) -> AttemptResult | None:
    """Own catch-up, locking, credential expiry, retry, and engine execution."""
    observed_at = _now_utc() if now is None else now
    previous = storage.load_health()
    last_success = None if previous is None else previous.last_success_at
    selection_changed = selection_fingerprint is not None and (
        previous is None or previous.selection_fingerprint != selection_fingerprint
    )
    if (
        not force
        and not selection_changed
        and not catch_up_due(
            last_success_at=last_success,
            now=observed_at,
            interval_seconds=settings.schedule_interval_seconds,
        )
    ):
        _LOG.info("ingestion_not_due source_kind=%s", storage.source_kind)
        return None

    try:
        with source_sync_lock(storage, timeout_seconds=settings.lock_timeout_seconds):
            credential_check = None
            if credential_reader is not None:
                if credential_target is None or auth_expires_at is None:
                    raise ValueError(
                        "credential_target and auth_expires_at are required with a reader"
                    )
                try:
                    credential_check = check_credential(
                        credential_reader,
                        target_name=credential_target,
                        auth_expires_at=auth_expires_at,
                        warning_days=settings.auth_expiry_warning_days,
                        now=observed_at,
                    )
                except CredentialReadError:
                    health = _failed_health(
                        storage,
                        now=observed_at,
                        error_code="credential_unavailable",
                        action_required=ACTION_RENEW_CREDENTIAL,
                        auth_expires_at=auth_expires_at,
                    )
                    return AttemptResult(
                        published=False,
                        generation_id=None,
                        health=health,
                    )
                if credential_check.status is HealthStatus.ERROR:
                    health = _failed_health(
                        storage,
                        now=observed_at,
                        error_code=credential_check.error_code or "credential_expired",
                        action_required=credential_check.action_required
                        or ACTION_RENEW_CREDENTIAL,
                        auth_expires_at=auth_expires_at,
                    )
                    return AttemptResult(
                        published=False,
                        generation_id=None,
                        health=health,
                    )

            secret = None if credential_check is None else credential_check.secret
            try:
                attempt = run_with_backoff(
                    lambda: attempt_factory(secret),
                    _retry_policy(settings),
                    sleep=time.sleep if sleep is None else sleep,
                    random_unit=random.random if random_unit is None else random_unit,
                )
                if (
                    selection_fingerprint is not None
                    and attempt.selection_fingerprint != selection_fingerprint
                ):
                    raise ValueError(
                        "attempt selection_fingerprint does not match the due decision"
                    )
            except TransientIngestionError:
                health = _failed_health(
                    storage,
                    now=observed_at,
                    error_code="transient_retries_exhausted",
                    action_required="Retry after the remote service recovers.",
                    auth_expires_at=auth_expires_at,
                )
                return AttemptResult(
                    published=False,
                    generation_id=None,
                    health=health,
                )
            except Exception as exc:
                _failed_health(
                    storage,
                    now=observed_at,
                    error_code="source_attempt_failed",
                    action_required="Review the source adapter diagnostics, then retry.",
                    auth_expires_at=auth_expires_at,
                )
                _LOG.error(
                    "ingestion_source_attempt_failed source_kind=%s error_type=%s",
                    storage.source_kind,
                    type(exc).__name__,
                )
                raise
            result = GenerationEngine(storage).run(attempt, now=observed_at)
            if (
                credential_check is not None
                and credential_check.status is HealthStatus.DEGRADED
                and result.health.status is HealthStatus.OK
            ):
                health = result.health.model_copy(
                    update={
                        "status": HealthStatus.DEGRADED,
                        "error_code": credential_check.error_code,
                        "action_required": credential_check.action_required,
                    }
                )
                storage.write_health(health)
                return cast(
                    AttemptResult,
                    AttemptResult.model_validate(result.model_dump() | {"health": health}),
                )
            return result
    except IngestionLockedError:
        health = _failed_health(
            storage,
            now=observed_at,
            error_code=ERROR_LOCKED,
            action_required=ACTION_LOCKED,
        )
        return AttemptResult(published=False, generation_id=None, health=health)


def _storage(settings: IngestionSettings, source_kind: str) -> IngestionStorage:
    return IngestionStorage(
        settings.data_root,
        source_kind,
        settings.retention_generations,
    )


def _canonical_source_kind(value: str) -> str:
    """Map the user-facing Confluence alias to its canonical document source."""
    aliases = {"doc": "doc", "confluence": "doc"}
    try:
        return aliases[value.casefold()]
    except KeyError as exc:
        supported = ", ".join(sorted(aliases))
        raise argparse.ArgumentTypeError(
            f"unsupported source kind '{value}'; choose one of: {supported}"
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Report generic ingestion health or whether startup catch-up is due."""
    parser = argparse.ArgumentParser(
        prog="cortex ingestion",
        description="Report the health of an ingestion source and its catch-up state.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="INGESTION.toml to use instead of the per-user file",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    command_help = {
        _COMMAND_STATUS: "Print the last recorded attempt as JSON (exit 1 on error state)",
        _COMMAND_DUE: "Print due or not-due for the startup catch-up (exit 3 when not due)",
    }
    for command, summary in command_help.items():
        subparser = subparsers.add_parser(command, help=summary)
        subparser.add_argument(
            "source_kind",
            type=_canonical_source_kind,
            help="doc, or its alias confluence",
        )
    namespace = parser.parse_args(argv)

    from cortex_logging import configure_logging

    configure_logging()
    try:
        settings = load_ingestion_settings(path=namespace.config)
        storage = _storage(settings, namespace.source_kind)
        health = storage.load_health()
    except (IngestionConfigError, IngestionStorageError) as exc:
        _LOG.error("ingestion_cli_refused error_type=%s", type(exc).__name__)
        sys.stderr.write(f"Cortex ingestion error: {exc}\n")
        return _EXIT_ERROR
    if namespace.command == _COMMAND_STATUS:
        if health is None:
            sys.stdout.write("No ingestion attempt has been recorded.\n")
            return _EXIT_ERROR
        sys.stdout.write(health.model_dump_json(indent=2) + "\n")
        return _EXIT_OK if health.status is not HealthStatus.ERROR else _EXIT_ERROR

    due = catch_up_due(
        last_success_at=None if health is None else health.last_success_at,
        now=_now_utc(),
        interval_seconds=settings.schedule_interval_seconds,
    )
    sys.stdout.write(("due" if due else "not-due") + "\n")
    return _EXIT_OK if due else _EXIT_NOT_DUE


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["execute_scheduled_attempt", "main"]
