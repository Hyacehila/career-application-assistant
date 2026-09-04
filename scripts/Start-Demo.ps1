#requires -Version 5.1

[CmdletBinding()]
param(
    [switch] $Reset
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$baseUrl = 'http://127.0.0.1:8001'
$healthUrl = "$baseUrl/api/health"
$resetUrl = "$baseUrl/api/demo/reset"

function Test-DemoHealth {
    try {
        $health = Invoke-RestMethod -Method Get -Uri $healthUrl -TimeoutSec 2
        return (
            $health.status -eq 'ok' -and
            $health.database -eq 'available' -and
            [int] $health.schema_version -eq 6 -and
            $health.service -eq 'career-application-assistant' -and
            $health.mode -eq 'demo' -and
            $health.synthetic_data -eq $true -and
            $health.mail_ingestion -eq $false
        )
    } catch {
        return $false
    }
}

if ($Reset) {
    if (-not (Test-DemoHealth)) {
        Write-Output 'FAIL: no healthy Career Application Assistant Demo is running at http://127.0.0.1:8001.'
        exit 1
    }

    try {
        $result = Invoke-RestMethod -Method Post -Uri $resetUrl -ContentType 'application/json; charset=utf-8' -Body '{}' -TimeoutSec 10
        if ($result.ok -ne $true -or [int] $result.records_seeded -ne 6) {
            throw 'The Demo reset response did not match the expected contract.'
        }
        Write-Output 'RESULT: PASS - Demo reset to 6 synthetic records.'
        exit 0
    } catch {
        Write-Output 'FAIL: Demo reset failed.'
        exit 1
    }
}

if (Test-DemoHealth) {
    Write-Output 'OK: Career Application Assistant Demo is already running at http://127.0.0.1:8001'
    exit 0
}

if (Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output 'FAIL: port 8001 is occupied by an unknown service.'
    exit 1
}

$preferredPython = Join-Path $repositoryRoot '.local\venv\Scripts\python.exe'
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonCandidate = if (Test-Path -LiteralPath $preferredPython -PathType Leaf) {
    $preferredPython
} elseif ($null -ne $pythonCommand) {
    $pythonCommand.Source
} else {
    $null
}
if ([string]::IsNullOrWhiteSpace($pythonCandidate)) {
    Write-Output 'FAIL: no Python interpreter is available.'
    exit 1
}

$frontendRoot = Join-Path $repositoryRoot 'app\frontend'
$frontendEntry = Join-Path $frontendRoot 'dist\index.html'
if (-not (Test-Path -LiteralPath $frontendEntry -PathType Leaf)) {
    if ($null -eq (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        Write-Output 'FAIL: the frontend production build is missing and pnpm is unavailable.'
        exit 1
    }
    & pnpm --dir $frontendRoot build
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $frontendEntry -PathType Leaf)) {
        Write-Output 'FAIL: the frontend production build could not be created.'
        exit 1
    }
}

$serverScript = Join-Path $repositoryRoot 'app\demo_server.py'
if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf)) {
    Write-Output 'FAIL: Demo server entry point is missing.'
    exit 1
}

Set-Location -LiteralPath $repositoryRoot
Write-Output 'Demo running at http://127.0.0.1:8001 - press Ctrl+C to stop and remove its temporary session.'
& $pythonCandidate $serverScript
$serverExitCode = $LASTEXITCODE
if ($serverExitCode -ne 0) {
    Write-Output 'FAIL: Demo server exited with an error.'
}
exit $serverExitCode
