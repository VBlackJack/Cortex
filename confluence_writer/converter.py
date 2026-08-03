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
    """Complete validated console result for one generation invocation."""

    converted: tuple[ConvertedPage, ...]
    failed: tuple[FailedPage, ...]


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
    try:
        completed = subprocess.run(
            [str(console_path), str(working_directory)],
            check=False,
            capture_output=True,
            text=False,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConverterContractError("Confluence conversion console could not run.") from exc
    _LOG.info("confluence_converter_finished exit_code=%d", completed.returncode)
    return completed.returncode


class ConsoleConverter:
    """Invoke the console once and consume only validated converted-page outputs."""

    def __init__(self, console_path: Path, *, runner: Runner | None = None) -> None:
        """Bind a configurable executable path and optional test runner."""
        self._console_path = Path(console_path)
        self._runner = _default_runner if runner is None else runner

    def convert(
        self,
        working_directory: Path,
        job: dict[str, object],
        *,
        requested_page_ids: frozenset[str],
    ) -> ConversionBatch:
        """Validate job and result against exact vendored schemas."""
        _validate(job, schema_name="job.schema.json", expected_hash=JOB_SCHEMA_SHA256)
        job_path = working_directory / "job.json"
        job_path.write_text(
            json.dumps(job, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        exit_code = self._runner(self._console_path, working_directory)
        if exit_code not in _ACCEPTED_EXIT_CODES:
            raise ConverterContractError(
                f"Confluence conversion console failed globally with exit code {exit_code}."
            )
        result_path = working_directory / "result.json"
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConverterContractError(
                "Conversion result.json is unavailable or invalid."
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
    "Runner",
]
