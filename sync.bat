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
    echo        Install Python 3.9+ from https://python.org and rerun.
    pause
    exit /b 1
)

echo  Python : !PYTHON_EXE!
echo.

cd /d "%CORTEX_DIR%"
"!PYTHON_EXE!" -c "from indexer import discover_sections; print('\n'.join(discover_sections()))" > "%TEMP%\cortex_sections.txt" 2>nul

if not exist "%TEMP%\cortex_sections.txt" (
    echo [WARN] Could not discover sections, using defaults.
    (
        echo Adsec
        echo Ansible
        echo Processes
        echo Products
        echo Projects
        echo Technical Services
        echo Zabbix
        echo Books
    ) > "%TEMP%\cortex_sections.txt"
)

set /a COUNT=0
for /f "usebackq delims=" %%S in ("%TEMP%\cortex_sections.txt") do set /a COUNT+=1

set /a IDX=0
for /f "usebackq delims=" %%S in ("%TEMP%\cortex_sections.txt") do (
    set /a IDX+=1
    echo [!IDX!/%COUNT%] Syncing: %%S
    "!PYTHON_EXE!" "%CORTEX_DIR%indexer.py" "%%S"
    echo [!IDX!/%COUNT%] %%S done.
    echo.
)

del "%TEMP%\cortex_sections.txt" 2>nul

echo ================================================
echo  Sync complete!
echo ================================================
echo.
"!PYTHON_EXE!" "%CORTEX_DIR%sync_summary.py"
echo.
pause >nul
endlocal
