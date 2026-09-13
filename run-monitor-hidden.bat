@echo off
REM ---------------------------------------------------------------
REM  AI Usage - background monitor, no console window
REM
REM  Same as run-monitor.bat but runs windowless, writing its output
REM  to data\monitor.log instead of a console.  Use this one for
REM  everyday running (or put a shortcut to it in your Startup
REM  folder); use run-monitor.bat when you want to watch it work.
REM
REM  Stop it from Task Manager (pythonw.exe) or by running:
REM      stop-monitor.bat
REM ---------------------------------------------------------------

cd /d "%~dp0"

where pythonw.exe >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw.exe -m usage_service.monitor --log data\monitor.log
    echo Monitor started in the background. Output: data\monitor.log
    exit /b
)

where pyw.exe >nul 2>&1
if %errorlevel% equ 0 (
    start "" pyw.exe -m usage_service.monitor --log data\monitor.log
    echo Monitor started in the background. Output: data\monitor.log
    exit /b
)

echo.
echo Python was not found on this computer.
echo Install Python 3.9 or newer from https://www.python.org/downloads/
echo.
pause
