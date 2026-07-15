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
"""Static contracts for the Windows installer and its release integration."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "packaging" / "windows" / "cortex-installer.iss"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_inno_script_declares_safe_per_user_install_contract() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    for directive in (
        "PrivilegesRequired=lowest",
        "DefaultDirName={localappdata}\\Programs\\Cortex",
        "ArchitecturesAllowed=x64compatible",
        "ArchitecturesInstallIn64BitMode=x64compatible",
        "ChangesEnvironment=yes",
        "OutputBaseFilename=Cortex-Setup",
    ):
        assert directive in script
    assert 'AppPublisher=Julien Bombled' in script


def test_installer_runs_setup_without_a_shell_and_checks_failure() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "SetEnvironmentVariableW@kernel32.dll stdcall" in script
    assert "Parameters := 'setup --yes --clients all'" in script
    assert "Parameters := Parameters + ' --no-index'" in script
    assert "ewWaitUntilTerminated" in script
    assert "ResultCode <> 0" in script
    assert "GetCustomSetupExitCode" in script
    assert "cmd /c" not in script.lower()


def test_uninstaller_unregisters_before_removing_user_path() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    uninstall = script[script.index("procedure CurUninstallStepChanged") :]

    assert "unregister --yes --clients all" in uninstall
    assert uninstall.index("unregister --yes --clients all") < uninstall.index(
        "RemoveAppFromUserPath"
    )
    assert "PathWithoutEntry" in script


def test_release_builds_and_attaches_windows_installer() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "choco install innosetup --no-progress -y" in workflow
    assert '"/DAppVersion=$version"' in workflow
    assert "packaging\\windows\\cortex-installer.iss" in workflow
    assert "dist-installer\\Cortex-Setup.exe" in workflow
    assert "out/Cortex-Setup.exe" in workflow
    assert "WINDOWS_CERT_PFX_BASE64" in workflow
