@echo off
echo.
echo  ================================================
echo   CORTEX - Sync Knowledge Base (par section)
echo  ================================================
echo  Mode : ONNX (sans PyTorch) - RAM optimisee
echo.

echo [1/7] Adsec...
C:\Python313\python.exe G:\_dev\Cortex\indexer.py Adsec
echo.

echo [2/7] Ansible...
C:\Python313\python.exe G:\_dev\Cortex\indexer.py Ansible
echo.

echo [3/7] Processes...
C:\Python313\python.exe G:\_dev\Cortex\indexer.py Processes
echo.

echo [4/7] Products...
C:\Python313\python.exe G:\_dev\Cortex\indexer.py Products
echo.

echo [5/7] Projects...
C:\Python313\python.exe G:\_dev\Cortex\indexer.py Projects
echo.

echo [6/7] Technical Services...
C:\Python313\python.exe G:\_dev\Cortex\indexer.py "Technical Services"
echo.

echo [7/7] Zabbix...
C:\Python313\python.exe G:\_dev\Cortex\indexer.py Zabbix
echo.

echo  ================================================
echo   Sync termine ! Appuie sur une touche.
echo  ================================================
pause > nul
