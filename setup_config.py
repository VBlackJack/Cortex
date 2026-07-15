#!/usr/bin/env python3
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
"""Configure Cortex and register its MCP server with supported AI clients."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

from data_home import (
    CortexDataHomeError,
    DataHomeConflictError,
    ensure_index_location,
    migration_state,
    move_legacy_index,
)
from dependencies import REQUIRED_PACKAGES
from user_config import (
    CortexConfigError,
    load_user_config,
    require_kb_path,
    user_config_path,
    write_user_config_atomic,
)

logger = logging.getLogger("cortex.setup")

SCRIPT_DIR = Path(__file__).parent.resolve()
SERVER_PY = SCRIPT_DIR / "server.py"
CORTEX_CONFIG_PATH = user_config_path()
CLIENT_NAMES = (
    "claude-desktop",
    "claude-code",
    "codex",
    "gemini",
    "cursor",
    "windsurf",
    "vscode",
)
_TABLE_HEADER_RE = re.compile(r"^\s*\[\s*([^\]]+)\s*\]\s*(?:#.*)?$")
_TOML_ASSIGNMENT_RE = re.compile(r"^(\s*)(command|args)(\s*=).*$")


class ClientConfigError(RuntimeError):
    """Raised when a client configuration cannot be changed safely."""


@dataclass(frozen=True)
class ClientTarget:
    """Declarative registration contract for one supported MCP client."""

    name: str
    config_path: Path | None
    config_format: str
    entry: Mapping[str, Any]
    executable: str | None = None


@dataclass(frozen=True)
class ClientResult:
    """One client registration or validation outcome."""

    client: str
    status: str
    message: str
    changed: bool = False

    @property
    def successful(self) -> bool:
        return self.status != "FAIL"


Runner = Callable[..., subprocess.CompletedProcess[str]]


def detect_python() -> str:
    """Return the absolute path of the running Python interpreter."""
    return sys.executable


def build_server_entry(
    *,
    frozen: bool,
    exe_path: str,
    python_exe: str,
    server_py: Path,
) -> dict[str, Any]:
    """Build the MCP command for a frozen binary or a Python installation."""
    if frozen:
        return {
            "command": str(Path(exe_path).resolve()),
            "args": ["serve"],
        }
    return {
        "command": str(Path(python_exe).resolve()),
        "args": [str(server_py)],
    }


def _resolved_entry(python_exe: str) -> dict[str, Any]:
    return build_server_entry(
        frozen=bool(getattr(sys, "frozen", False)),
        exe_path=sys.executable,
        python_exe=python_exe,
        server_py=SERVER_PY,
    )


def client_registry(
    python_exe: str,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, ClientTarget]:
    """Build the supported-client registry for the current user."""
    values = os.environ if environ is None else environ
    configured_home = values.get("HOME") or values.get("USERPROFILE")
    user_home = (
        Path(configured_home) if home is None and configured_home else Path.home()
    )
    if home is not None:
        user_home = Path(home)
    appdata_value = values.get("APPDATA")
    appdata = Path(appdata_value) if appdata_value else user_home / "AppData" / "Roaming"
    entry = _resolved_entry(python_exe)
    claude_entry = {**entry, "timeout": 120000}
    vscode_entry = {"type": "stdio", **entry}
    claude_cli = which("claude")

    return {
        "claude-desktop": ClientTarget(
            name="claude-desktop",
            config_path=appdata / "Claude" / "claude_desktop_config.json",
            config_format="json",
            entry=claude_entry,
        ),
        "claude-code": ClientTarget(
            name="claude-code",
            config_path=None,
            config_format="claude-cli-user-scope",
            entry=entry,
            executable=claude_cli,
        ),
        "codex": ClientTarget(
            name="codex",
            config_path=user_home / ".codex" / "config.toml",
            config_format="toml-table:mcp_servers.cortex",
            entry=entry,
            executable=which("codex"),
        ),
        "gemini": ClientTarget(
            name="gemini",
            config_path=user_home / ".gemini" / "settings.json",
            config_format="json",
            entry=entry,
            executable=which("gemini"),
        ),
        "cursor": ClientTarget(
            name="cursor",
            config_path=user_home / ".cursor" / "mcp.json",
            config_format="json",
            entry=entry,
            executable=which("cursor"),
        ),
        "windsurf": ClientTarget(
            name="windsurf",
            config_path=user_home / ".codeium" / "windsurf" / "mcp_config.json",
            config_format="json",
            entry=entry,
            executable=which("windsurf"),
        ),
        "vscode": ClientTarget(
            name="vscode",
            config_path=appdata / "Code" / "User" / "mcp.json",
            config_format="json-servers",
            entry=vscode_entry,
            executable=which("code"),
        ),
    }


def _client_is_detected(target: ClientTarget) -> bool:
    if target.name == "claude-code":
        return target.executable is not None
    assert target.config_path is not None
    return (
        target.config_path.exists()
        or target.config_path.parent.exists()
        or target.executable is not None
    )


def _json_servers_key(config_format: str) -> str:
    """Map a JSON client format to its server-map key.

    VS Code stores MCP servers under a top-level 'servers' object, whereas
    Claude Desktop, Gemini, Cursor and Windsurf use 'mcpServers'.
    """
    return "servers" if config_format == "json-servers" else "mcpServers"


def _read_json_config(path: Path, key: str = "mcpServers") -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientConfigError(
            f"Invalid or unreadable JSON at '{path}': {exc}. Fix or restore the "
            "client configuration, then retry; Cortex did not write anything."
        ) from exc
    if not isinstance(data, dict):
        raise ClientConfigError(
            f"Invalid JSON root at '{path}': expected an object. Cortex did not "
            "write anything."
        )
    servers = data.get(key)
    if servers is not None and not isinstance(servers, dict):
        raise ClientConfigError(
            f"Invalid '{key}' value at '{path}': expected an object. Cortex "
            "did not write anything."
        )
    return data


def _read_toml_config(path: Path) -> tuple[str, dict[str, Any]]:
    if not path.exists():
        return "", {}
    try:
        text = path.read_bytes().decode("utf-8")
        data = tomllib.loads(text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ClientConfigError(
            f"Invalid or unreadable TOML at '{path}': {exc}. Fix or restore the "
            "client configuration, then retry; Cortex did not write anything."
        ) from exc
    if not isinstance(data, dict):  # Defensive: TOML parsers currently always return dict.
        raise ClientConfigError(f"Invalid TOML root at '{path}'.")
    servers = data.get("mcp_servers")
    if servers is not None and not isinstance(servers, dict):
        raise ClientConfigError(
            f"Invalid 'mcp_servers' value at '{path}': expected a table. Cortex "
            "did not write anything."
        )
    cortex = servers.get("cortex") if isinstance(servers, dict) else None
    if cortex is not None and not isinstance(cortex, dict):
        raise ClientConfigError(
            f"Invalid 'mcp_servers.cortex' value at '{path}': expected a table. "
            "Cortex did not write anything."
        )
    return text, data


def _backup_path(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return path.with_name(f"{path.name}.{timestamp}.bak")


def _replace_atomically(path: Path, content: bytes) -> Path | None:
    """Back up an existing file and atomically replace it with content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    temporary: Path | None = None
    try:
        if path.exists():
            backup = _backup_path(path)
            shutil.copy2(path, backup)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return backup
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _json_with_entry(
    config: dict[str, Any], entry: Mapping[str, Any], key: str = "mcpServers"
) -> bytes | None:
    servers = config.setdefault(key, {})
    if servers.get("cortex") == dict(entry):
        return None
    servers["cortex"] = dict(entry)
    return (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _json_without_entry(
    config: dict[str, Any], key: str = "mcpServers"
) -> bytes | None:
    servers = config.get(key)
    if not isinstance(servers, dict) or "cortex" not in servers:
        return None
    del servers["cortex"]
    return (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _toml_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_with_entry(
    text: str,
    parsed: dict[str, Any],
    entry: Mapping[str, Any],
    *,
    path: Path,
) -> bytes | None:
    servers = parsed.get("mcp_servers", {})
    existing = servers.get("cortex") if isinstance(servers, dict) else None
    if isinstance(existing, dict) and all(
        existing.get(key) == value for key, value in entry.items()
    ):
        return None

    lines = text.splitlines(keepends=True)
    header_index: int | None = None
    end_index = len(lines)
    for index, line in enumerate(lines):
        match = _TABLE_HEADER_RE.match(line.rstrip("\r\n"))
        if match and match.group(1).strip() == "mcp_servers.cortex":
            header_index = index
            for following in range(index + 1, len(lines)):
                if _TABLE_HEADER_RE.match(lines[following].rstrip("\r\n")):
                    end_index = following
                    break
            break

    if header_index is None:
        if existing is not None:
            raise ClientConfigError(
                f"The Cortex entry in '{path}' uses an unsupported inline or dotted "
                "TOML form. Convert it to [mcp_servers.cortex], then retry; Cortex "
                "did not write anything."
            )
        newline = "\r\n" if "\r\n" in text else "\n"
        separator = "" if not text or text.endswith(("\n", "\r")) else newline
        if text and not text.endswith((newline + newline,)):
            separator += newline
        block = (
            "[mcp_servers.cortex]" + newline
            + f"command = {_toml_value(entry['command'])}" + newline
            + f"args = {_toml_value(entry['args'])}" + newline
        )
        return (text + separator + block).encode("utf-8")

    newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    found: set[str] = set()
    for index in range(header_index + 1, end_index):
        raw = lines[index].rstrip("\r\n")
        match = _TOML_ASSIGNMENT_RE.match(raw)
        if not match:
            continue
        key = match.group(2)
        if key == "args" and "[" in raw and "]" not in raw:
            raise ClientConfigError(
                f"The '{key}' value in '{path}' spans multiple lines and cannot be "
                "updated safely. Use a single-line value, then retry."
            )
        ending = "\r\n" if lines[index].endswith("\r\n") else "\n"
        if not lines[index].endswith(("\n", "\r")):
            ending = ""
        lines[index] = (
            f"{match.group(1)}{key}{match.group(3)} {_toml_value(entry[key])}{ending}"
        )
        found.add(key)

    insertions = [
        f"{key} = {_toml_value(entry[key])}{newline}"
        for key in ("command", "args")
        if key not in found
    ]
    if insertions and end_index > header_index + 1 and not lines[end_index - 1].endswith(
        ("\n", "\r")
    ):
        lines[end_index - 1] += newline
    lines[end_index:end_index] = insertions
    return "".join(lines).encode("utf-8")


def _toml_without_entry(
    text: str,
    parsed: dict[str, Any],
    *,
    path: Path,
) -> bytes | None:
    servers = parsed.get("mcp_servers", {})
    existing = servers.get("cortex") if isinstance(servers, dict) else None
    if existing is None:
        return None

    lines = text.splitlines(keepends=True)
    header_index: int | None = None
    end_index = len(lines)
    for index, line in enumerate(lines):
        match = _TABLE_HEADER_RE.match(line.rstrip("\r\n"))
        if match and match.group(1).strip() == "mcp_servers.cortex":
            header_index = index
            for following in range(index + 1, len(lines)):
                if _TABLE_HEADER_RE.match(lines[following].rstrip("\r\n")):
                    end_index = following
                    break
            break

    if header_index is None:
        raise ClientConfigError(
            f"The Cortex entry in '{path}' uses an unsupported inline or dotted "
            "TOML form. Convert it to [mcp_servers.cortex], then retry; Cortex "
            "did not write anything."
        )

    # Blank lines before the next table are separators, not Cortex settings.
    # Preserve them byte-for-byte with the surrounding user configuration.
    content_end = end_index
    while content_end > header_index + 1 and not lines[content_end - 1].strip():
        content_end -= 1
    del lines[header_index:content_end]
    return "".join(lines).encode("utf-8")


def _prepare_file_target(target: ClientTarget) -> bytes | None:
    """Parse and render a prospective update without touching the filesystem."""
    assert target.config_path is not None
    if target.config_format in ("json", "json-servers"):
        key = _json_servers_key(target.config_format)
        return _json_with_entry(
            _read_json_config(target.config_path, key), target.entry, key
        )
    if target.config_format.startswith("toml-table:"):
        text, parsed = _read_toml_config(target.config_path)
        return _toml_with_entry(text, parsed, target.entry, path=target.config_path)
    raise ClientConfigError(f"Unsupported client format: {target.config_format}")


def _prepare_file_unregistration(target: ClientTarget) -> bytes | None:
    """Parse and render removal of only the Cortex entry."""
    assert target.config_path is not None
    if target.config_format in ("json", "json-servers"):
        key = _json_servers_key(target.config_format)
        return _json_without_entry(_read_json_config(target.config_path, key), key)
    if target.config_format.startswith("toml-table:"):
        text, parsed = _read_toml_config(target.config_path)
        return _toml_without_entry(text, parsed, path=target.config_path)
    raise ClientConfigError(f"Unsupported client format: {target.config_format}")


def _register_file_target(target: ClientTarget, content: bytes | None) -> ClientResult:
    assert target.config_path is not None
    if content is None:
        return ClientResult(target.name, "OK", "already registered")
    backup = _replace_atomically(target.config_path, content)
    detail = f"updated {target.config_path}"
    if backup is not None:
        detail += f" (backup: {backup.name})"
    logger.info("Registered Cortex with %s at %s", target.name, target.config_path)
    return ClientResult(target.name, "OK", detail, changed=True)


def _unregister_file_target(target: ClientTarget) -> ClientResult:
    assert target.config_path is not None
    content = _prepare_file_unregistration(target)
    if content is None:
        return ClientResult(target.name, "OK", "already unregistered")
    backup = _replace_atomically(target.config_path, content)
    detail = f"updated {target.config_path}"
    if backup is not None:
        detail += f" (backup: {backup.name})"
    logger.info("Unregistered Cortex from %s at %s", target.name, target.config_path)
    return ClientResult(target.name, "OK", detail, changed=True)


def _run_claude(
    target: ClientTarget,
    args: Sequence[str],
    *,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    assert target.executable is not None
    return runner(
        [target.executable, *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _register_claude_code(target: ClientTarget, runner: Runner) -> ClientResult:
    expected = [str(target.entry["command"]), *map(str, target.entry["args"])]
    current = _run_claude(target, ["mcp", "get", "cortex"], runner=runner)
    combined = current.stdout + current.stderr
    if current.returncode == 0:
        if all(value in combined for value in expected):
            return ClientResult(target.name, "OK", "already registered at user scope")
        return ClientResult(
            target.name,
            "FAIL",
            "a different user-scope Cortex entry already exists; inspect it with "
            "`claude mcp get cortex` and remove it explicitly before retrying",
        )
    added = _run_claude(
        target,
        [
            "mcp",
            "add",
            "--scope",
            "user",
            "cortex",
            str(target.entry["command"]),
            *map(str, target.entry["args"]),
        ],
        runner=runner,
    )
    if added.returncode != 0:
        detail = (added.stderr or added.stdout).strip() or "unknown Claude CLI error"
        return ClientResult(target.name, "FAIL", f"claude mcp add failed: {detail}")
    logger.info("Registered Cortex with Claude Code at user scope")
    return ClientResult(target.name, "OK", "registered through claude mcp add --scope user", True)


def _unregister_claude_code(target: ClientTarget, runner: Runner) -> ClientResult:
    current = _run_claude(target, ["mcp", "get", "cortex"], runner=runner)
    if current.returncode != 0:
        return ClientResult(target.name, "OK", "already unregistered at user scope")
    removed = _run_claude(
        target,
        ["mcp", "remove", "--scope", "user", "cortex"],
        runner=runner,
    )
    if removed.returncode != 0:
        detail = (removed.stderr or removed.stdout).strip() or "unknown Claude CLI error"
        return ClientResult(target.name, "FAIL", f"claude mcp remove failed: {detail}")
    logger.info("Unregistered Cortex from Claude Code at user scope")
    return ClientResult(
        target.name,
        "OK",
        "unregistered through claude mcp remove --scope user",
        True,
    )


def _format_result(result: ClientResult) -> str:
    label = result.status if result.status != "SKIP" else "SKIP not installed"
    return f"[{label}] {result.client}: {result.message}"


def parse_client_selection(value: str | None, registry: Mapping[str, ClientTarget]) -> list[str]:
    """Resolve all, a comma-separated list, or the default detected clients."""
    if value is None:
        return [name for name, target in registry.items() if _client_is_detected(target)]
    requested = [item.strip().lower() for item in value.split(",") if item.strip()]
    if requested == ["none"]:
        return []
    if requested == ["all"]:
        return list(registry)
    unknown = sorted(set(requested) - set(registry))
    if unknown:
        raise ClientConfigError(
            f"Unknown client(s): {', '.join(unknown)}. Choose from: "
            f"{', '.join(CLIENT_NAMES)}, all, or none."
        )
    return list(dict.fromkeys(requested))


def register_clients(
    python_exe: str,
    *,
    clients: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner = subprocess.run,
) -> list[ClientResult]:
    """Register Cortex after fail-closed preflight of all selected files."""
    registry = client_registry(
        python_exe, environ=environ, home=home, which=which
    )
    selected = parse_client_selection(clients, registry)
    print("\n=== Cortex client registration ===")
    if not selected:
        print("[SKIP not installed] No supported clients detected.")
        return []
    for name in selected:
        target = registry[name]
        destination = target.config_path or "Claude CLI user scope"
        print(f"  - {name}: {destination}")

    prepared: dict[str, bytes | None] = {}
    results: list[ClientResult] = []
    try:
        for name in selected:
            target = registry[name]
            if not _client_is_detected(target):
                results.append(ClientResult(name, "SKIP", "client not installed"))
            elif target.config_path is not None:
                prepared[name] = _prepare_file_target(target)
    except ClientConfigError as exc:
        failure = ClientResult(name, "FAIL", str(exc))
        print(_format_result(failure))
        print("[FAIL] Registration aborted before any client configuration was written.")
        return [failure]

    for name in selected:
        if any(result.client == name for result in results):
            continue
        target = registry[name]
        try:
            result = (
                _register_claude_code(target, runner)
                if target.name == "claude-code"
                else _register_file_target(target, prepared[name])
            )
        except (ClientConfigError, OSError, subprocess.SubprocessError) as exc:
            result = ClientResult(name, "FAIL", str(exc))
        results.append(result)
    for result in results:
        print(_format_result(result))
    return results


def unregister_clients(
    python_exe: str,
    *,
    clients: str | None = "all",
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner = subprocess.run,
) -> list[ClientResult]:
    """Remove only Cortex MCP entries while preserving every other setting."""
    registry = client_registry(python_exe, environ=environ, home=home, which=which)
    selected = parse_client_selection(clients, registry)
    print("\n=== Cortex client unregistration ===")
    if not selected:
        print("[SKIP not installed] No supported clients selected.")
        return []

    results: list[ClientResult] = []
    for name in selected:
        target = registry[name]
        if not _client_is_detected(target):
            result = ClientResult(name, "SKIP", "client not installed")
        else:
            try:
                result = (
                    _unregister_claude_code(target, runner)
                    if target.name == "claude-code"
                    else _unregister_file_target(target)
                )
            except (ClientConfigError, OSError, subprocess.SubprocessError) as exc:
                result = ClientResult(name, "FAIL", str(exc))
        print(_format_result(result))
        results.append(result)
    return results


def init_user_config(
    path: Path = CORTEX_CONFIG_PATH,
    environ: dict[str, str] | None = None,
    input_fn: Callable[[str], str] = input,
    *,
    assume_yes: bool = False,
) -> bool:
    """Create schema-v1 user config atomically without overwriting."""
    if path.exists():
        print(f"[OK] Cortex user config already exists: {path}")
        return False
    values = dict(os.environ if environ is None else environ)
    kb_path = values.get("CORTEX_KB_PATH", "").strip().strip('"')
    if not kb_path and not assume_yes:
        kb_path = input_fn("Path to your Cortex knowledge base: ").strip().strip('"')
    if not kb_path:
        raise CortexConfigError(
            "Cannot initialize Cortex config without kb_path. Set "
            "CORTEX_KB_PATH or provide a path interactively."
        )
    values["CORTEX_KB_PATH"] = kb_path
    config = load_user_config(path=path, environ=values, script_dir=SCRIPT_DIR)
    created = write_user_config_atomic(path, config)
    if created:
        print(f"[OK] Created Cortex user config: {path}")
    return created


def offer_legacy_data_migration(
    *,
    config_path: Path = CORTEX_CONFIG_PATH,
    script_dir: Path = SCRIPT_DIR,
    environ: Mapping[str, str] | None = None,
    input_fn: Callable[[str], str] = input,
) -> bool:
    """Offer an explicit atomic move from the repository to the data home."""
    config = load_user_config(
        path=config_path,
        environ=environ,
        script_dir=script_dir,
    )
    legacy = Path(script_dir) / "chroma_db"
    target = Path(config.chroma_path)
    state = migration_state(legacy, target)
    if state == "conflict":
        raise DataHomeConflictError(
            f"Both legacy index '{legacy}' and configured target '{target}' exist. "
            "Migration aborted without changing either index."
        )
    if state != "required":
        return False

    print("\n=== Cortex data migration required ===")
    print(f"  legacy index : {legacy}")
    print(f"  data home    : {target}")
    print("  action       : atomic move; no copy and no second active index")
    answer = input_fn("Move the legacy index now? [y/N] : ").strip().lower()
    if answer not in {"y", "yes"}:
        print(
            "[SKIP] Legacy index kept in place. Search and sync will refuse to "
            "open a second index until migration is completed."
        )
        return False
    moved = move_legacy_index(legacy, target)
    if moved:
        print(f"[OK] Moved Cortex index to {target}")
        print(f"     Rollback: close all Cortex clients and move it back to {legacy}")
    return moved


def check_python(python_exe: str, *, frozen: bool = False) -> bool:
    if frozen:
        executable = Path(python_exe)
        if not executable.is_file():
            print(f"[FAIL] Standalone executable does not exist: {python_exe}")
            return False
        version = ".".join(map(str, sys.version_info[:3]))
        print(f"[OK] Standalone runtime: Python {version} in {executable.resolve()}")
        return True
    try:
        result = subprocess.run(
            [python_exe, "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            print(f"[FAIL] Python command failed: {python_exe}")
            return False
        print(f"[OK] Python: {(result.stdout or result.stderr).strip()}")
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] Python not found at {python_exe}: {exc}")
        return False


def check_packages(python_exe: str, *, frozen: bool = False) -> bool:
    ok = True
    for package in REQUIRED_PACKAGES:
        import_name = package.split("[")[0]
        if frozen:
            try:
                importlib.import_module(import_name)
                print(f"[OK] Bundled package: {package}")
            except ImportError as exc:
                print(f"[FAIL] Bundled package {package} not importable: {exc}")
                ok = False
            continue
        try:
            result = subprocess.run(
                [python_exe, "-c", f"import {import_name}; print('ok')"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip() == "ok":
                print(f"[OK] Package: {package}")
            else:
                print(f"[FAIL] Package {package} not importable: {result.stderr.strip()}")
                ok = False
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[FAIL] Package {package}: {exc}")
            ok = False
    return ok


def check_user_config() -> bool:
    try:
        config = load_user_config(path=CORTEX_CONFIG_PATH, script_dir=SCRIPT_DIR)
        kb_path = require_kb_path(config.kb_path, config_path=CORTEX_CONFIG_PATH)
        ensure_index_location(
            SCRIPT_DIR / "chroma_db",
            Path(config.chroma_path),
        )
    except (CortexConfigError, CortexDataHomeError) as exc:
        print(f"[FAIL] Cortex user config: {exc}")
        return False
    print(f"[OK] Cortex user config: {CORTEX_CONFIG_PATH}")
    print(f"     kb_path: {kb_path}")
    print(f"     chroma_path: {config.chroma_path}")
    print(f"     write_lock_path: {config.write_lock_path}")
    return True


def _entry_from_file(target: ClientTarget) -> Mapping[str, Any] | None:
    assert target.config_path is not None
    if target.config_format in ("json", "json-servers"):
        key = _json_servers_key(target.config_format)
        config = _read_json_config(target.config_path, key)
        servers = config.get(key, {})
    else:
        _, config = _read_toml_config(target.config_path)
        servers = config.get("mcp_servers", {})
    return servers.get("cortex") if isinstance(servers, dict) else None


def _validate_entry_paths(entry: Mapping[str, Any] | None) -> str | None:
    if not isinstance(entry, Mapping):
        return "Cortex MCP entry is missing"
    command = entry.get("command")
    args = entry.get("args")
    if not isinstance(command, str) or not Path(command).is_file():
        return f"Server command does not exist: {command!r}"
    if not isinstance(args, list) or not args or not isinstance(args[0], str):
        return "server argument is missing"
    if args == ["serve"]:
        return None
    if not Path(args[0]).is_file():
        return f"server.py does not exist: {args[0]!r}"
    return None


def check_clients(
    python_exe: str,
    *,
    clients: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner = subprocess.run,
) -> list[ClientResult]:
    """Validate registration and stored executable paths for selected clients."""
    registry = client_registry(python_exe, environ=environ, home=home, which=which)
    selected = parse_client_selection(clients, registry)
    results: list[ClientResult] = []
    for name in selected:
        target = registry[name]
        if not _client_is_detected(target):
            result = ClientResult(name, "SKIP", "client not installed")
        elif name == "claude-code":
            try:
                current = _run_claude(target, ["mcp", "get", "cortex"], runner=runner)
                combined = current.stdout + current.stderr
                expected = [
                    str(target.entry["command"]),
                    *map(str, target.entry["args"]),
                ]
                if current.returncode == 0 and all(value in combined for value in expected):
                    result = ClientResult(name, "OK", "user-scope entry and paths are valid")
                else:
                    result = ClientResult(
                        name, "FAIL", "user-scope Cortex entry is missing or stale"
                    )
            except (OSError, subprocess.SubprocessError) as exc:
                result = ClientResult(name, "FAIL", str(exc))
        else:
            try:
                error = _validate_entry_paths(_entry_from_file(target))
                result = ClientResult(
                    name,
                    "FAIL" if error else "OK",
                    error or "Cortex entry and paths are valid",
                )
            except ClientConfigError as exc:
                result = ClientResult(name, "FAIL", str(exc))
        print(_format_result(result))
        results.append(result)
    if not selected:
        print("[SKIP not installed] No supported clients detected.")
    return results


def run_check(
    python_exe: str,
    *,
    clients: str | None = None,
) -> int:
    print("\n=== Cortex installation check ===\n")
    frozen = bool(getattr(sys, "frozen", False))
    base_results = [
        check_python(python_exe, frozen=frozen),
        check_packages(python_exe, frozen=frozen),
        check_user_config(),
    ]
    client_results = check_clients(python_exe, clients=clients)
    success = all(base_results) and all(result.successful for result in client_results)
    print()
    if success:
        print("=== All checks passed. Cortex is ready. ===")
        return 0
    print("=== Some checks failed. See above for details. ===")
    return 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Cortex MCP setup helper")
    parser.add_argument(
        "--python", default=None, help="Python executable (default: current interpreter)"
    )
    parser.add_argument(
        "--clients",
        default=None,
        help="all, none, or a comma-separated list (default: detected clients)",
    )
    parser.add_argument(
        "--check", action="store_true", help="Validate without modifying anything"
    )
    parser.add_argument(
        "--init", action="store_true", help="Create per-user Cortex config"
    )
    parser.add_argument(
        "--unregister",
        action="store_true",
        help="Remove Cortex MCP entries without deleting user data",
    )
    parser.add_argument(
        "--migrate-data",
        action="store_true",
        help="Offer migration of a legacy repository-local Chroma index",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run layered strictly read-only support diagnostics",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the doctor report as stable JSON",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Non-interactive: no prompts. Requires CORTEX_KB_PATH for --init and "
            "never moves a legacy index (use --migrate-data explicitly)."
        ),
    )
    args = parser.parse_args(argv)
    python_exe = args.python or detect_python()

    try:
        if args.json and not args.doctor:
            parser.error("--json requires --doctor")
        if args.doctor:
            from doctor import main as doctor_main

            doctor_args = ["--python", python_exe]
            if args.json:
                doctor_args.append("--json")
            raise SystemExit(doctor_main(doctor_args))
        if args.init:
            init_user_config(assume_yes=args.yes)
            raise SystemExit(0)
        if args.migrate_data:
            offer_legacy_data_migration()
            raise SystemExit(0)
        if args.unregister:
            clients = args.clients if args.clients is not None else "all"
            results = unregister_clients(python_exe, clients=clients)
            raise SystemExit(0 if all(result.successful for result in results) else 1)
        if args.check:
            raise SystemExit(run_check(python_exe, clients=args.clients))
        if not args.yes:
            offer_legacy_data_migration()
        results = register_clients(python_exe, clients=args.clients)
        raise SystemExit(0 if all(result.successful for result in results) else 1)
    except (ClientConfigError, CortexConfigError, CortexDataHomeError) as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
