@echo off
chcp 65001 >nul
title ZK Attendance Pro
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating the Python environment ...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo Python 3.10+ is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
    pause
    exit /b 1
  )
  echo [2/2] Installing packages ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" http://127.0.0.1:8090
".venv\Scripts\python.exe" run.py %*
pause
