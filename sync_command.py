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
"""Command line of `cortex sync`, importable without the index or the configuration.

The indexer that runs the command loads the user configuration when it is
imported, so its parser could not be reached on a machine without one. The
desktop client builds this line, and the interoperability proof parses what the
client builds; both need the parser alone.
"""

from __future__ import annotations

import argparse

from search_command import DEFAULT_TOP_K


def build_parser(prog: str = "cortex sync") -> argparse.ArgumentParser:
    """Build the sync command line, including its deprecated search alias."""
    parser = argparse.ArgumentParser(prog=prog, description="Cortex indexer")
    parser.add_argument(
        "section", nargs="?", default=None, help="Section to sync (default: all)"
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        default=None,
        help="Deprecated alias of `cortex search QUERY`: search instead of syncing",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Number of results for --search (default: {DEFAULT_TOP_K})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the machine-readable sync report on stdout (Companion contract)",
    )
    return parser


__all__ = ["build_parser"]
