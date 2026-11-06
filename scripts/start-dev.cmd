@echo off
setlocal
cd /d "%~dp0.."
set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links"
if not exist .venv\Scripts\python.exe (
  echo Run scripts\setup-local.cmd first.
  exit /b 1
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo FFmpeg is missing. Install it and restart the command prompt.
  exit /b 1
)
docker compose --env-file .local/services.env up -d --wait
if errorlevel 1 exit /b 1
start "Catfeedik API" cmd /k ".venv\Scripts\python.exe scripts\dev-api.py"
start "Catfeedik Worker" cmd /k ".venv\Scripts\python.exe scripts\dev-worker.py"
start "Catfeedik Web" cmd /k "npm run dev -- --port 5174"
echo Open http://localhost:5174 after all three windows have started.
echo Keep Docker Desktop and the three windows open. Close old servers before running this script.
