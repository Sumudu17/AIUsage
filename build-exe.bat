@echo off
REM ===============================================================
REM   Build dist\AIUsage.exe - one self-contained file
REM
REM   Needs Python + PyInstaller on THIS machine only.  The .exe it
REM   produces needs neither on the machine that runs it.
REM ===============================================================

cd /d "%~dp0"
title AI Usage - Build exe

where py.exe >nul 2>&1
if %errorlevel% neq 0 (
    echo Python was not found. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing/updating PyInstaller...
py -m pip install --quiet --disable-pip-version-check --upgrade pyinstaller
if %errorlevel% neq 0 (
    echo Could not install PyInstaller.
    pause
    exit /b 1
)

echo.
echo Building...
py -m PyInstaller --noconfirm --clean AIUsage.spec
if %errorlevel% neq 0 (
    echo.
    echo BUILD FAILED - see the messages above.
    pause
    exit /b 1
)

echo.
echo ===============================================================
echo  Done:  dist\AIUsage.exe
echo  Copy that one file anywhere and double-click it.
echo ===============================================================
echo.
pause
