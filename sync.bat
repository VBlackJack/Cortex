@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

set "CORTEX_DIR=%~dp0"

echo.
echo ================================================
echo  CORTEX - Sync Knowledge Base (section by section)
echo ================================================
echo  Mode : ONNX (no PyTorch) - RAM optimized
echo.

set PYTHON_EXE=
for %%C in (python python3) do (
    if "!PYTHON_EXE!"=="" (
        for /f "delims=" %%P in ('where %%C 2^>nul') do (
            if "!PYTHON_EXE!"=="" (
                "%%P" --version >nul 2>&1
                if not errorlevel 1 set "PYTHON_EXE=%%P"
            )
        )
    )
)

if "!PYTHON_EXE!"=="" (
    echo [FAIL] Python not found in PATH.
    echo        Install Python 3.10+ from https://python.org and rerun.
    pause
    exit /b 1
)

echo  Python : !PYTHON_EXE!
echo.

cd /d "%CORTEX_DIR%"
set "SECTIONS_FILE=%TEMP%\cortex_sections_!RANDOM!.txt"
"!PYTHON_EXE!" -c "from indexer import discover_sections; print('\n'.join(discover_sections()))" > "!SECTIONS_FILE!"

if errorlevel 1 (
    echo.
    echo [FAIL] Section discovery failed. No synchronization was attempted.
    del "!SECTIONS_FILE!" 2>nul
    endlocal & exit /b 1
)

set /a COUNT=0
for /f "usebackq delims=" %%S in ("!SECTIONS_FILE!") do set /a COUNT+=1

if !COUNT! EQU 0 (
    echo.
    echo [FAIL] Section discovery returned no sections. No synchronization was attempted.
    del "!SECTIONS_FILE!" 2>nul
    endlocal & exit /b 1
)

set /a IDX=0
set /a FAILURES=0
for /f "usebackq delims=" %%S in ("!SECTIONS_FILE!") do (
    set /a IDX+=1
    echo [!IDX!/%COUNT%] Syncing: %%S
    "!PYTHON_EXE!" "%CORTEX_DIR%indexer.py" "%%S"
    if errorlevel 1 (
        set /a FAILURES+=1
        echo [!IDX!/%COUNT%] %%S FAILED.
    ) else (
        echo [!IDX!/%COUNT%] %%S done.
    )
    echo.
)

del "!SECTIONS_FILE!" 2>nul

if !FAILURES! GTR 0 (
    set "EXIT_CODE=1"
    echo ================================================
    echo  Sync completed with !FAILURES! failed section(s).
    echo ================================================
) else (
    set "EXIT_CODE=0"
    echo ================================================
    echo  Sync complete - all !COUNT! section(s) succeeded.
    echo ================================================
    echo.
    "!PYTHON_EXE!" "%CORTEX_DIR%sync_summary.py"
    if errorlevel 1 (
        set "EXIT_CODE=1"
        echo [FAIL] Could not generate the synchronization summary.
    )
)
echo.
pause >nul
endlocal & exit /b %EXIT_CODE%
