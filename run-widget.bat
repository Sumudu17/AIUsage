@echo off
REM ---------------------------------------------------------------
REM  AI Usage - desktop widget
REM
REM  Starts the always-on-top card without leaving a console window.
REM  The monitor (run-monitor.bat) supplies its data; the widget still
REM  starts and shows cached values if the monitor is not running.
REM ---------------------------------------------------------------

cd /d "%~dp0"

where pythonw.exe >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw.exe "widget\widget.py"
    exit /b
)

where pyw.exe >nul 2>&1
if %errorlevel% equ 0 (
    start "" pyw.exe "widget\widget.py"
    exit /b
)

where py.exe >nul 2>&1
if %errorlevel% equ 0 (
    start "" py.exe "widget\widget.py"
    exit /b
)

echo.
echo Python was not found on this computer.
echo Install Python 3.9 or newer from https://www.python.org/downloads/
echo.
pause
