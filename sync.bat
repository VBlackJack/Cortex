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

echo [1/7] Adsec...
"%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" Adsec
echo.

echo [2/7] Ansible...
"%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" Ansible
echo.

echo [3/7] Processes...
"%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" Processes
echo.

echo [4/7] Products...
"%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" Products
echo.

echo [5/7] Projects...
"%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" Projects
echo.

echo [6/7] Technical Services...
"%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" "Technical Services"
echo.

echo [7/7] Zabbix...
"%PYTHON_EXE%" "%CORTEX_DIR%\indexer.py" Zabbix
echo.

echo  ================================================
echo   Sync termine ! Appuie sur une touche.
echo  ================================================
pause > nul
endlocal
