#!/usr/bin/env python3
# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""
setup_config.py - Cortex MCP installer helper
Usage:
  python setup_config.py                    # patch claude_desktop_config.json
  python setup_config.py --python PATH      # patch with explicit Python path
  python setup_config.py --init             # create per-user Cortex config
  python setup_config.py --check           # validate installation
"""

import sys
import os
import json
import subprocess
import argparse
from pathlib import Path

from user_config import (
    CortexConfigError,
    load_user_config,
    require_kb_path,
    user_config_path,
    write_user_config_atomic,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent.resolve()
SERVER_PY    = SCRIPT_DIR / "server.py"
CLAUDE_CONFIG_PATH = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
CORTEX_CONFIG_PATH = user_config_path()
REQUIRED_PACKAGES = ["mcp", "chromadb", "fastembed", "pydantic", "pdfplumber", "filelock"]
if sys.version_info < (3, 11):
    REQUIRED_PACKAGES.append("tomli")


# ── Helpers ────────────────────────────────────────────────────────────────────

def detect_python() -> str:
    """Return the absolute path of the running Python interpreter."""
    return sys.executable


def load_config() -> dict:
    if CLAUDE_CONFIG_PATH.exists():
        try:
            return json.loads(CLAUDE_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[WARN] Could not parse {CLAUDE_CONFIG_PATH} - starting fresh")
    return {}


def save_config(cfg: dict):
    CLAUDE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


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


def patch_config(python_exe: str) -> bool:
    """
    Inject / update the cortex MCP server entry in claude_desktop_config.json.
    Returns True on success.
    """
    python_path = str(Path(python_exe).resolve())
    server_path = str(SERVER_PY)

    cfg = load_config()
    cfg.setdefault("mcpServers", {})

    existing = cfg["mcpServers"].get("cortex", {})
    entry = {
        "command": python_path,
        "args": [server_path],
        "timeout": 120000,
    }

    if existing == entry:
        print("[OK] claude_desktop_config.json is already up to date.")
        return True

    cfg["mcpServers"]["cortex"] = entry
    save_config(cfg)

    print(f"[OK] Patched {CLAUDE_CONFIG_PATH}")
    print(f"     python : {python_path}")
    print(f"     server : {server_path}")
    return True


# ── Check mode ─────────────────────────────────────────────────────────────────

def check_python(python_exe: str) -> bool:
    try:
        result = subprocess.run(
            [python_exe, "--version"],
            capture_output=True, text=True, timeout=10
        )
        print(f"[OK] Python : {result.stdout.strip()}")
        return True
    except Exception as e:
        print(f"[FAIL] Python not found at {python_exe} - {e}")
        return False


def check_packages(python_exe: str) -> bool:
    ok = True
    for pkg in REQUIRED_PACKAGES:
        try:
            result = subprocess.run(
                [python_exe, "-c", f"import {pkg.split('[')[0]}; print('ok')"],
                capture_output=True, text=True, timeout=15
            )
            if result.stdout.strip() == "ok":
                print(f"[OK] Package : {pkg}")
            else:
                print(f"[FAIL] Package {pkg} not importable - {result.stderr.strip()}")
                ok = False
        except Exception as e:
            print(f"[FAIL] Package {pkg} - {e}")
            ok = False
    return ok


def check_config(python_exe: str) -> bool:
    if not CLAUDE_CONFIG_PATH.exists():
        print(f"[FAIL] Config not found : {CLAUDE_CONFIG_PATH}")
        return False

    try:
        cfg = json.loads(CLAUDE_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[FAIL] Config is invalid JSON : {CLAUDE_CONFIG_PATH}")
        return False

    entry = cfg.get("mcpServers", {}).get("cortex")
    if not entry:
        print("[FAIL] 'cortex' entry missing from mcpServers")
        return False

    stored_py  = entry.get("command", "")
    stored_srv = entry.get("args", [None])[0] if entry.get("args") else ""

    if not Path(stored_py).exists():
        print(f"[FAIL] Python path in config does not exist : {stored_py}")
        return False

    if not Path(stored_srv).exists():
        print(f"[FAIL] server.py path in config does not exist : {stored_srv}")
        return False

    print(f"[OK] Config  : cortex entry present and paths exist")
    print(f"     python  : {stored_py}")
    print(f"     server  : {stored_srv}")
    return True


def check_user_config() -> bool:
    try:
        config = load_user_config(path=CORTEX_CONFIG_PATH, script_dir=SCRIPT_DIR)
        kb_path = require_kb_path(config.kb_path, config_path=CORTEX_CONFIG_PATH)
    except CortexConfigError as exc:
        print(f"[FAIL] Cortex user config: {exc}")
        return False
    print(f"[OK] Cortex user config: {CORTEX_CONFIG_PATH}")
    print(f"     kb_path : {kb_path}")
    return True


def run_check(python_exe: str):
    print("\n=== Cortex Installation Check ===\n")
    results = [
        check_python(python_exe),
        check_packages(python_exe),
        check_user_config(),
        check_config(python_exe),
    ]
    print()
    if all(results):
        print("=== All checks passed. Cortex is ready! ===")
        print("    Restart the Claude desktop app to activate the MCP server.")
        sys.exit(0)
    else:
        print("=== Some checks failed. See above for details. ===")
        sys.exit(1)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cortex MCP setup helper")
    parser.add_argument("--python", default=None,
                        help="Path to Python executable (default: current interpreter)")
    parser.add_argument("--check", action="store_true",
                        help="Validate installation without modifying anything")
    parser.add_argument("--init", action="store_true",
                        help="Create per-user Cortex config without overwriting")
    args = parser.parse_args()

    python_exe = args.python or detect_python()

    if args.init:
        try:
            init_user_config()
        except CortexConfigError as exc:
            print(f"[FAIL] {exc}")
            sys.exit(1)
        sys.exit(0)
    elif args.check:
        run_check(python_exe)
    else:
        success = patch_config(python_exe)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
