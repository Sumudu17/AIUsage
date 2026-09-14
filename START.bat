@echo off
REM ===============================================================
REM   AI Usage - START
REM
REM   Double-click this to run the whole app:
REM     * the background monitor (windowless, logs to data\monitor.log)
REM     * the always-on-top usage card
REM
REM   Safe to click twice - anything already running is left alone.
REM   Close it all again with STOP.bat
REM ===============================================================

cd /d "%~dp0"
title AI Usage - Start

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\appctl.ps1" start
