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
from pathlib import Path

from config_contract import (
    ConfigError,
    ConfigErrorCode,
    ConfigGetReport,
    ConfigRootMutationReport,
    ConfigRootsReport,
    ConfigSetReport,
    ConfigValues,
    SectionRootEntry,
)
from confluence_writer.constants import (
    EXIT_CONFLICT,
    EXIT_ERROR,
    EXIT_INVALID_INPUT,
    EXIT_LOCKED,
    EXIT_OK,
)
from index_contract import ROOT_SECTION
from section_roots import locate_section
from user_config import CortexUserConfig, user_config_path
from user_config_mutation import (
    UserConfigConflictError,
    UserConfigInvalidBaseError,
    UserConfigLockedError,
    UserConfigMutationError,
    UserConfigMutationResult,
    UserConfigSnapshot,
    UserConfigValidationError,
    read_user_config_snapshot,
    write_section_root_cas,
    write_user_config_cas,
)

_OPERATION_GET = "get"
_OPERATION_SET = "set"
_OPERATION_ROOTS = "roots"
_OPERATION_SET_ROOT = "set-root"
_OPERATION_CLEAR_ROOT = "clear-root"
_ROOT_OPERATION_NAMES = {
    _OPERATION_SET_ROOT: "config_set_root",
    _OPERATION_CLEAR_ROOT: "config_clear_root",
}


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


def _write_report(
    report: ConfigGetReport | ConfigSetReport | ConfigRootsReport | ConfigRootMutationReport,
) -> None:
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


def _section_entries(config: CortexUserConfig) -> tuple[SectionRootEntry, ...]:
    names = (
        [ROOT_SECTION] if config.index_whole_folder else sorted(config.included_sections)
    )
    entries = []
    for name in names:
        mount = config.section_roots.get(name)
        if mount is None and not config.kb_path:
            entries.append(SectionRootEntry(section=name, root=None, mounted=False, exists=False))
            continue
        location = locate_section(Path(config.kb_path or ""), name, config.section_roots)
        entries.append(
            SectionRootEntry(
                section=name,
                root=str(location.directory),
                mounted=location.mounted,
                exists=location.directory.is_dir(),
            )
        )
    return tuple(entries)


def _roots(environ: Mapping[str, str]) -> int:
    target = user_config_path(environ)
    try:
        snapshot = read_user_config_snapshot(target, environ=environ)
    except OSError:
        snapshot = None
    config = snapshot.config if snapshot is not None else None
    report = ConfigRootsReport(
        present=snapshot.present if snapshot is not None else target.exists(),
        content_hash=snapshot.content_hash if snapshot is not None else None,
        valid=config is not None,
        error=None if config is not None else _error("invalid_configuration", "validate"),
        kb_path=config.kb_path if config is not None else None,
        index_whole_folder=config.index_whole_folder if config is not None else None,
        sections=_section_entries(config) if config is not None else (),
    )
    _write_report(report)
    return EXIT_OK


def _root_failure(
    namespace: argparse.Namespace,
    *,
    status: str,
    code: ConfigErrorCode,
    phase: str,
    snapshot: UserConfigSnapshot | None = None,
) -> ConfigRootMutationReport:
    content_hash = snapshot.content_hash if snapshot is not None else None
    return ConfigRootMutationReport(
        operation=_ROOT_OPERATION_NAMES[namespace.operation],
        status=status,
        section=namespace.section,
        root=None,
        changed=False,
        previous_content_hash=content_hash,
        content_hash=content_hash,
        backup_written=False,
        restart_required=False,
        error=_error(code, phase),
    )


def _root_success(
    namespace: argparse.Namespace, result: UserConfigMutationResult
) -> ConfigRootMutationReport:
    current = result.current.config
    root = current.section_roots.get(namespace.section) if current is not None else None
    return ConfigRootMutationReport(
        operation=_ROOT_OPERATION_NAMES[namespace.operation],
        status="succeeded" if result.changed else "unchanged",
        section=namespace.section,
        root=root,
        changed=result.changed,
        previous_content_hash=result.previous.content_hash,
        content_hash=result.current.content_hash,
        backup_written=result.backup_written,
        restart_required=result.changed,
        error=None,
    )


def _mutate_root(namespace: argparse.Namespace, environ: Mapping[str, str]) -> int:
    clearing = namespace.operation == _OPERATION_CLEAR_ROOT
    requested_root = None if clearing else namespace.root
    blank_root = requested_root is not None and not requested_root.strip()
    if not namespace.section.strip() or blank_root:
        _write_report(
            _root_failure(namespace, status="failed", code="invalid_argument", phase="validate")
        )
        return EXIT_INVALID_INPUT
    try:
        result = write_section_root_cas(
            user_config_path(environ),
            section=namespace.section,
            root=requested_root,
            expected_hash=namespace.expected_hash,
            environ=environ,
        )
    except ValueError:
        report = _root_failure(
            namespace, status="failed", code="invalid_argument", phase="validate"
        )
        exit_code = EXIT_INVALID_INPUT
    except UserConfigConflictError:
        report = _root_failure(
            namespace,
            status="conflict",
            code="hash_mismatch",
            phase="compare",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_CONFLICT
    except UserConfigLockedError:
        report = _root_failure(
            namespace,
            status="locked",
            code="locked",
            phase="lock",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_LOCKED
    except UserConfigInvalidBaseError:
        report = _root_failure(
            namespace,
            status="failed",
            code="invalid_configuration",
            phase="validate",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_ERROR
    except UserConfigValidationError:
        report = _root_failure(
            namespace,
            status="failed",
            code="validation_failed",
            phase="validate",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_ERROR
    except (OSError, UserConfigMutationError):
        report = _root_failure(
            namespace,
            status="failed",
            code="write_failed",
            phase="write",
            snapshot=_safe_snapshot(environ),
        )
        exit_code = EXIT_ERROR
    else:
        report = _root_success(namespace, result)
        exit_code = EXIT_OK
    _write_report(report)
    return exit_code


# The machine commands have no human rendering, so the mandatory flag says so
# instead of leaving argparse's bare 'required' error as the only hint.
_JSON_HELP = (
    "Required: emit the machine-readable JSON contract; this command has no "
    "human output."
)


def build_parser() -> argparse.ArgumentParser:
    """Build the configuration command line the desktop client and the proofs share."""
    parser = argparse.ArgumentParser(
        prog="cortex config",
        description="Read or change the per-user configuration through the atomic "
        "JSON contract used by Cortex Companion.",
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    get_parser = subparsers.add_parser(
        _OPERATION_GET, help="Print the configuration and its hash"
    )
    get_parser.add_argument("--json", action="store_true", required=True, help=_JSON_HELP)
    set_parser = subparsers.add_parser(
        _OPERATION_SET,
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
    roots_parser = subparsers.add_parser(
        _OPERATION_ROOTS,
        help="List each section with its resolved folder, mount and presence on disk",
    )
    roots_parser.add_argument("--json", action="store_true", required=True, help=_JSON_HELP)
    set_root_parser = subparsers.add_parser(
        _OPERATION_SET_ROOT,
        help="Mount one included section on a folder outside the knowledge base",
    )
    set_root_parser.add_argument("section", help="Name of a section in included_sections")
    set_root_parser.add_argument("root", help="Absolute path of the folder that holds it")
    clear_root_parser = subparsers.add_parser(
        _OPERATION_CLEAR_ROOT,
        help="Return one section to its folder under the knowledge base",
    )
    clear_root_parser.add_argument("section", help="Name of the mounted section")
    for mutation_parser in (set_root_parser, clear_root_parser):
        mutation_parser.add_argument(
            "--json", action="store_true", required=True, help=_JSON_HELP
        )
        mutation_parser.add_argument(
            "--expected-hash",
            required=True,
            help="Hash returned by `get` or `roots`; the write is refused when the file changed",
        )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Read or mutate the user configuration through a versioned JSON contract."""
    namespace = build_parser().parse_args(argv)
    values = os.environ if environ is None else environ
    if namespace.operation == _OPERATION_GET:
        return _get(values)
    if namespace.operation == _OPERATION_ROOTS:
        return _roots(values)
    if namespace.operation in _ROOT_OPERATION_NAMES:
        return _mutate_root(namespace, values)
    return _set(namespace, values)


if __name__ == "__main__":
    raise SystemExit(main())
