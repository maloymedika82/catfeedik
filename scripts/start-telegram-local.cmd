@echo off
setlocal
set "APP_ENV=development"
set "ALLOW_DEV_LOGIN=0"
set "ALLOW_DEV_ADMIN=0"
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
call npm run build
if errorlevel 1 exit /b 1
docker compose --env-file .local/services.env up -d --wait
if errorlevel 1 exit /b 1
start "Catfeedik API" cmd /k ".venv\Scripts\python.exe scripts\dev-api.py"
start "Catfeedik Worker" cmd /k ".venv\Scripts\python.exe scripts\dev-worker.py"
start "Catfeedik Web" cmd /k "npm run preview -- --host 127.0.0.1 --port 5174 --strictPort"
echo Open the HTTPS ngrok URL through the Telegram bot menu.
echo Test logins are disabled. Run ngrok http 5174 in another window.
echo Keep Docker Desktop and the three windows open. Close old servers before running this script.
