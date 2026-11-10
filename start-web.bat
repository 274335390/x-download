@echo off
cd /d "%~dp0"
if exist "Dongdong.exe" (
  start "" "Dongdong.exe" --web
) else if exist "release\Dongdong.exe" (
  start "" "release\Dongdong.exe" --web
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py --web
) else (
  echo Please run Dongdong.exe or install the Python dependencies first.
  pause
)
