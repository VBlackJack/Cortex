@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

:: Self-locating: %~dp0 expands to the directory containing this script
:: (with trailing backslash). Lets Cortex relocate without editing anything.
set "CORTEX_DIR=%~dp0"
:: Strip trailing backslash for cleaner display
if "%CORTEX_DIR:~-1%"=="\" set "CORTEX_DIR=%CORTEX_DIR:~0,-1%"

echo.
echo ============================================================
echo   Cortex MCP — Installation / Reinstallation
echo   Install dir : %CORTEX_DIR%
echo ============================================================
echo.

:: ── Step 1 : Detect Python ───────────────────────────────────────────────────
echo [1/6] Detecting Python...

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

:: ── Step 2 : Configure CORTEX_KB_PATH ────────────────────────────────────────
echo [2/6] Checking knowledge base path (CORTEX_KB_PATH)...
echo.

if defined CORTEX_KB_PATH (
    if exist "!CORTEX_KB_PATH!\" (
        echo [OK]   CORTEX_KB_PATH = !CORTEX_KB_PATH!
    ) else (
        echo [WARN] CORTEX_KB_PATH is set to "!CORTEX_KB_PATH!"
        echo        but that directory does not exist.
        set "CORTEX_KB_PATH="
    )
)

if not defined CORTEX_KB_PATH (
    echo        Cortex needs the absolute path to your markdown knowledge base.
    echo        Example: D:\Confluence_Export   or   C:\Users\me\Documents\KB
    echo.
    set /p KB_INPUT="        Path to your knowledge base : "

    if "!KB_INPUT!"=="" (
        echo [FAIL] No path provided. Aborting.
        pause
        exit /b 1
    )
    if not exist "!KB_INPUT!\" (
        echo [FAIL] Directory does not exist : !KB_INPUT!
        pause
        exit /b 1
    )

    setx CORTEX_KB_PATH "!KB_INPUT!" >nul
    set "CORTEX_KB_PATH=!KB_INPUT!"
    echo [OK]   CORTEX_KB_PATH set to !KB_INPUT!
    echo        ^(persisted via setx — available in any new terminal^)
)
echo.

:: ── Step 3 : Install packages ────────────────────────────────────────────────
echo [3/6] Installing / upgrading required packages...
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

:: ── Step 4 : Patch claude_desktop_config.json ────────────────────────────────
echo [4/6] Patching Claude desktop config...
echo.

"!PYTHON_EXE!" "%CORTEX_DIR%\setup_config.py" --python "!PYTHON_EXE!"
if errorlevel 1 (
    echo.
    echo [FAIL] Could not patch claude_desktop_config.json.
    pause
    exit /b 1
)
echo.

:: ── Step 5 : Optional — wipe vector database ─────────────────────────────────
echo [5/6] Reset vector database?
echo.
echo        WARNING: This deletes all indexed vectors. You will need to
echo        re-run sync.bat (or cortex_sync via Claude) to rebuild the index.
echo        Required if you changed the embedding model.
echo.
set /p WIPE="        Wipe chroma_db? [y/N] : "

if /i "!WIPE!"=="y" (
    echo.
    echo        Wiping %CORTEX_DIR%\chroma_db ...
    if exist "%CORTEX_DIR%\chroma_db" (
        rmdir /s /q "%CORTEX_DIR%\chroma_db"
        echo [OK]   chroma_db deleted. Run sync.bat to reindex.
    ) else (
        echo [OK]   chroma_db did not exist, nothing to delete.
    )
) else (
    echo [OK]   chroma_db kept as-is.
)
echo.

:: ── Step 6 : Validate ────────────────────────────────────────────────────────
echo [6/6] Validating installation...
echo.

"!PYTHON_EXE!" "%CORTEX_DIR%\setup_config.py" --python "!PYTHON_EXE!" --check
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
