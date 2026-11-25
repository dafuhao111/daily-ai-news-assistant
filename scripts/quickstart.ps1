[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $projectRoot 'backend'
$frontendDir = Join-Path $projectRoot 'frontend'
$rssPath = Join-Path $backendDir 'config/rss_sources.json'

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed (exit $LASTEXITCODE). Quick start stopped; fix the error and retry."
    }
}

foreach ($commandName in @('uv', 'node', 'npm.cmd')) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Missing command: $commandName. Install uv and Node.js 24 LTS, then reopen PowerShell."
    }
}

$nodeVersion = & node --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(\d+)\.(\d+)\.') {
    throw 'Unable to read the Node.js version.'
}
$nodeMajor = [int]$Matches[1]
$nodeMinor = [int]$Matches[2]
if (-not (($nodeMajor -eq 22 -and $nodeMinor -ge 12) -or $nodeMajor -eq 24 -or $nodeMajor -ge 26)) {
    throw 'Unsupported Node.js version. Install Node.js 24 LTS (or a version allowed by frontend/package.json).'
}

if (-not (Test-Path -LiteralPath $rssPath -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $backendDir 'config/rss_sources.example.json') -Destination $rssPath
}

Push-Location -LiteralPath $frontendDir
try {
    Invoke-Checked -Command 'npm.cmd' -Arguments @('ci')
    Invoke-Checked -Command 'npm.cmd' -Arguments @('run', 'build')
} finally {
    Pop-Location
}

$previousDatabaseUrl = $env:DATABASE_URL
$previousSchedulerEnabled = $env:SCHEDULER_ENABLED
$previousUvProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT
Push-Location -LiteralPath $backendDir
try {
    $env:DATABASE_URL = 'sqlite+pysqlite:///./data/quickstart.db'
    $env:SCHEDULER_ENABLED = 'false'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $backendDir '.venv-quickstart'
    New-Item -ItemType Directory -Force -Path 'data' | Out-Null

    Invoke-Checked -Command 'uv' -Arguments @('sync', '--locked', '--no-dev')
    Invoke-Checked -Command 'uv' -Arguments @('run', '--locked', 'python', '-m', 'alembic', 'upgrade', 'head')

    $budgetOutput = & uv run --locked python -m app.budget status
    if ($LASTEXITCODE -ne 0) {
        throw "uv budget status failed (exit $LASTEXITCODE). Quick start stopped."
    }
    try {
        $budget = ($budgetOutput -join "`n") | ConvertFrom-Json
    } catch {
        throw 'Could not read the local budget status. Quick start stopped without changing it.'
    }
    if (-not $budget.initialized) {
        Invoke-Checked -Command 'uv' -Arguments @(
            'run', '--locked', 'python', '-m', 'app.budget', 'initialize', '--limit', '1000000'
        )
    }

    Write-Host 'Quick start uses backend/data/quickstart.db and keeps scheduled email disabled.'
    Write-Host 'Open http://127.0.0.1:8000/; configure a model key in backend/.env to generate briefs.'
    Write-Host 'Keep this terminal open. Press Ctrl+C to stop the server.'
    & uv run --locked python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
    if ($LASTEXITCODE -ne 0) {
        throw "Server stopped with exit $LASTEXITCODE. If port 8000 is occupied, check the existing service."
    }
} finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:DATABASE_URL = $previousDatabaseUrl
    }
    if ($null -eq $previousSchedulerEnabled) {
        Remove-Item Env:SCHEDULER_ENABLED -ErrorAction SilentlyContinue
    } else {
        $env:SCHEDULER_ENABLED = $previousSchedulerEnabled
    }
    if ($null -eq $previousUvProjectEnvironment) {
        Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    } else {
        $env:UV_PROJECT_ENVIRONMENT = $previousUvProjectEnvironment
    }
    Pop-Location
}
