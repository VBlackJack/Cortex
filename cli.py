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
from collections.abc import Sequence

from _version import __version__
from offline_models import activate_if_embedded

activate_if_embedded()

_COMMANDS = (
    "serve",
    "sync",
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
        from indexer import main as sync_main

        return sync_main(arguments)
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
