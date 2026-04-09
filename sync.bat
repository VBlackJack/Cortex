@echo off
setlocal
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

echo.
echo ================================================
echo  CORTEX - Sync Knowledge Base (section by section)
echo ================================================
echo  Mode : ONNX (no PyTorch) - RAM optimized
echo.

C:\Python313\python.exe G:\_dev\Cortex\indexer.py Adsec
echo [1/8] Adsec done.

C:\Python313\python.exe G:\_dev\Cortex\indexer.py Ansible
echo [2/8] Ansible done.

C:\Python313\python.exe G:\_dev\Cortex\indexer.py Processes
echo [3/8] Processes done.

C:\Python313\python.exe G:\_dev\Cortex\indexer.py Products
echo [4/8] Products done.

C:\Python313\python.exe G:\_dev\Cortex\indexer.py Projects
echo [5/8] Projects done.

C:\Python313\python.exe G:\_dev\Cortex\indexer.py "Technical Services"
echo [6/8] Technical Services done.

C:\Python313\python.exe G:\_dev\Cortex\indexer.py Zabbix
echo [7/8] Zabbix done.

C:\Python313\python.exe G:\_dev\Cortex\indexer.py Books
echo [8/8] Books done.

echo.
echo ================================================
echo  Sync complete! Press any key to exit.
echo ================================================
pause >nul
endlocal
