# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Thin console dispatcher for existing Cortex command entry points."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from _version import __version__

_COMMANDS = ("sync", "doctor", "init", "register", "check")


def _run_setup(arguments: list[str]) -> int:
    from setup_config import main as setup_main

    try:
        setup_main(arguments)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a Cortex subcommand without duplicating domain logic."""
    parser = argparse.ArgumentParser(prog="cortex")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in _COMMANDS:
        subparsers.add_parser(name, add_help=False)
    namespace, arguments = parser.parse_known_args(argv)

    if namespace.command == "sync":
        from indexer import main as sync_main

        return sync_main(arguments)
    if namespace.command == "doctor":
        from doctor import main as doctor_main

        return doctor_main(arguments)
    setup_flags = {
        "init": ["--init"],
        "register": [],
        "check": ["--check"],
    }
    return _run_setup([*setup_flags[namespace.command], *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
