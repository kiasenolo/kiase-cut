@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.11+ from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
python -c "import PySide6,numpy,PIL,moderngl" 2>nul
if errorlevel 1 python -m pip install PySide6 numpy Pillow moderngl
python -m kiasecut
pause
