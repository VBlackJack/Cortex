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

<#
.SYNOPSIS
    Build the standalone Cortex executable on Windows with PyInstaller.
.DESCRIPTION
    Produces a single-file cortex.exe containing the CLI and MCP server. Install
    the build extra first with: python -m pip install -e ".[build]".
.PARAMETER Python
    Python interpreter used for the build. Defaults to the repository virtual
    environment and falls back to python on PATH.
.PARAMETER OutputDir
    Directory receiving the executable. Defaults to dist.
.PARAMETER Clean
    Remove previous PyInstaller build and output directories before building.
.EXAMPLE
    ./scripts/build_installer.ps1 -Clean
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$Python = ".venv\Scripts\python.exe",

    [Parameter(Mandatory = $false)]
    [string]$OutputDir = "dist",

    [Parameter(Mandatory = $false)]
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Entry = Join-Path $RepoRoot "packaging\cortex_launcher.py"
$WorkPath = Join-Path $RepoRoot "build\pyinstaller"
$DistPath = Join-Path $RepoRoot $OutputDir
$ExeName = "cortex"
$CollectedPackages = @("chromadb", "onnxruntime", "fastembed", "tokenizers")
$HiddenImports = @(
    "server",
    "indexer",
    "doctor",
    "setup_wizard",
    "setup_config",
    "sync_hash_aware",
    "sync_summary",
    "lexical_index",
    "reranker",
    "chroma_client",
    "chunker",
    "chunker_pdf",
    "chunker_utils",
    "config",
    "cortex_logging",
    "data_home",
    "dependencies",
    "embedding_fingerprint",
    "freshness",
    "user_config",
    "write_lock",
    "truststore",
    "_version"
)

try {
    if (-not (Test-Path -LiteralPath $Python)) {
        Write-Warning "Interpreter '$Python' not found; falling back to 'python' on PATH."
        $Python = "python"
    }
    if (-not (Test-Path -LiteralPath $Entry)) {
        throw "Entry script not found: $Entry"
    }

    & $Python -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed. Run: $Python -m pip install -e `".[build]`""
    }

    if ($Clean) {
        foreach ($path in @($WorkPath, $DistPath)) {
            if ((Test-Path -LiteralPath $path) -and $PSCmdlet.ShouldProcess($path, "Remove")) {
                Remove-Item -LiteralPath $path -Recurse -Force
            }
        }
    }

    $arguments = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name", $ExeName,
        "--paths", $RepoRoot,
        "--distpath", $DistPath,
        "--workpath", $WorkPath,
        "--specpath", $WorkPath
    )
    foreach ($package in $CollectedPackages) {
        $arguments += @("--collect-all", $package)
    }
    foreach ($module in $HiddenImports) {
        $arguments += @("--hidden-import", $module)
    }
    $arguments += $Entry

    if ($PSCmdlet.ShouldProcess($Entry, "Build cortex.exe")) {
        & $Python @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed with exit code $LASTEXITCODE."
        }
        $exePath = Join-Path $DistPath "$ExeName.exe"
        if (-not (Test-Path -LiteralPath $exePath)) {
            throw "Build reported success but $exePath is missing."
        }
        Write-Output "Built standalone executable: $exePath"
    }
}
catch {
    Write-Error "Build failed: $_"
    exit 1
}
