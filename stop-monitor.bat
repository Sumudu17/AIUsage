@echo off
REM ---------------------------------------------------------------
REM  Stops a background monitor started by run-monitor-hidden.bat.
REM  (A monitor started by run-monitor.bat is stopped by closing its
REM  window or pressing Ctrl+C in it.)
REM ---------------------------------------------------------------

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | Where-Object { $_.CommandLine -like '*usage_service.monitor*' };" ^
  "if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('Stopped monitor (pid ' + $_.ProcessId + ')') } } else { Write-Host 'No background monitor is running.' }"

echo.
pause
