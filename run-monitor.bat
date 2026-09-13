@echo off
REM ---------------------------------------------------------------
REM  AI Usage - background monitor
REM
REM  Checks Claude and Codex on a schedule, caches the result in
REM  data\usage.json and pushes it to any running widget.
REM  Keep this window open (minimise it) while you want updates.
REM ---------------------------------------------------------------

cd /d "%~dp0"
title AI Usage - Monitor

where py.exe >nul 2>&1
if %errorlevel% equ 0 (
    py -m usage_service.monitor %*
    goto :done
)

where python.exe >nul 2>&1
if %errorlevel% equ 0 (
    python -m usage_service.monitor %*
    goto :done
)

echo.
echo Python was not found on this computer.
echo Install Python 3.9 or newer from https://www.python.org/downloads/
echo.

:done
echo.
pause
