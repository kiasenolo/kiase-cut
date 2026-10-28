@echo off
rem Build KiaseCut into an executable on Windows: app-build-exec\kiasecut\kiasecut.exe (a
rem folder with the program and its Python, Qt, numpy... beside it, and the render engine in
rem engine\; copy the whole folder). What goes in: packaging\kiasecut.spec.
rem MLT and ffmpeg are not built in: the machine running it needs Kdenlive (or Shotcut)
rem installed, as when run from source - unless built with --bundle-mlt, which copies
rem Kdenlive's bin, lib\mlt and share\mlt into app-build-exec\kiasecut\mlt (several hundred MB).
rem   build_exec.bat [--bundle-mlt]
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.11+ from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
python -c "import PySide6,numpy,PIL,moderngl" 2>nul
if errorlevel 1 python -m pip install PySide6 numpy Pillow moderngl || goto :fail
python -c "import PyInstaller" 2>nul
if errorlevel 1 python -m pip install pyinstaller || goto :fail

set OUT=app-build-exec
set WORK=.cache\pyinstaller
if exist "%OUT%\kiasecut" rmdir /s /q "%OUT%\kiasecut"
if exist "%OUT%\kiasecut-engine" rmdir /s /q "%OUT%\kiasecut-engine"
if exist "%WORK%" rmdir /s /q "%WORK%"
python -m PyInstaller --noconfirm --clean --distpath "%OUT%" --workpath "%WORK%" ^
    packaging\kiasecut.spec || goto :fail
move "%OUT%\kiasecut-engine" "%OUT%\kiasecut\engine" >nul || goto :fail

if /i "%~1"=="--bundle-mlt" (
  if not exist "C:\Program Files\Kdenlive\bin\libmlt-7.dll" (
    echo Kdenlive not found in C:\Program Files\Kdenlive: nothing to bundle.
    goto :fail
  )
  echo Copying Kdenlive's MLT and ffmpeg...
  robocopy "C:\Program Files\Kdenlive\bin" "%OUT%\kiasecut\mlt\bin" /e /nfl /ndl /njh /njs >nul
  robocopy "C:\Program Files\Kdenlive\lib\mlt" "%OUT%\kiasecut\mlt\lib\mlt" /e /nfl /ndl /njh /njs >nul
  robocopy "C:\Program Files\Kdenlive\share\mlt" "%OUT%\kiasecut\mlt\share\mlt" /e /nfl /ndl /njh /njs >nul
) else (
  if not exist "C:\Program Files\Kdenlive\bin\libmlt-7.dll" if not exist "C:\Program Files\Shotcut\libmlt-7.dll" (
    echo Warning: neither Kdenlive nor Shotcut found here ^(needed to run it^)
  )
)
echo Built: %CD%\%OUT%\kiasecut\kiasecut.exe
pause
exit /b 0

:fail
echo Build failed (see above).
pause
exit /b 1
