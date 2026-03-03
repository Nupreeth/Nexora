param(
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$runFile = Join-Path $root "run.py"
$logDir = Join-Path $root "tmp_logs"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment python not found at $venvPython"
}
if (-not (Test-Path $runFile)) {
    throw "run.py not found at $runFile"
}
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$appOut = Join-Path $logDir "app.out.log"
$appErr = Join-Path $logDir "app.err.log"
$cfOut = Join-Path $logDir "cloudflared.out.log"
$cfErr = Join-Path $logDir "cloudflared.err.log"

Remove-Item $appOut, $appErr, $cfOut, $cfErr -Force -ErrorAction SilentlyContinue

# Stop old cloudflared to avoid stale links.
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force

$listen = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING"
if (-not $listen) {
    Start-Process -FilePath $venvPython -ArgumentList $runFile -WorkingDirectory $root -RedirectStandardOutput $appOut -RedirectStandardError $appErr | Out-Null
    Start-Sleep -Seconds 4
}

$cloudflaredPath = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
if (-not (Test-Path $cloudflaredPath)) {
    throw "cloudflared not found at $cloudflaredPath"
}

Start-Process -FilePath $cloudflaredPath -ArgumentList "tunnel --url http://127.0.0.1:$Port --no-autoupdate" -RedirectStandardOutput $cfOut -RedirectStandardError $cfErr | Out-Null
Start-Sleep -Seconds 10

$lines = Get-Content $cfErr -ErrorAction SilentlyContinue
$urlLine = $lines | Where-Object { $_ -match "https://.*\.trycloudflare\.com" } | Select-Object -First 1

if (-not $urlLine) {
    Write-Host "Tunnel started, but URL not found yet. Check logs: $cfErr"
    exit 1
}

$url = [regex]::Match($urlLine, "https://[a-z0-9\-]+\.trycloudflare\.com").Value
Write-Host "Public URL: $url"
Write-Host "App local URL: http://127.0.0.1:$Port"
