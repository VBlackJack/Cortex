#Requires -Version 5.1
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
    Delegates to the canonical Python builder, which derives every hidden
    import from pyproject.toml and produces a single-file cortex.exe.
.PARAMETER Python
    Python interpreter used for the build. Defaults to the repository virtual
    environment and falls back to python on PATH.
.PARAMETER OutputDir
    Dedicated directory receiving the executable. Must resolve to repository dist.
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

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

[string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
[string]$Builder = Join-Path $RepoRoot "packaging\build_executable.py"

try {
    [string]$PythonCommand = $Python
    if (-not [IO.Path]::IsPathRooted($PythonCommand)) {
        [string]$RepositoryCandidate = Join-Path $RepoRoot $PythonCommand
        if (Test-Path -LiteralPath $RepositoryCandidate -PathType Leaf) {
            $PythonCommand = $RepositoryCandidate
        }
        elseif ($PythonCommand -ceq ".venv\Scripts\python.exe") {
            Write-Warning (
                "Interpreter '$PythonCommand' was not found in the repository; " +
                "falling back to 'python' on PATH."
            )
            $PythonCommand = "python"
        }
    }
    if (-not (Test-Path -LiteralPath $PythonCommand -PathType Leaf)) {
        [System.Management.Automation.CommandInfo]$DiscoveredPython =
            Get-Command $PythonCommand -ErrorAction Stop
        $PythonCommand = $DiscoveredPython.Source
    }
    if (-not (Test-Path -LiteralPath $Builder -PathType Leaf)) {
        throw "Canonical build script not found: $Builder"
    }

    [string[]]$Arguments = @($Builder, "--output-dir", $OutputDir)
    if ($Clean.IsPresent) {
        $Arguments += "--clean"
    }

    if ($PSCmdlet.ShouldProcess($RepoRoot, "Build the standalone Cortex executable")) {
        Push-Location $RepoRoot
        try {
            & $PythonCommand @Arguments
            if ($LASTEXITCODE -ne 0) {
                throw "Canonical executable build failed with exit code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }
}
catch {
    Write-Error "Build failed: $($_.Exception.Message)"
    exit 1
}
