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
"""Guided end-to-end Cortex setup: init config, register clients, build the index.

`run_setup` is the non-interactive orchestration behind the `cortex setup`
command: it initializes the per-user config, registers the MCP clients, then
builds the search index (optional). Keeping the logic here as a pure function over a
`SetupPlan` - with injectable steps - makes the whole flow unit testable without
loading the vector store or simulating prompts; the CLI layer only builds the
plan and renders the result.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from setup_config import (
    ClientConfigError,
    ClientResult,
    ResetResult,
    detect_python,
    init_user_config,
    register_clients,
    reset_user_state,
)
from user_config import CortexConfigError

__all__ = ["SetupPlan", "SetupResult", "run_setup", "main"]


@dataclass(frozen=True)
class SetupPlan:
    """Fully-resolved choices for one `cortex setup` run.

    Attributes:
        clients: Client selection passed to register_clients ("all", "none", a
            comma-separated list, or None for detected clients).
        build_index: Whether to build the search index during setup.
        assume_yes: Non-interactive mode; init requires CORTEX_KB_PATH instead of
            prompting.
        reset: Delete the existing user config and generated data before init.
        python_exe: Interpreter recorded in client configs; None uses the current
            interpreter.
    """

    clients: str | None = "all"
    build_index: bool = True
    assume_yes: bool = False
    reset: bool = False
    python_exe: str | None = None


@dataclass(frozen=True)
class SetupResult:
    """Outcome of `run_setup`, for rendering a summary.

    Attributes:
        config_created: Whether a new per-user config was created.
        indexed: Whether the search index was built.
        index_error: Index failure details, or None when built or intentionally skipped.
        client_results: Per-client registration outcomes.
        warnings: Non-fatal messages (one per non-successful client).
        reset: Whether an explicit reset ran before initialization.
    """

    config_created: bool
    indexed: bool
    index_error: str | None
    client_results: list[ClientResult]
    warnings: list[str] = field(default_factory=list)
    reset: bool = False

    @property
    def successful(self) -> bool:
        return all(result.successful for result in self.client_results)


InitFn = Callable[..., bool]
IndexFn = Callable[[], dict[str, int]]
RegisterFn = Callable[..., list[ClientResult]]
ResetFn = Callable[[], ResetResult]


def _default_index() -> dict[str, int]:
    # Lazy import: callers that skip indexing never load chromadb/fastembed.
    from indexer import sync

    return sync(section=None, verbose=True)


def run_setup(
    plan: SetupPlan,
    *,
    init_fn: InitFn = init_user_config,
    index_fn: IndexFn = _default_index,
    register_fn: RegisterFn = register_clients,
    reset_fn: ResetFn = reset_user_state,
) -> SetupResult:
    """Run the full setup sequence for `plan` and return a summary.

    Steps run in order: reset when explicitly requested, initialize the per-user
    config, register the selected MCP clients, then build the index when requested.
    Index failures are deferred so they never roll back successful registration.
    Client registration failures are captured as warnings rather than aborting an
    otherwise successful setup, matching the guided-setup contract.

    Args:
        plan: The resolved setup choices.
        init_fn: Config initializer; defaults to the real init_user_config.
        index_fn: Index builder; defaults to a full incremental sync.
        register_fn: Client registrar; defaults to the real register_clients.
        reset_fn: Guarded user-state reset; defaults to reset_user_state.

    Returns:
        A SetupResult describing everything that was done.
    """
    if plan.reset:
        reset_fn()
    config_created = init_fn(assume_yes=plan.assume_yes)

    python_exe = plan.python_exe or detect_python()
    client_results = register_fn(python_exe, clients=plan.clients)
    warnings = [
        f"client {result.client}: {result.message}"
        for result in client_results
        if not result.successful
    ]

    indexed = False
    index_error: str | None = None
    if plan.build_index:
        try:
            index_fn()
            indexed = True
        except Exception as exc:  # noqa: BLE001 -- registration must remain usable.
            index_error = f"{type(exc).__name__}: {exc}"

    return SetupResult(
        config_created=config_created,
        indexed=indexed,
        index_error=index_error,
        client_results=client_results,
        warnings=warnings,
        reset=plan.reset,
    )


def _render_result(result: SetupResult) -> None:
    print("\n=== Cortex setup ===")
    if result.reset:
        print("[OK] previous config and generated index reset")
    config_label = "OK" if result.config_created else "INFO"
    config_state = "created" if result.config_created else "already present"
    print(f"[{config_label}] config {config_state}")
    if result.indexed:
        print("[OK] index built")
    elif result.index_error is not None:
        print(
            f"[WARN] index deferred: {result.index_error}. "
            "Run `cortex sync` when the model is available."
        )
    else:
        print("[SKIP] index skipped (--no-index)")
    for result_item in result.client_results:
        label = result_item.status if result_item.status != "SKIP" else "SKIP not installed"
        print(f"[{label}] {result_item.client}: {result_item.message}")
    if result.successful:
        print("=== Setup complete. Restart the registered clients. ===")
    else:
        print("=== Setup finished with client warnings (see above). ===")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse flags, run the guided setup, and return a process exit code."""
    parser = argparse.ArgumentParser(description="Cortex guided setup")
    parser.add_argument(
        "--clients",
        default="all",
        help="all, none, or a comma-separated list (default: all)",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip building the search index",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive: no prompts; requires CORTEX_KB_PATH to create config",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing Cortex config and generated index before setup",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="Python executable (default: current interpreter)",
    )
    args = parser.parse_args(argv)
    plan = SetupPlan(
        clients=args.clients,
        build_index=not args.no_index,
        assume_yes=args.yes,
        reset=args.reset,
        python_exe=args.python,
    )
    try:
        result = run_setup(plan)
    except (ClientConfigError, CortexConfigError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    _render_result(result)
    return 0 if result.successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
