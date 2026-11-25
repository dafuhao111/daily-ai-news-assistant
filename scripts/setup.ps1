[CmdletBinding()]
param([switch]$PrepareOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $projectRoot 'backend'
$frontendDir = Join-Path $projectRoot 'frontend'
$envPath = Join-Path $backendDir '.env'
$rssPath = Join-Path $backendDir 'config/rss_sources.json'

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed (exit $LASTEXITCODE). Setup stopped; fix the error and retry."
    }
}

$createdEnv = $false
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $backendDir '.env.example') -Destination $envPath
    $createdEnv = $true
    Write-Host 'Created backend/.env from the example. Existing configuration is never overwritten.'
}
if (-not (Test-Path -LiteralPath $rssPath -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $backendDir 'config/rss_sources.example.json') -Destination $rssPath
    Write-Host 'Created the local RSS source configuration.'
}
if ($PrepareOnly -or $createdEnv) {
    Write-Host 'Edit backend/.env, create your MySQL database/account, then run this script again without -PrepareOnly.'
    Write-Host 'See backend/README.md for MySQL setup. No dependencies, migrations, model calls or email sends were executed.'
    return
}

foreach ($commandName in @('uv', 'node', 'npm.cmd')) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Missing command: $commandName. Install uv and Node.js 24 LTS, reopen PowerShell, then retry."
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

Push-Location -LiteralPath $frontendDir
try {
    Invoke-Checked -Command 'npm.cmd' -Arguments @('ci')
    Invoke-Checked -Command 'npm.cmd' -Arguments @('run', 'build')
} finally {
    Pop-Location
}
Push-Location -LiteralPath $backendDir
try {
    Invoke-Checked -Command 'uv' -Arguments @('sync', '--locked')
    Invoke-Checked -Command 'uv' -Arguments @('run', '--locked', 'python', '-m', 'alembic', 'upgrade', 'head')
} finally {
    Pop-Location
}
Write-Host 'Dependencies, frontend build and database migrations completed.'
Write-Host 'For a NEW database only, initialize the Token budget as documented in backend/README.md.'
Write-Host 'Then run scripts/start.ps1. Setup does not initialize/reset budgets, start scheduling or send email.'
