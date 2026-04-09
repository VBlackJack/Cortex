@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

echo.
echo ============================================================
echo   Cortex MCP — Installation / Reinstallation
echo ============================================================
echo.

:: ── Step 1 : Detect Python ───────────────────────────────────────────────────
echo [1/5] Detecting Python...

set PYTHON_EXE=

:: Try python3 first, then python
for %%C in (python3 python) do (
    if "!PYTHON_EXE!"=="" (
        for /f "delims=" %%P in ('where %%C 2^>nul') do (
            if "!PYTHON_EXE!"=="" set PYTHON_EXE=%%P
        )
    )
)

:: Check version >= 3.9
if "!PYTHON_EXE!"=="" (
    echo [FAIL] Python not found in PATH.
    echo        Install Python 3.9+ from https://python.org and rerun this script.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('"!PYTHON_EXE!" --version 2^>&1') do set PY_VERSION=%%V
echo [OK]   Found : !PYTHON_EXE!
echo        Version : !PY_VERSION!
echo.

:: ── Step 2 : Install packages ────────────────────────────────────────────────
echo [2/5] Installing / upgrading required packages...
echo.

"!PYTHON_EXE!" -m pip install --upgrade mcp[cli] chromadb fastembed pydantic
if errorlevel 1 (
    echo.
    echo [FAIL] pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo.
echo [OK]   Packages installed.
echo.

:: ── Step 3 : Patch claude_desktop_config.json ────────────────────────────────
echo [3/5] Patching Claude desktop config...
echo.

"!PYTHON_EXE!" "G:\_dev\Cortex\setup_config.py" --python "!PYTHON_EXE!"
if errorlevel 1 (
    echo.
    echo [FAIL] Could not patch claude_desktop_config.json.
    pause
    exit /b 1
)
echo.

:: ── Step 4 : Optional — wipe vector database ─────────────────────────────────
echo [4/5] Reset vector database?
echo.
echo        WARNING: This deletes all indexed vectors. You will need to
echo        re-run sync.bat (or cortex_sync via Claude) to rebuild the index.
echo        Required if you changed the embedding model.
echo.
set /p WIPE="        Wipe chroma_db? [y/N] : "

if /i "!WIPE!"=="y" (
    echo.
    echo        Wiping G:\_dev\Cortex\chroma_db ...
    if exist "G:\_dev\Cortex\chroma_db" (
        rmdir /s /q "G:\_dev\Cortex\chroma_db"
        echo [OK]   chroma_db deleted. Run sync.bat to reindex.
    ) else (
        echo [OK]   chroma_db did not exist, nothing to delete.
    )
) else (
    echo [OK]   chroma_db kept as-is.
)
echo.

:: ── Step 5 : Validate ────────────────────────────────────────────────────────
echo [5/5] Validating installation...
echo.

"!PYTHON_EXE!" "G:\_dev\Cortex\setup_config.py" --python "!PYTHON_EXE!" --check
if errorlevel 1 (
    echo.
    echo [WARN] Validation reported issues — see above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Cortex is installed!
echo.
echo   Next steps:
echo     1. Restart the Claude desktop app
echo     2. Run sync.bat to index your knowledge base
echo        (or use the cortex_sync tool inside Claude)
echo ============================================================
echo.
pause
endlocal
