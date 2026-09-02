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
from typing import TYPE_CHECKING

from _version import __version__
from confluence_writer.constants import EXIT_INVALID_INPUT
from sync_contract import SyncError, build_sync_failure_report

if TYPE_CHECKING:
    from user_config import CortexConfigError

# One line per public subcommand, rendered by `cortex --help`. Keep this table
# and the command table in both READMEs describing the same surface.
_COMMANDS: tuple[tuple[str, str], ...] = (
    ("serve", "Run the MCP server over stdio (started by MCP clients)."),
    ("sync", "Incrementally index the knowledge base and the current generation."),
    ("ingestion", "Report ingestion source health and whether a catch-up is due."),
    ("confluence", "Store the Confluence PAT or run the allowlisted writer."),
    ("bundle", "Describe or verify an encrypted portable archive."),
    ("config", "Read or change the configuration through the atomic JSON contract."),
    ("doctor", "Diagnose the installation without writing anything."),
    ("setup", "Initialize the config, register MCP clients, and build the index."),
    ("init", "Create the per-user configuration only."),
    ("register", "Add Cortex to the detected MCP clients."),
    ("unregister", "Remove Cortex from the detected MCP clients."),
    ("check", "Verify that the installation is usable."),
)


def _run_setup(arguments: list[str], *, prog: str) -> int:
    from setup_config import main as setup_main

    try:
        setup_main(arguments, prog=prog)
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
    parser = argparse.ArgumentParser(
        prog="cortex",
        description="Local multi-client RAG server over the Model Context Protocol.",
        epilog="Run `cortex <command> --help` for the options of one command.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="<command>",
    )
    for name, summary in _COMMANDS:
        subparsers.add_parser(name, add_help=False, help=summary)
    namespace, arguments = parser.parse_known_args(argv)

    if namespace.command == "bundle":
        from bundle_command import main as bundle_main

        return bundle_main(arguments)

    from offline_models import activate_if_embedded

    activate_if_embedded()

    if namespace.command == "serve":
        from server import run_stdio

        run_stdio()
        return 0
    if namespace.command == "sync":
        from user_config import CortexConfigError

        try:
            from indexer import main as sync_main
        except CortexConfigError as exc:
            return _handle_sync_configuration_error(arguments, exc)

        return sync_main(arguments, prog="cortex sync")
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

        return setup_wizard_main(arguments, prog="cortex setup")
    setup_flags = {
        "init": ["--init"],
        "register": [],
        "unregister": ["--unregister"],
        "check": ["--check"],
    }
    return _run_setup(
        [*setup_flags[namespace.command], *arguments],
        prog=f"cortex {namespace.command}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
