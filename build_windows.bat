@echo off
REM ============================================================
REM  Build the Windows app for 图片命名压字 (Smart Name Stamp).
REM  Run this ON A WINDOWS PC that has Python 3.10-3.13 installed.
REM  Just double-click this file, or run it from a Command Prompt.
REM ============================================================
setlocal

cd /d "%~dp0"

echo.
echo === [1/4] Checking Python ===
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    echo Please install Python 3.11 from https://www.python.org/downloads/windows/
    echo During install, tick "Add python.exe to PATH".
    pause
    exit /b 1
)
python --version

echo.
echo === [2/4] Creating build environment (.venv-build) ===
if not exist ".venv-build\Scripts\python.exe" (
    python -m venv .venv-build
)
call ".venv-build\Scripts\python.exe" -m pip install --upgrade pip
call ".venv-build\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 (
    echo Dependency install failed.
    pause
    exit /b 1
)

echo.
echo === [3/4] Building with PyInstaller ===
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
call ".venv-build\Scripts\pyinstaller.exe" --noconfirm SmartNameStamp.spec
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo === [4/4] Done ===
echo The app is here:  dist\SmartNameStamp\SmartNameStamp.exe
echo Send the whole "dist\SmartNameStamp" folder (zip it) to others.
echo They unzip it and double-click SmartNameStamp.exe to run.
echo.
pause
endlocal
