@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /p IP=Device IP (e.g. 10.28.65.253): 
".venv\Scripts\python.exe" tools\device_check.py %IP% %*
pause
