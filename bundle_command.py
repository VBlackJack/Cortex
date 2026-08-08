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
"""Machine-only CLI for describing and verifying Cortex portable bundles."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO, TextIO

import fastembed

from bundle_contract import (
    BundleDescribeReport,
    BundleError,
    BundleErrorCode,
    BundleVerifyReport,
)
from bundle_format import BundleFormatError, is_compatible, read_header, verify_bundle
from confluence_writer.constants import (
    EXIT_ERROR,
    EXIT_INTEGRITY,
    EXIT_INVALID_INPUT,
    EXIT_NOT_FOUND,
    EXIT_OK,
)

_EXIT_CODES: dict[BundleErrorCode, int] = {
    "archive_not_found": EXIT_NOT_FOUND,
    "archive_unreadable": EXIT_ERROR,
    "malformed_container": EXIT_INVALID_INPUT,
    "unsupported_container_version": EXIT_INVALID_INPUT,
    "header_field_rejected": EXIT_INVALID_INPUT,
    "kdf_parameters_rejected": EXIT_INVALID_INPUT,
    "password_missing": EXIT_INVALID_INPUT,
    "kdf_unavailable": EXIT_ERROR,
    "authentication_failed": EXIT_INTEGRITY,
    "truncated_archive": EXIT_INTEGRITY,
    "malformed_payload": EXIT_INTEGRITY,
    "malformed_manifest": EXIT_INTEGRITY,
    "unsupported_contract_version": EXIT_INTEGRITY,
    "header_manifest_mismatch": EXIT_INTEGRITY,
    "member_rejected": EXIT_INTEGRITY,
    "member_digest_mismatch": EXIT_INTEGRITY,
}


def _write_report(
    report: BundleDescribeReport | BundleVerifyReport,
    output: TextIO,
) -> None:
    output.write(report.model_dump_json(indent=2) + "\n")


def _failure_error(code: BundleErrorCode, phase: str) -> BundleError:
    return BundleError(code=code, phase=phase, path=None)


def _describe_failure(code: BundleErrorCode, phase: str) -> BundleDescribeReport:
    return BundleDescribeReport(
        status="failed",
        error=_failure_error(code, phase),
        authenticated=None,
        claimed_compatible=None,
        created_at=None,
        cortex_version=None,
        roles_summary=None,
    )


def _verify_failure(error: BundleFormatError) -> BundleVerifyReport:
    return BundleVerifyReport(
        status="failed",
        error=_failure_error(error.code, error.phase),
        authenticated=None,
        compatible=None,
        header_matches_manifest=error.header_matches_manifest,
        members_verified=None,
        roles=None,
    )


def _open_archive(path: Path) -> BinaryIO:
    if not path.is_file():
        raise BundleFormatError("archive_not_found", "open_archive")
    try:
        return path.open("rb")
    except OSError as exc:
        raise BundleFormatError("archive_unreadable", "open_archive") from exc


def _describe(path: Path, output: TextIO) -> int:
    try:
        with _open_archive(path) as stream:
            header, _ = read_header(stream)
    except BundleFormatError as exc:
        _write_report(_describe_failure(exc.code, exc.phase), output)
        return _EXIT_CODES[exc.code]
    except OSError:
        code: BundleErrorCode = "archive_unreadable"
        _write_report(_describe_failure(code, "read_header"), output)
        return _EXIT_CODES[code]
    report = BundleDescribeReport(
        status="succeeded",
        error=None,
        authenticated=False,
        claimed_compatible=is_compatible(
            header.contracts,
            header.embedding_fingerprint,
            fastembed.__version__,
        ),
        created_at=header.created_at,
        cortex_version=header.cortex_version,
        roles_summary=header.roles_summary,
    )
    _write_report(report, output)
    return EXIT_OK


def _read_password(input_stream: TextIO) -> str:
    try:
        line = input_stream.readline()
    except OSError as exc:
        raise BundleFormatError("password_missing", "read_password") from exc
    password = line.removesuffix("\n").removesuffix("\r")
    if not line or not password:
        raise BundleFormatError("password_missing", "read_password")
    return password


def _verify(path: Path, input_stream: TextIO, output: TextIO) -> int:
    try:
        with _open_archive(path) as stream:
            password = _read_password(input_stream)
            verification = verify_bundle(stream, password, fastembed.__version__)
    except BundleFormatError as exc:
        _write_report(_verify_failure(exc), output)
        return _EXIT_CODES[exc.code]
    except OSError:
        error = BundleFormatError("archive_unreadable", "read_archive")
        _write_report(_verify_failure(error), output)
        return _EXIT_CODES[error.code]
    report = BundleVerifyReport(
        status="succeeded",
        error=None,
        authenticated=True,
        compatible=verification.compatible,
        header_matches_manifest=True,
        members_verified=True,
        roles=verification.manifest.roles,
    )
    _write_report(report, output)
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cortex bundle")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    describe = subparsers.add_parser("describe")
    describe.add_argument("archive", type=Path)
    describe.add_argument("--json", action="store_true", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("archive", type=Path)
    verify.add_argument("--json", action="store_true", required=True)
    verify.add_argument("--password-stdin", action="store_true", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output: TextIO | None = None,
) -> int:
    """Describe or authenticate a portable bundle through a versioned JSON contract."""
    namespace = _parser().parse_args(argv)
    effective_input = sys.stdin if input_stream is None else input_stream
    effective_output = sys.stdout if output is None else output
    if namespace.operation == "describe":
        return _describe(namespace.archive, effective_output)
    return _verify(namespace.archive, effective_input, effective_output)


if __name__ == "__main__":
    raise SystemExit(main())
