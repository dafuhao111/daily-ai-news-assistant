[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $projectRoot 'backend'

if (-not (Test-Path -LiteralPath (Join-Path $backendDir '.env') -PathType Leaf)) {
    throw 'Missing backend/.env. Run scripts/setup.ps1 -PrepareOnly and complete local configuration first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/dist/index.html') -PathType Leaf)) {
    throw 'Missing frontend build. Complete scripts/setup.ps1 first.'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Missing uv. Install uv, reopen PowerShell and retry.'
}

Write-Host 'Starting http://127.0.0.1:8000/ with one worker. Keep this terminal open; Ctrl+C stops the server.'
Write-Host 'If scheduling and the saved subscription are enabled, startup may generate/send today''s missed brief.'
Push-Location -LiteralPath $backendDir
try {
    & uv run --locked python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
    if ($LASTEXITCODE -ne 0) {
        throw "Server stopped with exit $LASTEXITCODE. If port 8000 is occupied, check the existing service; do not start a second copy."
    }
} finally {
    Pop-Location
}
