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
"""Thin console dispatcher for existing Cortex command entry points."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from _version import __version__
from confluence_writer.constants import EXIT_INVALID_INPUT
from offline_models import activate_if_embedded
from sync_contract import SyncError, build_sync_failure_report
from user_config import CortexConfigError

activate_if_embedded()

_COMMANDS = (
    "serve",
    "sync",
    "ingestion",
    "confluence",
    "config",
    "doctor",
    "setup",
    "init",
    "register",
    "unregister",
    "check",
)


def _run_setup(arguments: list[str]) -> int:
    from setup_config import main as setup_main

    try:
        setup_main(arguments)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _requested_sync_section(arguments: list[str]) -> str | None:
    """Read the optional section from the canonical sync argument order."""
    if arguments and not arguments[0].startswith("-"):
        return arguments[0]
    return None


def _handle_sync_configuration_error(
    arguments: list[str],
    error: CortexConfigError,
) -> int:
    """Render an import-time configuration failure for the requested output mode."""
    if "--json" not in arguments:
        sys.stderr.write(f"Cortex sync error: {error}\n")
        return EXIT_INVALID_INPUT
    report = build_sync_failure_report(
        requested_section=_requested_sync_section(arguments),
        index_whole_folder=False,
        included_ingestion_documents=False,
        error=SyncError(code="invalid_configuration", phase="validate", path=None),
        status="failed",
        recommendation="none",
    )
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return EXIT_INVALID_INPUT


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a Cortex subcommand without duplicating domain logic."""
    parser = argparse.ArgumentParser(prog="cortex")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in _COMMANDS:
        subparsers.add_parser(name, add_help=False)
    namespace, arguments = parser.parse_known_args(argv)

    if namespace.command == "serve":
        from server import run_stdio

        run_stdio()
        return 0
    if namespace.command == "sync":
        try:
            from indexer import main as sync_main
        except CortexConfigError as exc:
            return _handle_sync_configuration_error(arguments, exc)

        return sync_main(arguments)
    if namespace.command == "ingestion":
        from ingestion.cli import main as ingestion_main

        return ingestion_main(arguments)
    if namespace.command == "confluence":
        from confluence_writer.cli import main as confluence_main

        return confluence_main(arguments)
    if namespace.command == "config":
        from config_command import main as config_main

        return config_main(arguments)
    if namespace.command == "doctor":
        from doctor import main as doctor_main

        return doctor_main(arguments)
    if namespace.command == "setup":
        from setup_wizard import main as setup_wizard_main

        return setup_wizard_main(arguments)
    setup_flags = {
        "init": ["--init"],
        "register": [],
        "unregister": ["--unregister"],
        "check": ["--check"],
    }
    return _run_setup([*setup_flags[namespace.command], *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
