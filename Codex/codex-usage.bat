@echo off
setlocal
title Codex CLI - Usage

where codex >nul 2>&1
if errorlevel 1 (
    echo ERROR: "codex" command was not found in PATH.
    echo Make sure the Codex CLI is installed and accessible from cmd.
    echo.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0codex-usage.ps1"

echo.
pause
endlocal
