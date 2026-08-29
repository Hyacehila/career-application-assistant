#requires -Version 5.1
<#
.SYNOPSIS
    Run the simulated recruitment-page browser regression on an isolated DB.

.DESCRIPTION
    Starts a loopback-only FastAPI fixture on port 8000 with a temporary
    database, runs the Playwright flow, then stops the exact child process and
    removes the temporary database and test artifacts. It never reads or writes
    private/applications.sqlite.
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $repositoryRoot '.local\venv\Scripts\python.exe'
$mockServer = Join-Path $repositoryRoot 'app\tests\e2e\mock_server.py'
$frontendRoot = Join-Path $repositoryRoot 'app\frontend'
$healthUrl = 'http://127.0.0.1:8000/api/health'

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Write-Output 'FAIL: .local/venv is missing. Follow the README dependency setup first.'
    exit 1
}
if (-not (Test-Path -LiteralPath $mockServer -PathType Leaf)) {
    Write-Output 'FAIL: browser E2E fixture server is missing.'
    exit 1
}
if ($null -eq (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Output 'FAIL: pnpm is required.'
    exit 1
}
$portDeadline = (Get-Date).AddSeconds(2)
while (
    (Get-Date) -lt $portDeadline -and
    (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
) {
    Start-Sleep -Milliseconds 100
}
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output 'FAIL: port 8000 is already in use. Stop the local board service before running E2E.'
    exit 1
}

$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ("career-board-e2e-" + [Guid]::NewGuid().ToString('N'))
$fixtureRoot = [IO.Path]::GetFullPath($fixtureRoot)
$databasePath = Join-Path $fixtureRoot 'applications.sqlite'
$artifactPath = Join-Path $fixtureRoot 'playwright-output'
$serverProcess = $null
$testExitCode = 1

try {
    $null = New-Item -ItemType Directory -Path $fixtureRoot -Force
    $serverArguments = @(
        "`"$mockServer`"",
        '--database',
        "`"$databasePath`"",
        '--port',
        '8000'
    )
    $startParameters = @{
        FilePath = $pythonPath
        ArgumentList = $serverArguments
        WorkingDirectory = $repositoryRoot
        WindowStyle = 'Hidden'
        PassThru = $true
    }
    $serverProcess = Start-Process @startParameters

    $deadline = (Get-Date).AddSeconds(12)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        if ($serverProcess.HasExited) {
            break
        }
        try {
            $health = Invoke-RestMethod -Method Get -Uri $healthUrl -TimeoutSec 1
            if ($health.status -eq 'ok' -and $health.database -eq 'available') {
                $healthy = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 150
        }
    }
    if (-not $healthy) {
        throw 'E2E fixture server did not become healthy.'
    }

    $previousOutput = $env:BOARD_E2E_OUTPUT_DIR
    try {
        $env:BOARD_E2E_OUTPUT_DIR = $artifactPath
        & pnpm --dir $frontendRoot run test:e2e
        $testExitCode = $LASTEXITCODE
    } finally {
        $env:BOARD_E2E_OUTPUT_DIR = $previousOutput
    }
} catch {
    Write-Output "FAIL: $($_.Exception.Message)"
    $testExitCode = 1
} finally {
    if ($null -ne $serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        $null = $serverProcess.WaitForExit(5000)
    }

    $resolvedTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $safeFixturePath = (
        $fixtureRoot.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase) -and
        [IO.Path]::GetFileName($fixtureRoot).StartsWith('career-board-e2e-', [StringComparison]::Ordinal)
    )
    if ($safeFixturePath -and (Test-Path -LiteralPath $fixtureRoot)) {
        Remove-Item -LiteralPath $fixtureRoot -Recurse -Force
    }
}

if ($testExitCode -eq 0) {
    Write-Output 'RESULT: PASS - simulated recruitment Agent browser E2E'
}
exit $testExitCode
