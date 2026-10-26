@echo off
rem Update KiaseCut: pull the latest version from GitHub into this folder (fast-forward only,
rem so local changes are never merged over). The next start_kiasecut.bat installs missing packages.
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
  echo git not found. Install Git for Windows from git-scm.com.
  pause
  exit /b 1
)
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo This folder is not a git checkout. Get KiaseCut with:
  echo   git clone https://github.com/kiasenolo/kiase-cut
  pause
  exit /b 1
)
for /f %%h in ('git rev-parse HEAD') do set BEFORE=%%h
git pull --ff-only
if errorlevel 1 (
  echo Update failed ^(see above^). Changes made in this folder can block it: git status lists them.
  pause
  exit /b 1
)
for /f %%h in ('git rev-parse HEAD') do set AFTER=%%h
if not "%BEFORE%"=="%AFTER%" (
  echo New in this update:
  git log --oneline %BEFORE%..%AFTER%
)
pause
