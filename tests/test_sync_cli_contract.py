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
"""Machine-facing sync CLI contract tests for Companion consumers."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

import indexer
from confluence_writer.constants import (
    EXIT_ERROR,
    EXIT_INVALID_INPUT,
    EXIT_LOCKED,
    EXIT_OK,
)
from embedding_fingerprint import EmbeddingFingerprintMismatchError
from ingestion.config import IngestionConfigError
from ingestion.locking import IngestionLockedError
from ingestion.storage import IngestionStorageError
from sync_contract import (
    SyncError,
    SyncIndexes,
    SyncIngestion,
    SyncReport,
    SyncScope,
    build_sync_report,
)
from user_config import CortexConfigError
from write_lock import CortexWriteLockedError


@pytest.fixture(autouse=True)
def _disable_logging_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cortex_logging.configure_logging", lambda: None)


def _report(
    *,
    counters: dict[str, int] | None = None,
    indexes: SyncIndexes | None = None,
    errors: list[SyncError] | None = None,
) -> SyncReport:
    return build_sync_report(
        counters=(
            {
                "published_files": 0,
                "added_chunks": 0,
                "deleted_chunks": 0,
                "removed_files": 0,
                "skipped_files": 0,
                "errors": 0,
            }
            if counters is None
            else counters
        ),
        scope=SyncScope(
            requested_section=None,
            resolved_sections=("knowledge",),
            index_whole_folder=False,
            included_ingestion_documents=False,
        ),
        ingestion=SyncIngestion(source_kind="doc", indexed_generation_id=None),
        indexes=SyncIndexes(chroma="ok", lexical="ok") if indexes is None else indexes,
        errors=[] if errors is None else errors,
    )


def test_json_stdout_is_exactly_one_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _report()
    monkeypatch.setattr(indexer, "sync_report", lambda **_kwargs: report)

    assert indexer.main(["--json"]) == EXIT_OK
    captured = capsys.readouterr()

    assert json.loads(captured.out)["status"] == "succeeded"
    assert captured.out == report.model_dump_json(indent=2) + "\n"
    assert captured.out.count("\n") == report.model_dump_json(indent=2).count("\n") + 1


def test_json_search_is_refused_before_search(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        indexer,
        "search",
        lambda *_args, **_kwargs: pytest.fail("JSON search must be refused"),
    )

    assert indexer.main(["--json", "--search", "x"]) == EXIT_INVALID_INPUT
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "failed"
    assert payload["errors"][0]["code"] == "invalid_arguments"


def test_unknown_section_is_rejected_before_index_mutation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(indexer, "INDEX_WHOLE_FOLDER", False)
    monkeypatch.setattr(indexer, "INCLUDED_SECTIONS", frozenset({"knowledge"}))
    monkeypatch.setattr(
        indexer,
        "ensure_index_location",
        lambda *_args: pytest.fail("invalid section must not open or migrate an index"),
    )

    assert indexer.main(["unknown", "--json"]) == EXIT_INVALID_INPUT
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "failed"
    assert payload["changed"] is False
    assert payload["errors"][0]["code"] == "invalid_section"


def test_chroma_lock_contention_is_locked_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class RefusedLock:
        def __enter__(self) -> None:
            raise CortexWriteLockedError("busy")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(indexer, "INDEX_WHOLE_FOLDER", False)
    monkeypatch.setattr(indexer, "INCLUDED_SECTIONS", frozenset({"knowledge"}))
    monkeypatch.setattr(indexer, "ensure_index_location", lambda *_args: None)
    monkeypatch.setattr(indexer, "chroma_write_lock", RefusedLock)
    monkeypatch.setattr(
        indexer,
        "get_client",
        lambda: pytest.fail("lock contention must stop before index mutation"),
    )

    assert indexer.main(["knowledge", "--json"]) == EXIT_LOCKED
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "locked"
    assert payload["changed"] is False
    assert payload["errors"][0]["code"] == "lock_unavailable"


def test_unexpected_exception_is_failed_without_traceback_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_sync(**_kwargs: object) -> SyncReport:
        raise RuntimeError("boom")

    monkeypatch.setattr(indexer, "sync_report", fail_sync)

    assert indexer.main(["--json"]) == EXIT_ERROR
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["status"] == "failed"
    assert payload["errors"][0]["code"] == "unexpected_error"
    assert "Traceback" not in captured.out
    assert "RuntimeError" not in captured.out


def test_no_change_sync_is_successful(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(indexer, "sync_report", lambda **_kwargs: _report())

    assert indexer.main(["--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "succeeded"
    assert payload["changed"] is False


def test_lexical_preparation_failure_after_chroma_success_is_partial(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = SyncError(
        code="lexical_preparation_failed",
        phase="prepare_lexical",
        path="lexical.db",
    )
    report = _report(
        counters={
            "published_files": 1,
            "added_chunks": 2,
            "deleted_chunks": 0,
            "removed_files": 0,
            "skipped_files": 0,
            "errors": 1,
        },
        indexes=SyncIndexes(chroma="ok", lexical="failed"),
        errors=[error],
    )
    monkeypatch.setattr(indexer, "sync_report", lambda **_kwargs: report)

    assert indexer.main(["--json"]) == EXIT_ERROR
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "partial"
    assert payload["indexes"] == {"chroma": "ok", "lexical": "failed"}
    assert payload["recommendation"] == "repair_lexical"


def test_error_samples_are_truncated_without_truncating_exact_counter() -> None:
    errors = [
        SyncError(code="extraction_failed", phase="extract", path=str(index))
        for index in range(51)
    ]
    report = _report(
        counters={
            "published_files": 0,
            "added_chunks": 0,
            "deleted_chunks": 0,
            "removed_files": 0,
            "skipped_files": 0,
            "errors": len(errors),
        },
        indexes=SyncIndexes(chroma="failed", lexical="ok"),
        errors=errors,
    )

    assert len(report.errors) == 50
    assert report.errors_truncated is True
    assert report.counters.errors == 51


def test_human_sync_keeps_stdout_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str | None, bool]] = []

    def successful_sync(section: str | None, verbose: bool) -> dict[str, int]:
        calls.append((section, verbose))
        return _report().counters.to_stats()

    monkeypatch.setattr(indexer, "sync", successful_sync)

    assert indexer.main([]) == EXIT_OK
    captured = capsys.readouterr()

    assert captured.out == ""
    assert calls == [(None, True)]


@pytest.mark.parametrize(
    ("error_factory", "expected_code", "expected_error"),
    [
        pytest.param(
            lambda: CortexConfigError("bad config"),
            EXIT_INVALID_INPUT,
            "invalid_configuration",
            id="cortex-config",
        ),
        pytest.param(
            lambda: IngestionConfigError("bad ingestion config"),
            EXIT_INVALID_INPUT,
            "invalid_configuration",
            id="ingestion-config",
        ),
        pytest.param(
            lambda: EmbeddingFingerprintMismatchError(
                {"embedding_model": "runtime"},
                {"embedding_model": "stored"},
            ),
            EXIT_INVALID_INPUT,
            "incompatible_index",
            id="embedding-fingerprint",
        ),
        pytest.param(
            lambda: IngestionLockedError("busy"),
            EXIT_LOCKED,
            "lock_unavailable",
            id="ingestion-lock",
        ),
        pytest.param(
            lambda: IngestionStorageError("bad generation"),
            EXIT_ERROR,
            "inconsistent_generation",
            id="ingestion-storage",
        ),
    ],
)
def test_json_exception_funnel_maps_known_failures(
    error_factory: Callable[[], Exception],
    expected_code: int,
    expected_error: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_sync(**_kwargs: object) -> SyncReport:
        raise error_factory()

    monkeypatch.setattr(indexer, "sync_report", fail_sync)

    assert indexer.main(["--json"]) == expected_code
    payload = json.loads(capsys.readouterr().out)

    assert payload["errors"][0]["code"] == expected_error
    assert payload["changed"] is False


def test_mcp_sync_survives_ingestion_lock_contention(monkeypatch: pytest.MonkeyPatch) -> None:
    import server

    monkeypatch.setattr(server, "_resolve_section", lambda section: (section, None))

    def locked_sync(*_args: object, **_kwargs: object) -> dict[str, int]:
        raise IngestionLockedError("busy")

    monkeypatch.setattr(server, "sync", locked_sync)

    assert "Cortex sync locked" in server.cortex_sync()
