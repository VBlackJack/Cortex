#!/usr/bin/env python3
# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Configure Cortex and register its MCP server with supported AI clients."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

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
REQUIRED_PACKAGES = [
    "mcp",
    "chromadb",
    "fastembed",
    "pydantic",
    "pdfplumber",
    "filelock",
]
if sys.version_info < (3, 11):
    REQUIRED_PACKAGES.append("tomli")

CLIENT_NAMES = ("claude-desktop", "claude-code", "codex", "gemini")
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


def _resolved_entry(python_exe: str) -> dict[str, Any]:
    return {
        "command": str(Path(python_exe).resolve()),
        "args": [str(SERVER_PY)],
    }


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


def _read_json_config(path: Path) -> dict[str, Any]:
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
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise ClientConfigError(
            f"Invalid 'mcpServers' value at '{path}': expected an object. Cortex "
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


def _json_with_entry(config: dict[str, Any], entry: Mapping[str, Any]) -> bytes | None:
    servers = config.setdefault("mcpServers", {})
    if servers.get("cortex") == dict(entry):
        return None
    servers["cortex"] = dict(entry)
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


def _prepare_file_target(target: ClientTarget) -> bytes | None:
    """Parse and render a prospective update without touching the filesystem."""
    assert target.config_path is not None
    if target.config_format == "json":
        return _json_with_entry(_read_json_config(target.config_path), target.entry)
    if target.config_format.startswith("toml-table:"):
        text, parsed = _read_toml_config(target.config_path)
        return _toml_with_entry(text, parsed, target.entry, path=target.config_path)
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


def init_user_config(
    path: Path = CORTEX_CONFIG_PATH,
    environ: dict[str, str] | None = None,
    input_fn=input,
) -> bool:
    """Create schema-v1 user config atomically without overwriting."""
    if path.exists():
        print(f"[OK] Cortex user config already exists: {path}")
        return False
    values = dict(os.environ if environ is None else environ)
    kb_path = values.get("CORTEX_KB_PATH", "").strip().strip('"')
    if not kb_path:
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


def check_python(python_exe: str) -> bool:
    try:
        result = subprocess.run(
            [python_exe, "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            print(f"[FAIL] Python command failed: {python_exe}")
            return False
        print(f"[OK] Python: {(result.stdout or result.stderr).strip()}")
        return True
    except Exception as exc:
        print(f"[FAIL] Python not found at {python_exe}: {exc}")
        return False


def check_packages(python_exe: str) -> bool:
    ok = True
    for package in REQUIRED_PACKAGES:
        try:
            result = subprocess.run(
                [python_exe, "-c", f"import {package.split('[')[0]}; print('ok')"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip() == "ok":
                print(f"[OK] Package: {package}")
            else:
                print(f"[FAIL] Package {package} not importable: {result.stderr.strip()}")
                ok = False
        except Exception as exc:
            print(f"[FAIL] Package {package}: {exc}")
            ok = False
    return ok


def check_user_config() -> bool:
    try:
        config = load_user_config(path=CORTEX_CONFIG_PATH, script_dir=SCRIPT_DIR)
        kb_path = require_kb_path(config.kb_path, config_path=CORTEX_CONFIG_PATH)
    except CortexConfigError as exc:
        print(f"[FAIL] Cortex user config: {exc}")
        return False
    print(f"[OK] Cortex user config: {CORTEX_CONFIG_PATH}")
    print(f"     kb_path: {kb_path}")
    return True


def _entry_from_file(target: ClientTarget) -> Mapping[str, Any] | None:
    assert target.config_path is not None
    if target.config_format == "json":
        config = _read_json_config(target.config_path)
        servers = config.get("mcpServers", {})
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
        return f"Python executable does not exist: {command!r}"
    if not isinstance(args, list) or not args or not isinstance(args[0], str):
        return "server argument is missing"
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
    base_results = [
        check_python(python_exe),
        check_packages(python_exe),
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


def main() -> None:
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
    args = parser.parse_args()
    python_exe = args.python or detect_python()

    try:
        if args.init:
            init_user_config()
            raise SystemExit(0)
        if args.check:
            raise SystemExit(run_check(python_exe, clients=args.clients))
        results = register_clients(python_exe, clients=args.clients)
        raise SystemExit(0 if all(result.successful for result in results) else 1)
    except (ClientConfigError, CortexConfigError) as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
