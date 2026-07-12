# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Static contract tests for Windows batch orchestration."""

from __future__ import annotations

from pathlib import Path

SYNC_BAT = Path(__file__).resolve().parents[1] / "sync.bat"
INSTALL_BAT = Path(__file__).resolve().parents[1] / "install.bat"


def _sync_script() -> str:
    return SYNC_BAT.read_text(encoding="utf-8")


def test_section_discovery_keeps_stderr_and_fails_when_empty() -> None:
    script = _sync_script()
    discovery_line = next(
        line for line in script.splitlines() if "from indexer import discover_sections" in line
    )

    assert "2>nul" not in discovery_line
    assert "if errorlevel 1" in script
    assert "if !COUNT! EQU 0" in script
    assert "No synchronization was attempted" in script


def test_dead_section_fallback_is_absent() -> None:
    script = _sync_script()

    for legacy_section in ("Adsec", "Ansible", "Zabbix", "Books"):
        assert f"echo {legacy_section}" not in script


def test_section_failures_control_banner_and_exit_code() -> None:
    script = _sync_script()

    assert "set /a FAILURES=0" in script
    assert "set /a FAILURES+=1" in script
    assert "if !FAILURES! GTR 0" in script
    assert "Sync completed with !FAILURES! failed section(s)." in script
    assert "endlocal & exit /b %EXIT_CODE%" in script


def test_installer_enforces_python_310() -> None:
    script = INSTALL_BAT.read_text(encoding="utf-8")

    assert "sys.version_info >= (3, 10)" in script
    assert "requires Python 3.10 or newer" in script


def test_installer_initializes_missing_user_config() -> None:
    script = INSTALL_BAT.read_text(encoding="utf-8")

    assert 'if not exist "!CORTEX_CONFIG_FILE!"' in script
    assert 'setup_config.py" --init' in script


def test_installer_proposes_detected_client_registration() -> None:
    script = INSTALL_BAT.read_text(encoding="utf-8")

    assert "Register Cortex with detected AI clients?" in script
    assert "Register detected clients? [Y/n]" in script
    assert "Claude Desktop, Claude Code, Codex and Gemini" in script
    assert 'set "CLIENT_CHECK_ARGS=--clients none"' in script
