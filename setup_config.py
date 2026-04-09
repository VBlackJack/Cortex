#!/usr/bin/env python3
"""
setup_config.py - Cortex MCP installer helper
Usage:
  python setup_config.py                    # patch claude_desktop_config.json
  python setup_config.py --python C:\...   # patch with explicit Python path
  python setup_config.py --check           # validate installation
"""

import sys
import os
import json
import subprocess
import argparse
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent.resolve()          # G:\_dev\Cortex
SERVER_PY    = SCRIPT_DIR / "server.py"
CONFIG_PATH  = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
REQUIRED_PACKAGES = ["mcp", "chromadb", "fastembed", "pydantic"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def detect_python() -> str:
    """Return the absolute path of the running Python interpreter."""
    return sys.executable


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[WARN] Could not parse {CONFIG_PATH} - starting fresh")
    return {}


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


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

    print(f"[OK] Patched {CONFIG_PATH}")
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
    if not CONFIG_PATH.exists():
        print(f"[FAIL] Config not found : {CONFIG_PATH}")
        return False

    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[FAIL] Config is invalid JSON : {CONFIG_PATH}")
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


def run_check(python_exe: str):
    print("\n=== Cortex Installation Check ===\n")
    results = [
        check_python(python_exe),
        check_packages(python_exe),
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
    args = parser.parse_args()

    python_exe = args.python or detect_python()

    if args.check:
        run_check(python_exe)
    else:
        success = patch_config(python_exe)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
