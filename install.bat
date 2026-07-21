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
echo   Cortex MCP - Installation / Reinstallation
echo   Install dir : %CORTEX_DIR%
echo ============================================================
echo.

:: -- Step 1 : Detect Python ---------------------------------------------------
echo [1/6] Detecting Python...

set PYTHON_EXE=

:: Try python first (on Windows, python3 is often the Microsoft Store stub)
for %%C in (python python3) do (
    if "!PYTHON_EXE!"=="" (
        for /f "delims=" %%P in ('where %%C 2^>nul') do (
            if "!PYTHON_EXE!"=="" set PYTHON_EXE=%%P
        )
    )
)

:: Check version >= 3.10
if "!PYTHON_EXE!"=="" (
    echo [FAIL] Python not found in PATH.
    echo        Install Python 3.10+ from https://python.org and rerun this script.
    pause
    exit /b 1
)

"!PYTHON_EXE!" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Cortex requires Python 3.10 or newer.
    echo        Found: !PYTHON_EXE!
    pause
    exit /b 1
)

for /f "delims=" %%V in ('"!PYTHON_EXE!" --version 2^>&1') do set PY_VERSION=%%V
echo [OK]   Found : !PYTHON_EXE!
echo        Version : !PY_VERSION!
echo.

:: -- Step 2 : Configure CORTEX_KB_PATH ----------------------------------------
echo [2/6] Checking knowledge base path (CORTEX_KB_PATH)...
echo.

set "CORTEX_CONFIG_FILE=%APPDATA%\Cortex\config.toml"
if exist "!CORTEX_CONFIG_FILE!" (
    echo [OK]   Cortex user config found: !CORTEX_CONFIG_FILE!
    goto user_config_ready
)

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
    echo        Option: choose the folder Cortex reads for markdown documents.
    echo        Default: no folder is assumed, so an absolute path is required.
    echo        Consequence: documents stay in place; Cortex stores only the path
    echo        in %%APPDATA%%\Cortex and generated data in %%LOCALAPPDATA%%\Cortex.
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

    set "CORTEX_KB_PATH=!KB_INPUT!"
    echo [OK]   Knowledge base path selected: !KB_INPUT!
    echo        ^(it will be stored in the per-user Cortex config^)
)

:user_config_ready
echo.

:: -- Step 3 : Install packages ------------------------------------------------
echo [3/6] Installing / upgrading required packages...
echo.

"!PYTHON_EXE!" -m pip install --upgrade -r "%CORTEX_DIR%\requirements.txt"
if errorlevel 1 (
    echo.
    echo [FAIL] pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo.
echo [OK]   Packages installed.
echo.

:: -- Step 4 : Register detected MCP clients ----------------------------------
echo [4/6] Register Cortex with detected AI clients?
echo.

if not exist "!CORTEX_CONFIG_FILE!" (
    "!PYTHON_EXE!" "%CORTEX_DIR%\setup_config.py" --init
    if errorlevel 1 (
        echo.
        echo [FAIL] Could not initialize Cortex user config.
        pause
        exit /b 1
    )
)

echo        Supported clients: Claude Desktop, Claude Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf and VS Code.
echo        Option: add Cortex to each supported client detected on this PC.
echo        Default: yes. Press Enter to register every detected client.
echo        Consequence: only the Cortex entry changes; existing settings are
echo        backed up and preserved. Choose no to leave all clients unchanged.
set "CLIENT_CHECK_ARGS="
set /p REGISTER_CLIENTS="        Register detected clients? [Y/n] : "
if /i "!REGISTER_CLIENTS!"=="n" (
    echo [OK]   Client registration skipped by user.
    set "CLIENT_CHECK_ARGS=--clients none"
) else (
    "!PYTHON_EXE!" "%CORTEX_DIR%\setup_config.py" --python "!PYTHON_EXE!"
    if errorlevel 1 (
        echo.
        echo [FAIL] Could not register Cortex with the selected clients.
        pause
        exit /b 1
    )
)
echo.

:: -- Step 5 : Optional - wipe vector database ---------------------------------
echo [5/6] Reset vector database?
echo.
echo        Option: delete the repository-local legacy chroma_db directory.
echo        Default: no, which preserves the current directory.
echo        Consequence: yes deletes only %%CORTEX_DIR%%\chroma_db. Documents and
echo        %%LOCALAPPDATA%%\Cortex stay unchanged; run sync.bat to rebuild later.
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

:: -- Step 6 : Validate --------------------------------------------------------
echo [6/6] Validating installation...
echo.

"!PYTHON_EXE!" "%CORTEX_DIR%\setup_config.py" --python "!PYTHON_EXE!" --check !CLIENT_CHECK_ARGS!
if errorlevel 1 (
    echo.
    echo [WARN] Validation reported issues - see above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Cortex is installed!
echo.
echo   Next steps:
echo     1. Restart the AI clients registered above
echo     2. Run sync.bat to index your knowledge base
echo        (or use the cortex_sync tool inside an MCP client)
echo ============================================================
echo.
pause
endlocal
