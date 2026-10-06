@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BRV Sglypa Smart Moderator

where py >nul 2>nul
if errorlevel 1 (
  set PY=python
) else (
  set PY=py
)

if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install -q -r requirements.txt

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo Открылся .env. Вставь BOT_TOKEN и OWNER_ID.
  notepad .env
  pause
  exit /b
)

python main.py
pause
