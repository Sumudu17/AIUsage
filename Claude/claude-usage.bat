@echo off
setlocal
title Claude Code - Usage

echo ================================================
echo   Claude Code - Current Usage
echo ================================================
echo.

where claude >nul 2>&1
if errorlevel 1 (
    echo ERROR: "claude" command was not found in PATH.
    echo Make sure Claude Code CLI is installed and accessible from cmd.
    echo.
    pause
    exit /b 1
)

claude -p "/usage" --output-format text
set "EXITCODE=%ERRORLEVEL%"

echo.
echo ================================================
if "%EXITCODE%"=="0" (
    echo Done.
) else (
    echo Claude exited with error code %EXITCODE%.
    echo If this keeps happening, run "claude -p /usage" manually to see the full error.
)
echo ================================================
echo.
pause
endlocal
