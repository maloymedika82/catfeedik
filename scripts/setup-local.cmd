@echo off
setlocal
cd /d "%~dp0.."
set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links"
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.12 first: winget install -e --id Python.Python.3.12
  exit /b 1
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo Install FFmpeg: winget install -e --id Gyan.FFmpeg
  echo Then open a NEW command prompt and run this script again.
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo Start Docker Desktop, wait for Engine running, then try again.
  exit /b 1
)
call npm ci
if errorlevel 1 exit /b 1
if not exist .venv\Scripts\python.exe py -3.12 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe scripts\init-local.py
if errorlevel 1 exit /b 1
docker compose --env-file .local/services.env up -d --wait
if errorlevel 1 exit /b 1
echo Setup complete. Run scripts\start-dev.cmd next.
