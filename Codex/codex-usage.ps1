$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

Set-Location -Path $PSScriptRoot

Write-Host "================================================"
Write-Host "  Codex CLI - Current Usage"
Write-Host "================================================"
Write-Host ""
Write-Host "Codex CLI has no direct non-interactive usage command yet," -ForegroundColor Yellow
Write-Host "so this starts the interactive session and auto-types /status." -ForegroundColor Yellow
Write-Host "If it does not appear below in a few seconds, type /status and press Enter." -ForegroundColor Yellow
Write-Host ""

$codexCmd = Get-Command "codex.cmd" -ErrorAction SilentlyContinue
if (-not $codexCmd) {
    Write-Host "ERROR: codex.cmd was not found in PATH." -ForegroundColor Red
    Write-Host "Make sure the Codex CLI (npm i -g @openai/codex) is installed and on PATH."
    Read-Host "Press Enter to close"
    exit 1
}

$proc = Start-Process -FilePath $codexCmd.Source `
    -ArgumentList @("--no-alt-screen", "--ask-for-approval", "never", "--sandbox", "read-only") `
    -NoNewWindow -PassThru

# Give the TUI a moment to initialize, then dismiss any first-run/trust
# prompt with Enter before typing the status command.
Start-Sleep -Seconds 3
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
Start-Sleep -Seconds 2
[System.Windows.Forms.SendKeys]::SendWait("/status")
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")

# Leave the session running so the user can read the result; the window
# stays open until they exit Codex themselves (Ctrl+C or /quit).
Wait-Process -Id $proc.Id -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "================================================"
Write-Host "Codex session ended."
Write-Host "================================================"
