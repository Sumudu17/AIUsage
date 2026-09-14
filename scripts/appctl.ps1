# ---------------------------------------------------------------
#  Start / stop helper for the AI Usage app.
#
#  Driven by START.bat and STOP.bat - you do not need to run this
#  directly, but you can:  powershell -File scripts\appctl.ps1 status
# ---------------------------------------------------------------
param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

# Both parts of the app are Python processes; we recognise them by what
# they were told to run rather than by a PID file, which can go stale.
function Get-AppProcesses {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='py.exe' OR Name='pyw.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -like '*usage_service.monitor*' -or
                $_.CommandLine -like '*widget.py*'
            )
        }
}

function Get-Part($proc) {
    if ($proc.CommandLine -like '*usage_service.monitor*') { 'monitor' } else { 'widget' }
}

# Launching through py.exe/pyw.exe leaves a launcher parent plus the real
# python child, both matching.  Keep only the top process of each pair so one
# running part is reported (and stopped) once.
function Get-AppLeaders {
    $all = @(Get-AppProcesses)
    $ids = @($all | ForEach-Object { $_.ProcessId })
    @($all | Where-Object { $ids -notcontains $_.ParentProcessId })
}

# pythonw runs without a console window; fall back through the launchers.
function Get-PythonW {
    foreach ($name in 'pythonw.exe', 'pyw.exe') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

switch ($Action) {

    'start' {
        $python = Get-PythonW
        if (-not $python) {
            Write-Host 'Python was not found on this computer.' -ForegroundColor Red
            Write-Host 'Install Python 3.9+ from https://www.python.org/downloads/'
            Write-Host 'and tick "Add Python to PATH" during setup.'
            exit 1
        }

        $running = @(Get-AppLeaders)
        $parts = @($running | ForEach-Object { Get-Part $_ })

        if ($parts -contains 'monitor') {
            Write-Host 'Monitor  : already running' -ForegroundColor DarkGray
        }
        else {
            Start-Process -FilePath $python `
                -ArgumentList '-m', 'usage_service.monitor', '--log', 'data\monitor.log' `
                -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
            Write-Host 'Monitor  : started' -ForegroundColor Green
        }

        if ($parts -contains 'widget') {
            Write-Host 'Widget   : already running' -ForegroundColor DarkGray
        }
        else {
            Start-Process -FilePath $python `
                -ArgumentList 'widget\widget.py' `
                -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
            Write-Host 'Widget   : started' -ForegroundColor Green
        }

        Write-Host ''
        Write-Host 'The card appears in the top-right corner of the screen.'
        Write-Host 'Monitor output goes to data\monitor.log'
        Write-Host 'Close everything again with STOP.bat'
    }

    'stop' {
        $running = @(Get-AppLeaders)
        if ($running.Count -eq 0) {
            Write-Host 'Nothing to stop - the app is not running.' -ForegroundColor DarkGray
            break
        }
        foreach ($proc in $running) {
            $part = Get-Part $proc
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
                Write-Host ("Stopped {0,-8} (pid {1})" -f $part, $proc.ProcessId) -ForegroundColor Yellow
            }
            catch {
                Write-Host ("Could not stop {0} (pid {1}): {2}" -f $part, $proc.ProcessId, $_.Exception.Message) -ForegroundColor Red
            }
        }

        # A launcher parent takes its python child with it, but tidy up any
        # child that outlived its parent.  Already-gone pids are not errors.
        Start-Sleep -Milliseconds 500
        foreach ($proc in @(Get-AppProcesses)) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Write-Host 'Closed.' -ForegroundColor Yellow
    }

    'status' {
        $running = @(Get-AppLeaders)
        if ($running.Count -eq 0) {
            Write-Host 'Not running.'
        }
        else {
            foreach ($proc in $running) {
                Write-Host ("{0,-8} running (pid {1})" -f (Get-Part $proc), $proc.ProcessId)
            }
        }
    }
}

# Give a double-clicked window a moment to be read before it closes.
if ($Action -ne 'status') { Start-Sleep -Seconds 3 }
