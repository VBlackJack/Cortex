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
"""Credential, scheduling, overlap, configuration, and schema tests."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cortex_logging import configure_logging
from ingestion.cli import execute_scheduled_attempt
from ingestion.config import IngestionConfigError, IngestionSettings, load_ingestion_settings
from ingestion.credentials import SecretValue, check_credential
from ingestion.models import (
    CollectedDocument,
    GenerationAttempt,
    GenerationManifest,
    HealthStatus,
    SourceHealth,
)
from ingestion.scheduling import (
    RetryPolicy,
    TransientIngestionError,
    catch_up_due,
    run_with_backoff,
)
from ingestion.storage import IngestionStorage

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
_FAKE_SECRET = "fixture-only-fake-secret-4e552cc8"


class FakeCredentialReader:
    """Credential Manager substitute containing an explicitly fake value."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def read(self, target_name: str) -> SecretValue:
        """Return a redacting wrapper around the fixture-only value."""
        self.calls.append(target_name)
        return SecretValue(_FAKE_SECRET)


@pytest.fixture
def ingestion_file_logger(tmp_path: Path) -> tuple[object, Path]:
    """Configure then fully restore the shared Cortex logger after one test."""
    import logging

    target = logging.getLogger("cortex")
    previous_level = target.level
    previous_propagate = target.propagate
    previous_handlers = list(target.handlers)
    logs = tmp_path / "logs"
    logger = configure_logging(log_dir=logs, logger_name="cortex")
    try:
        yield logger, logs
    finally:
        for handler in list(logger.handlers):
            if handler not in previous_handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _settings(tmp_path: Path, **changes: object) -> IngestionSettings:
    values: dict[str, object] = {
        "data_root": tmp_path / "state",
        "lock_timeout_seconds": 0.0,
        "schedule_interval_seconds": 60.0,
        "backoff_initial_seconds": 0.01,
        "backoff_max_seconds": 0.02,
    }
    values.update(changes)
    return IngestionSettings.model_validate(values)


def _attempt(body: bytes = b"fixture content\n") -> GenerationAttempt:
    return GenerationAttempt(
        documents=(
            CollectedDocument(
                source_uid="document-1",
                path="published/document-1.md",
                content=body,
            ),
        ),
        remote_seen_source_uids=frozenset({"document-1"}),
        enumeration_complete=True,
        enumeration_succeeded=True,
    )


def test_persisted_models_publish_json_schemas() -> None:
    manifest_schema = GenerationManifest.model_json_schema()
    health_schema = SourceHealth.model_json_schema()
    assert set(manifest_schema["required"]) == {
        "schema_version",
        "generation_id",
        "published_at",
        "documents",
        "tombstones",
    }
    assert "documents" in manifest_schema["properties"]
    assert "tombstones" in manifest_schema["properties"]
    assert set(health_schema["required"]) == {
        "schema_version",
        "source_kind",
        "last_attempt_at",
        "last_success_at",
        "remote_cursor",
        "auth_expires_at",
        "status",
        "error_code",
        "action_required",
        "counts",
    }
    assert "counts" in health_schema["properties"]


def test_ingestion_config_uses_environment_over_toml_over_defaults(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ingestion.toml"
    config_path.write_text(
        "schema_version = 1\nretention_generations = 3\n",
        encoding="utf-8",
    )
    settings = load_ingestion_settings(
        path=config_path,
        environ={
            "LOCALAPPDATA": str(tmp_path / "local"),
            "CORTEX_INGESTION_RETENTION_GENERATIONS": "4",
        },
    )
    assert settings.retention_generations == 4
    assert settings.auth_expiry_warning_days == 14
    assert settings.data_root == tmp_path / "local" / "Cortex" / "ingestion"


def test_ingestion_config_rejects_secret_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "ingestion.toml"
    config_path.write_text(
        'schema_version = 1\nsecret = "not-accepted"\n',
        encoding="utf-8",
    )
    with pytest.raises(IngestionConfigError, match="Unknown ingestion configuration key"):
        load_ingestion_settings(path=config_path, environ={})
    with pytest.raises(IngestionConfigError, match="CORTEX_INGESTION_SECRET"):
        load_ingestion_settings(
            path=tmp_path / "absent.toml",
            environ={"CORTEX_INGESTION_SECRET": _FAKE_SECRET},
        )


def test_mocked_credential_expiry_degrades_then_errors_without_secret_leak(
    tmp_path: Path,
    ingestion_file_logger: tuple[object, Path],
) -> None:
    reader = FakeCredentialReader()
    warning = check_credential(
        reader,
        target_name="fixture-target",
        auth_expires_at=_NOW + timedelta(days=7),
        warning_days=14,
        now=_NOW,
    )
    expired = check_credential(
        reader,
        target_name="fixture-target",
        auth_expires_at=_NOW,
        warning_days=14,
        now=_NOW,
    )
    assert warning.status is HealthStatus.DEGRADED
    assert warning.action_required is not None
    assert expired.status is HealthStatus.ERROR
    assert expired.action_required is not None
    assert _FAKE_SECRET not in repr(warning)
    assert _FAKE_SECRET not in repr(expired)

    settings = _settings(tmp_path)
    storage = IngestionStorage(settings.data_root, "doc", 2)
    first = execute_scheduled_attempt(
        storage,
        settings,
        lambda _secret: _attempt(),
        now=_NOW,
        force=True,
    )
    assert first is not None and first.published
    pointer = storage.current_generation_id()
    logger, logs = ingestion_file_logger
    warning_result = execute_scheduled_attempt(
        storage,
        settings,
        lambda _secret: _attempt(b"warning generation\n"),
        now=_NOW + timedelta(minutes=30),
        force=True,
        credential_reader=reader,
        credential_target="fixture-target",
        auth_expires_at=_NOW + timedelta(days=7),
    )
    assert warning_result is not None
    assert warning_result.published
    assert warning_result.health.status is HealthStatus.DEGRADED
    pointer = storage.current_generation_id()

    result = execute_scheduled_attempt(
        storage,
        settings,
        lambda _secret: _attempt(),
        now=_NOW + timedelta(hours=1),
        force=True,
        credential_reader=reader,
        credential_target="fixture-target",
        auth_expires_at=_NOW,
    )
    for handler in logger.handlers:  # type: ignore[attr-defined]
        handler.flush()
    assert result is not None
    assert not result.published
    assert result.health.status is HealthStatus.ERROR
    assert result.health.action_required is not None
    assert storage.current_generation_id() == pointer
    assert _FAKE_SECRET not in (logs / "cortex.log").read_text(encoding="utf-8")


def test_exhausted_transient_retries_write_error_health(tmp_path: Path) -> None:
    settings = _settings(tmp_path, retry_attempts=2)
    storage = IngestionStorage(settings.data_root, "doc", 2)
    calls = 0

    def fail(_secret: SecretValue | None) -> GenerationAttempt:
        nonlocal calls
        calls += 1
        raise TransientIngestionError("fixture remote failure")

    result = execute_scheduled_attempt(
        storage,
        settings,
        fail,
        now=_NOW,
        force=True,
        sleep=lambda _seconds: None,
        random_unit=lambda: 0.5,
    )

    assert calls == 2
    assert result is not None
    assert not result.published
    assert result.health.status is HealthStatus.ERROR
    assert result.health.error_code == "transient_retries_exhausted"


def test_double_launch_allows_only_one_sync_body(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = IngestionStorage(settings.data_root, "doc", 2)
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    results: list[object] = []

    def blocking_factory(_secret: SecretValue | None) -> GenerationAttempt:
        calls.append("executed")
        entered.set()
        assert release.wait(timeout=5.0)
        return _attempt()

    def first_run() -> None:
        results.append(
            execute_scheduled_attempt(
                storage,
                settings,
                blocking_factory,
                now=_NOW,
                force=True,
            )
        )

    first = threading.Thread(target=first_run)
    first.start()
    assert entered.wait(timeout=5.0)
    second = execute_scheduled_attempt(
        storage,
        settings,
        blocking_factory,
        now=_NOW,
        force=True,
    )
    release.set()
    first.join(timeout=5.0)
    assert not first.is_alive()
    assert calls == ["executed"]
    assert second is not None
    assert not second.published
    assert len(results) == 1


def test_selection_fingerprint_change_bypasses_cadence(tmp_path: Path) -> None:
    settings = _settings(tmp_path, schedule_interval_seconds=86_400.0)
    storage = IngestionStorage(settings.data_root, "doc", 2)
    first_fingerprint = "a" * 64
    second_fingerprint = "b" * 64
    first = _attempt().model_copy(update={"selection_fingerprint": first_fingerprint})
    second = _attempt(body=b"expanded scope\n").model_copy(
        update={"selection_fingerprint": second_fingerprint}
    )

    first_result = execute_scheduled_attempt(
        storage,
        settings,
        lambda _secret: first,
        now=_NOW,
        force=True,
        selection_fingerprint=first_fingerprint,
    )
    second_result = execute_scheduled_attempt(
        storage,
        settings,
        lambda _secret: second,
        now=_NOW + timedelta(minutes=1),
        selection_fingerprint=second_fingerprint,
    )

    assert first_result is not None and first_result.published
    assert second_result is not None and second_result.published
    assert second_result.health.selection_fingerprint == second_fingerprint


def test_unchanged_selection_still_respects_cadence(tmp_path: Path) -> None:
    settings = _settings(tmp_path, schedule_interval_seconds=86_400.0)
    storage = IngestionStorage(settings.data_root, "doc", 2)
    fingerprint = "c" * 64
    attempt = _attempt().model_copy(update={"selection_fingerprint": fingerprint})
    assert (
        execute_scheduled_attempt(
            storage,
            settings,
            lambda _secret: attempt,
            now=_NOW,
            force=True,
            selection_fingerprint=fingerprint,
        )
        is not None
    )

    assert (
        execute_scheduled_attempt(
            storage,
            settings,
            lambda _secret: attempt,
            now=_NOW + timedelta(minutes=1),
            selection_fingerprint=fingerprint,
        )
        is None
    )


def test_transient_backoff_is_exponential_with_jitter() -> None:
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TransientIngestionError("fixture transient failure")
        return "ok"

    result = run_with_backoff(
        operation,
        RetryPolicy(
            attempts=3,
            initial_seconds=2.0,
            maximum_seconds=8.0,
            multiplier=2.0,
            jitter_ratio=0.25,
        ),
        sleep=delays.append,
        random_unit=lambda: 1.0,
    )
    assert result == "ok"
    assert delays == [2.5, 5.0]


def test_startup_catch_up_detects_missed_window() -> None:
    assert catch_up_due(last_success_at=None, now=_NOW, interval_seconds=60.0)
    assert catch_up_due(
        last_success_at=_NOW - timedelta(seconds=61),
        now=_NOW,
        interval_seconds=60.0,
    )
    assert not catch_up_due(
        last_success_at=_NOW - timedelta(seconds=59),
        now=_NOW,
        interval_seconds=60.0,
    )
