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


def test_installer_defaults_to_whole_folder_and_supports_advanced_sections() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "IndexModePage.SelectedValueIndex := 0" in script
    assert "Index everything in this folder (recommended)" in script
    assert "Organize into sections (advanced)" in script
    assert "knowledge,projects,notes" in script
    assert "CORTEX_INDEX_MODE" in script
    assert "CORTEX_INDEX_SECTIONS" in script
    assert "CommandLineValue('INDEXMODE')" in script
    assert "CommandLineValue('SECTIONS')" in script


def test_reinstall_defaults_to_keep_and_routes_reset_through_cortex_cli() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "ExistingConfigDetected := FileExists" in script
    assert "{userappdata}\\Cortex\\config.toml" in script
    assert "ReinstallPage.SelectedValueIndex := 0" in script
    assert "Keep my current Cortex configuration (recommended)" in script
    assert "CommandLineSwitchPresent('RESETCONFIG')" in script
    assert "Parameters := Parameters + ' --reset'" in script
    assert "if not KeepExistingConfiguration then" in script
    assert "DelTree(" not in script


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
    assert '"/DModelPayloadDir=$env:CORTEX_MODEL_PAYLOAD_DIR"' in workflow
    assert "packaging\\windows\\cortex-installer.iss" in workflow
    assert "dist-installer\\Cortex-Setup.exe" in workflow
    assert "out/Cortex-Setup.exe" in workflow
    assert "WINDOWS_CERT_PFX_BASE64" in workflow


def test_installer_embeds_models_in_the_stable_per_user_cache() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "#ifndef ModelPayloadDir" in script
    assert 'Source: "{#ModelPayloadDir}\\*"' in script
    assert 'DestDir: "{localappdata}\\Cortex\\models"' in script
    assert "recursesubdirs createallsubdirs" in script


def test_installer_embeds_apache_license_and_model_notices() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "Apache License" in license_text
    assert "Version 2.0, January 2004" in license_text
    assert 'Source: "..\\..\\LICENSE"' in script
    assert 'DestName: "Apache-2.0.txt"' in script
    assert 'Source: "..\\..\\THIRD_PARTY_NOTICES.md"' in script
    assert 'DestDir: "{localappdata}\\Cortex\\models\\licenses"' in script
    for value in (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q",
        "faf4aa4225822f3bc6376869cb1164e8e3feedd0",
        "jinaai/jina-reranker-v1-tiny-en",
        "aca45de6945b5dc6399abcd2a9c55ded5dc9111f",
        "Apache-2.0",
    ):
        assert value in notices


def test_release_verifies_a_fresh_fetch_without_generating_its_manifest() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/model_payload.py prepare" in workflow
    assert "CORTEX_MODEL_PAYLOAD_DIR" in workflow
    assert "Compressed Cortex-Setup.exe" in workflow
    assert "model_payload.py generate" not in workflow
    assert "upload-artifact" not in workflow


def test_release_smokes_installed_embedding_and_reranker_offline() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "Smoke-test installed models with Hugging Face offline" in workflow
    assert 'HF_HUB_OFFLINE: "1"' in workflow
    assert "Expected an empty per-user model cache before installation" in workflow
    assert "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /INDEX" in workflow
    assert 'sync --search "offline installer smoke"' in workflow
    assert "Offline installer embedding and reranker smoke passed" in workflow
    assert "licenses\\Apache-2.0.txt" in workflow
    assert "licenses\\THIRD_PARTY_NOTICES.md" in workflow
