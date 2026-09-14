@echo off
REM ===============================================================
REM   AI Usage - STOP
REM
REM   Double-click this to close the app: both the usage card and
REM   the background monitor.
REM
REM   Start it again with START.bat
REM ===============================================================

cd /d "%~dp0"
title AI Usage - Stop

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\appctl.ps1" stop
