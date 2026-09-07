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
"""Parse a complete `cortex` command line with the parsers that run it, without running it.

A desktop client builds its command lines from string literals. The JSON documents
that come back are proved against the client's parsers, but the lines themselves were
not proved against anything: renaming a subcommand, moving a parent option or dropping
a required flag stayed green on both sides and broke the desktop at run time. This
module gives the interoperability proof, and the tests here, the real parsers of the
commands a client may build, importable on a machine that has no Cortex configuration.

Only the commands with a machine contract are exposed. The others are still accepted
by the root parser, and asking for one of them is reported as unsupported rather than
as a parse failure, so the two cannot be confused.
"""

from __future__ import annotations

import argparse
import contextlib
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from cli import build_parser as build_root_parser

_EXIT_OK = 0


@dataclass(frozen=True)
class Invocation:
    """One accepted command line: the root command, and what its own parser made of the rest."""

    command: str | None
    namespace: argparse.Namespace
    output: str = ""


class UnsupportedInvocationError(ValueError):
    """The root parser accepts this command, but it has no machine parser to expose."""


def _sync_parser() -> argparse.ArgumentParser:
    from sync_command import build_parser

    return build_parser("cortex sync")


def _search_parser() -> argparse.ArgumentParser:
    from search_command import build_parser

    return build_parser("cortex search")


def _ingestion_parser() -> argparse.ArgumentParser:
    from ingestion.cli import build_parser

    return build_parser()


def _confluence_parser() -> argparse.ArgumentParser:
    from confluence_writer.cli import build_parser

    return build_parser()


def _config_parser() -> argparse.ArgumentParser:
    from config_command import build_parser

    return build_parser()


# The commands a desktop client builds, each with the parser that actually runs it.
_MACHINE_PARSERS: dict[str, Callable[[], argparse.ArgumentParser]] = {
    "sync": _sync_parser,
    "search": _search_parser,
    "ingestion": _ingestion_parser,
    "confluence": _confluence_parser,
    "config": _config_parser,
}


def machine_commands() -> tuple[str, ...]:
    """Return the commands whose lines can be parsed here."""
    return tuple(_MACHINE_PARSERS)


def parse_invocation(arguments: Sequence[str]) -> Invocation:
    """Parse `arguments` exactly as `cortex` would, and stop before anything runs.

    A usage error raises `SystemExit` with the parser's own status, as it would
    at the console. An informational line such as `--version` returns an
    invocation without a command, carrying what the parser printed.
    """
    argv = list(arguments)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        try:
            root, remainder = build_root_parser().parse_known_args(argv)
        except SystemExit as exc:
            if exc.code == _EXIT_OK:
                return Invocation(None, argparse.Namespace(), captured.getvalue().strip())
            raise
    command = str(root.command)
    try:
        build_parser = _MACHINE_PARSERS[command]
    except KeyError:
        raise UnsupportedInvocationError(
            f"cortex {command} has no machine parser to check a command line against"
        ) from None
    return Invocation(command, build_parser().parse_args(remainder))


__all__ = [
    "Invocation",
    "UnsupportedInvocationError",
    "machine_commands",
    "parse_invocation",
]
