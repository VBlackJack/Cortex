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
"""Frozen-schema bridge to the extracted ConfluenceRAGBuilder console."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from confluence_writer.constants import JOB_SCHEMA_SHA256, RESULT_SCHEMA_SHA256

_LOG = logging.getLogger("cortex.confluence_writer.converter")
_ACCEPTED_EXIT_CODES = {0, 2}
_PROBE_ARGUMENT = "--probe"
_PROBE_TIMEOUT_SECONDS = 5
_SUPPORTED_SCHEMA_VERSION = 1
_RESOURCES = Path(__file__).parent / "resources"


class ConverterContractError(RuntimeError):
    """Raised when frozen schemas, console results, or output paths diverge."""


@dataclass(frozen=True)
class ConvertedPage:
    """Validated Markdown and console artifacts for one converted page."""

    page_id: str
    markdown: str
    artifacts: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class FailedPage:
    """Validated per-page console failure."""

    page_id: str
    error_code: str


@dataclass(frozen=True)
class ConversionBatch:
    """Complete validated console result for one job invocation."""

    converted: tuple[ConvertedPage, ...]
    failed: tuple[FailedPage, ...]


@dataclass(frozen=True)
class JobLimits:
    """Frozen job-schema limits used to plan console invocations."""

    maximum_pages: int
    maximum_bytes: int


@dataclass(frozen=True)
class JobPlan:
    """Stable page batches plus pages that cannot fit in a job alone."""

    batches: tuple[tuple[dict[str, object], ...], ...]
    oversized_page_ids: tuple[str, ...]


Runner = Callable[[Path, Path], int]


def _load_schema(file_name: str, expected_hash: str) -> dict[str, Any]:
    path = _RESOURCES / file_name
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ConverterContractError(f"Frozen schema '{file_name}' is unavailable.") from exc
    canonical_payload = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    actual_hash = hashlib.sha256(canonical_payload).hexdigest()
    if actual_hash != expected_hash:
        raise ConverterContractError(f"Frozen schema '{file_name}' failed its provenance hash.")
    try:
        value = json.loads(canonical_payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConverterContractError(f"Frozen schema '{file_name}' is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ConverterContractError(f"Frozen schema '{file_name}' must be an object.")
    return cast(dict[str, Any], value)


def _validate(value: object, *, schema_name: str, expected_hash: str) -> None:
    schema = _load_schema(schema_name, expected_hash)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except (SchemaError, ValidationError) as exc:
        raise ConverterContractError(f"Payload does not match frozen {schema_name}.") from exc


def _job_limits(schema: dict[str, Any]) -> JobLimits:
    properties = schema.get("properties")
    pages = properties.get("pages") if isinstance(properties, dict) else None
    maximum_pages = pages.get("maxItems") if isinstance(pages, dict) else None
    maximum_bytes = schema.get("x-maximum-job-bytes")
    if (
        not isinstance(maximum_pages, int)
        or isinstance(maximum_pages, bool)
        or maximum_pages <= 0
        or not isinstance(maximum_bytes, int)
        or isinstance(maximum_bytes, bool)
        or maximum_bytes <= 0
    ):
        raise ConverterContractError("Frozen job schema has invalid batching limits.")
    return JobLimits(maximum_pages=maximum_pages, maximum_bytes=maximum_bytes)


def _serialize_job(job: dict[str, object]) -> bytes:
    return (json.dumps(job, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _contained_file(root: Path, relative_path: str) -> Path:
    candidate = root.joinpath(*relative_path.split("/"))
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise ConverterContractError("Console output path escapes its working directory.")
    if not resolved.is_file():
        raise ConverterContractError("Console output path is not a regular file.")
    return resolved


def _default_runner(console_path: Path, working_directory: Path) -> int:
    _LOG.info(
        "confluence_converter_start path=%s workspace=%s",
        console_path,
        working_directory,
    )
    try:
        completed = subprocess.run(
            [str(console_path), str(working_directory)],
            check=False,
            capture_output=True,
            text=False,
            timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        _LOG.error(
            "confluence_converter_timeout path=%s timeout_seconds=%d",
            console_path,
            1800,
        )
        raise ConverterContractError(
            f"Confluence conversion console timed out at '{console_path}'."
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.error(
            "confluence_converter_launch_failed path=%s error_type=%s",
            console_path,
            type(exc).__name__,
        )
        raise ConverterContractError(
            f"Confluence conversion console could not run at '{console_path}'."
        ) from exc
    _LOG.info(
        "confluence_converter_finished path=%s exit_code=%d",
        console_path,
        completed.returncode,
    )
    return completed.returncode


def _probe_console(console_path: Path) -> None:
    _LOG.info(
        "confluence_converter_selected reason=effective_configuration path=%s",
        console_path,
    )
    try:
        completed = subprocess.run(
            [str(console_path), _PROBE_ARGUMENT],
            check=False,
            capture_output=True,
            text=False,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConverterContractError(
            f"Confluence converter capability probe timed out at '{console_path}'."
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConverterContractError(
            f"Confluence converter is unavailable at '{console_path}'."
        ) from exc
    try:
        payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        payload = None
        parsing_error: Exception | None = exc
    else:
        parsing_error = None
    valid = (
        completed.returncode == 0
        and isinstance(payload, dict)
        and set(payload) == {"tool_version", "schema_version"}
        and isinstance(payload.get("tool_version"), str)
        and bool(payload["tool_version"].strip())
        and payload.get("schema_version") == _SUPPORTED_SCHEMA_VERSION
    )
    if not valid:
        _LOG.error(
            "confluence_converter_probe_refused path=%s exit_code=%d parse_error=%s",
            console_path,
            completed.returncode,
            "none" if parsing_error is None else type(parsing_error).__name__,
        )
        raise ConverterContractError(
            f"The executable at '{console_path}' is not a compatible Confluence console converter."
        )
    _LOG.info(
        "confluence_converter_probe_ok path=%s tool_version=%s schema_version=%d",
        console_path,
        payload["tool_version"],
        payload["schema_version"],
    )


class ConsoleConverter:
    """Plan and invoke validated console jobs, consuming only safe outputs."""

    def __init__(self, console_path: Path, *, runner: Runner | None = None) -> None:
        """Bind a configurable executable path and optional test runner."""
        self._console_path = Path(console_path)
        self._runner = _default_runner if runner is None else runner
        if runner is None:
            _probe_console(self._console_path)
        self._job_limits = _job_limits(_load_schema("job.schema.json", JOB_SCHEMA_SHA256))

    @property
    def job_limits(self) -> JobLimits:
        """Return page-count and serialized-byte limits from the frozen schema."""
        return self._job_limits

    def serialized_job_size(self, job: dict[str, object]) -> int:
        """Return the exact UTF-8 byte count written to job.json."""
        return len(_serialize_job(job))

    def plan_job_pages(self, pages: list[dict[str, object]]) -> JobPlan:
        """Split pages stably so every planned job satisfies frozen size limits."""
        batches: list[tuple[dict[str, object], ...]] = []
        oversized_page_ids: list[str] = []
        current: list[dict[str, object]] = []
        for page in pages:
            single_job = {"schema_version": 1, "pages": [page]}
            if self.serialized_job_size(single_job) > self._job_limits.maximum_bytes:
                oversized_page_ids.append(cast(str, page["page_id"]))
                continue
            if not current:
                current.append(page)
                continue
            candidate = [*current, page]
            candidate_job = {"schema_version": 1, "pages": candidate}
            if (
                len(candidate) > self._job_limits.maximum_pages
                or self.serialized_job_size(candidate_job) > self._job_limits.maximum_bytes
            ):
                batches.append(tuple(current))
                current = [page]
                continue
            current.append(page)
        if current:
            batches.append(tuple(current))
        return JobPlan(
            batches=tuple(batches),
            oversized_page_ids=tuple(oversized_page_ids),
        )

    def convert(
        self,
        working_directory: Path,
        job: dict[str, object],
        *,
        requested_page_ids: frozenset[str],
    ) -> ConversionBatch:
        """Validate job and result against exact vendored schemas."""
        serialized_job = _serialize_job(job)
        if len(serialized_job) > self._job_limits.maximum_bytes:
            raise ConverterContractError("Serialized job exceeds the frozen byte limit.")
        _validate(job, schema_name="job.schema.json", expected_hash=JOB_SCHEMA_SHA256)
        job_path = working_directory / "job.json"
        job_path.write_bytes(serialized_job)
        exit_code = self._runner(self._console_path, working_directory)
        if exit_code not in _ACCEPTED_EXIT_CODES:
            raise ConverterContractError(
                f"Confluence conversion console failed globally with exit code {exit_code}."
            )
        result_path = working_directory / "result.json"
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            _LOG.error(
                "confluence_converter_result_unavailable path=%s error_type=%s",
                result_path,
                type(exc).__name__,
            )
            raise ConverterContractError(
                f"Conversion result.json is unavailable or invalid at '{result_path}'."
            ) from exc
        _validate(
            result,
            schema_name="result.schema.json",
            expected_hash=RESULT_SCHEMA_SHA256,
        )
        if not isinstance(result, dict):
            raise ConverterContractError("Conversion result must be an object.")
        raw_pages = result.get("pages")
        if not isinstance(raw_pages, list):
            raise ConverterContractError("Conversion result pages must be an array.")
        converted: list[ConvertedPage] = []
        failed: list[FailedPage] = []
        returned_ids: set[str] = set()
        for raw in raw_pages:
            if not isinstance(raw, dict):
                raise ConverterContractError("Conversion page result must be an object.")
            page_id = cast(str, raw["page_id"])
            if page_id in returned_ids or page_id not in requested_page_ids:
                raise ConverterContractError(
                    "Conversion result page identities diverged from job.json."
                )
            returned_ids.add(page_id)
            if raw["status"] == "failed":
                failed.append(FailedPage(page_id=page_id, error_code=cast(str, raw["error_code"])))
                continue
            markdown_paths = cast(list[str], raw["markdown_paths"])
            markdown_parts = [
                _contained_file(working_directory, path).read_text(encoding="utf-8")
                for path in markdown_paths
            ]
            attachment_root = working_directory / "_attachments" / page_id
            artifacts: list[tuple[str, bytes]] = []
            if attachment_root.is_dir():
                artifact_files = (
                    candidate for candidate in attachment_root.rglob("*") if candidate.is_file()
                )
                for path in sorted(artifact_files):
                    relative = path.relative_to(working_directory).as_posix()
                    artifacts.append(
                        (relative, _contained_file(working_directory, relative).read_bytes())
                    )
            converted.append(
                ConvertedPage(
                    page_id=page_id,
                    markdown="\n\n".join(part.strip("\n") for part in markdown_parts) + "\n",
                    artifacts=tuple(artifacts),
                )
            )
        missing = requested_page_ids - returned_ids
        if missing:
            raise ConverterContractError("Conversion result omitted one or more requested pages.")
        return ConversionBatch(converted=tuple(converted), failed=tuple(failed))


__all__ = [
    "ConsoleConverter",
    "ConversionBatch",
    "ConvertedPage",
    "ConverterContractError",
    "FailedPage",
    "JobLimits",
    "JobPlan",
    "Runner",
]
