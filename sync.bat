@echo off
setlocal EnableDelayedExpansion

:: Self-locating: %~dp0 expands to this script's directory (with trailing \)
set "CORTEX_DIR=%~dp0"
if "%CORTEX_DIR:~-1%"=="\" set "CORTEX_DIR=%CORTEX_DIR:~0,-1%"

:: Detect Python from PATH
set "PYTHON_EXE="
for %%C in (python3 python) do (
    if "!PYTHON_EXE!"=="" (
        for /f "delims=" %%P in ('where %%C 2^>nul') do (
            if "!PYTHON_EXE!"=="" set "PYTHON_EXE=%%P"
        )
    )
)
if "!PYTHON_EXE!"=="" (
    echo [FAIL] Python not found in PATH. Run install.bat first.
    pause
    exit /b 1
)

if not defined CORTEX_KB_PATH (
    echo [FAIL] CORTEX_KB_PATH is not set.
    echo        Run install.bat first, or set it with:
    echo            setx CORTEX_KB_PATH "<path to your knowledge base>"
    echo        then open a new terminal.
    pause
    exit /b 1
)

echo.
echo  ================================================
echo   CORTEX - Sync Knowledge Base (par section)
echo  ================================================
echo   Cortex dir : %CORTEX_DIR%
echo   KB path    : %CORTEX_KB_PATH%
echo   Python     : %PYTHON_EXE%
echo  ================================================
echo.

:: Discover sections from CORTEX_KB_PATH (one per line)
echo  Discovering sections...
set /a SECTION_COUNT=0
for /f "usebackq delims=" %%S in (`""%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" --list-sections"`) do (
    set /a SECTION_COUNT+=1
)

if %SECTION_COUNT%==0 (
    echo  [FAIL] No sections found under "%CORTEX_KB_PATH%".
    echo         Make sure the directory contains at least one subdirectory.
    pause
    exit /b 1
)

echo  Found %SECTION_COUNT% section(s).
echo.

set /a INDEX=0
for /f "usebackq delims=" %%S in (`""%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" --list-sections"`) do (
    set /a INDEX+=1
    echo [!INDEX!/%SECTION_COUNT%] %%S...
    "%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" "%%S"
    echo.
)

echo  ================================================
echo   Sync termine ! Appuie sur une touche.
echo  ================================================
pause > nul
endlocal
