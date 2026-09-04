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
"""Machine-only CLI for reading and mutating the Cortex user configuration."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from config_contract import (
    ConfigError,
    ConfigErrorCode,
    ConfigGetReport,
    ConfigSetReport,
    ConfigValues,
)
from confluence_writer.constants import (
    EXIT_CONFLICT,
    EXIT_ERROR,
    EXIT_INVALID_INPUT,
    EXIT_LOCKED,
    EXIT_OK,
)
from user_config import CortexUserConfig, user_config_path
from user_config_mutation import (
    UserConfigConflictError,
    UserConfigLockedError,
    UserConfigMutationError,
    UserConfigSnapshot,
    UserConfigValidationError,
    read_user_config_snapshot,
    write_user_config_cas,
)


def _values(config: CortexUserConfig) -> ConfigValues:
    return ConfigValues(
        schema_version=config.schema_version,
        kb_path=config.kb_path,
        chroma_path=config.chroma_path,
        index_whole_folder=config.index_whole_folder,
        included_sections=tuple(sorted(config.included_sections)),
        excluded_dirs=tuple(sorted(config.excluded_dirs)),
        exclude_files=tuple(sorted(config.exclude_files)),
        max_markdown_file_size_bytes=config.max_markdown_file_size_bytes,
        max_pdf_size_bytes=config.max_pdf_size_bytes,
        write_lock_path=config.write_lock_path,
        write_lock_timeout_seconds=config.write_lock_timeout_seconds,
    )


def _error(code: ConfigErrorCode, phase: str) -> ConfigError:
    return ConfigError(code=code, phase=phase, path=None)


def _write_report(report: ConfigGetReport | ConfigSetReport) -> None:
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")


def _get(environ: Mapping[str, str]) -> int:
    target = user_config_path(environ)
    try:
        snapshot = read_user_config_snapshot(target, environ=environ)
    except OSError:
        report = ConfigGetReport(
            present=target.exists(),
            content_hash=None,
            valid=False,
            error=_error("invalid_configuration", "validate"),
            values=None,
        )
    else:
        valid = snapshot.config is not None
        report = ConfigGetReport(
            present=snapshot.present,
            content_hash=snapshot.content_hash,
            valid=valid,
            error=None if valid else _error("invalid_configuration", "validate"),
            values=_values(snapshot.config) if snapshot.config is not None else None,
        )
    _write_report(report)
    return EXIT_OK


def _set_failure(
    *,
    status: str,
    code: ConfigErrorCode,
    phase: str,
    snapshot: UserConfigSnapshot | None = None,
) -> ConfigSetReport:
    content_hash = snapshot.content_hash if snapshot is not None else None
    return ConfigSetReport(
        status=status,
        changed=False,
        previous_content_hash=content_hash,
        content_hash=content_hash,
        backup_written=False,
        rebuilt_from_defaults=False,
        restart_required=False,
        reindex_required=False,
        error=_error(code, phase),
    )


def _safe_snapshot(
    environ: Mapping[str, str],
) -> UserConfigSnapshot | None:
    try:
        return read_user_config_snapshot(user_config_path(environ), environ=environ)
    except OSError:
        return None


def _set(
    namespace: argparse.Namespace,
    environ: Mapping[str, str],
) -> int:
    has_hash = namespace.expected_hash is not None
    if namespace.expect_absent == has_hash or not namespace.kb_path.strip():
        _write_report(
            _set_failure(
                status="failed",
                code="invalid_argument",
                phase="validate",
            )
        )
        return EXIT_INVALID_INPUT
    expected_hash = None if namespace.expect_absent else namespace.expected_hash
    target = user_config_path(environ)
    try:
        result = write_user_config_cas(
            target,
            kb_path=namespace.kb_path,
            expected_hash=expected_hash,
            environ=environ,
        )
    except ValueError:
        report = _set_failure(
            status="failed",
            code="invalid_argument",
            phase="validate",
        )
        exit_code = EXIT_INVALID_INPUT
    except UserConfigConflictError:
        report = _set_failure(
            status="conflict",
            code="hash_mismatch",
            phase="compare",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_CONFLICT
    except UserConfigLockedError:
        report = _set_failure(
            status="locked",
            code="locked",
            phase="lock",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_LOCKED
    except UserConfigValidationError:
        report = _set_failure(
            status="failed",
            code="validation_failed",
            phase="validate",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_ERROR
    except (OSError, UserConfigMutationError):
        report = _set_failure(
            status="failed",
            code="write_failed",
            phase="write",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_ERROR
    else:
        previous_kb_path = (
            result.previous.config.kb_path if result.previous.config is not None else None
        )
        current_kb_path = (
            result.current.config.kb_path if result.current.config is not None else None
        )
        reindex_required = result.rebuilt_from_defaults or (
            result.changed and previous_kb_path != current_kb_path
        )
        report = ConfigSetReport(
            status="succeeded" if result.changed else "unchanged",
            changed=result.changed,
            previous_content_hash=result.previous.content_hash,
            content_hash=result.current.content_hash,
            backup_written=result.backup_written,
            rebuilt_from_defaults=result.rebuilt_from_defaults,
            restart_required=result.changed,
            reindex_required=reindex_required,
            error=None,
        )
        exit_code = EXIT_OK
    _write_report(report)
    return exit_code


# The machine commands have no human rendering, so the mandatory flag says so
# instead of leaving argparse's bare 'required' error as the only hint.
_JSON_HELP = (
    "Required: emit the machine-readable JSON contract; this command has no "
    "human output."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cortex config",
        description="Read or change the per-user configuration through the atomic "
        "JSON contract used by Cortex Companion.",
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    get_parser = subparsers.add_parser("get", help="Print the configuration and its hash")
    get_parser.add_argument("--json", action="store_true", required=True, help=_JSON_HELP)
    set_parser = subparsers.add_parser(
        "set",
        help="Change the knowledge-base folder with compare-and-swap protection",
    )
    set_parser.add_argument("--json", action="store_true", required=True, help=_JSON_HELP)
    set_parser.add_argument(
        "--expected-hash",
        help="Hash returned by `get`; the write is refused when the file changed",
    )
    set_parser.add_argument(
        "--expect-absent",
        action="store_true",
        help="Require that no configuration file exists yet (first write)",
    )
    set_parser.add_argument(
        "--kb-path",
        required=True,
        help="Absolute path of the knowledge-base folder to record",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Read or mutate the user configuration through a versioned JSON contract."""
    namespace = _parser().parse_args(argv)
    values = os.environ if environ is None else environ
    if namespace.operation == "get":
        return _get(values)
    return _set(namespace, values)


if __name__ == "__main__":
    raise SystemExit(main())
