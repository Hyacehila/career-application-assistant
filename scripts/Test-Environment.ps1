#requires -Version 5.1

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Standard', 'Demo')]
    [string] $Mode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:FailureCount = 0

function Write-CheckResult {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,
        [Parameter(Mandatory = $true)]
        [bool] $Passed
    )

    if ($Passed) {
        Write-Output "PASS: $Name"
    } else {
        $script:FailureCount += 1
        Write-Output "FAIL: $Name"
    }
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $repositoryRoot '.local\venv\Scripts\python.exe'
$frontendRoot = Join-Path $repositoryRoot 'app\frontend'
$frontendModules = Join-Path $frontendRoot 'node_modules'
$frontendBuild = Join-Path $frontendRoot 'dist\index.html'
$materialsPath = Join-Path $repositoryRoot 'private\resume_materials.md'
$port = if ($Mode -eq 'Demo') { 8001 } else { 8000 }
$expectedMode = $Mode.ToLowerInvariant()

Write-CheckResult -Name 'powershell' -Passed ($PSVersionTable.PSVersion -ge [Version]'5.1')

$pythonReady = $false
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -ne $pythonCommand) {
    & $pythonCommand.Source -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' *> $null
    $pythonReady = $LASTEXITCODE -eq 0
}
Write-CheckResult -Name 'python' -Passed $pythonReady

$uvReady = $false
if ($null -ne (Get-Command uv -ErrorAction SilentlyContinue)) {
    & uv --version *> $null
    $uvReady = $LASTEXITCODE -eq 0
}
Write-CheckResult -Name 'uv' -Passed $uvReady

$pnpmReady = $false
if ($null -ne (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    $pnpmVersion = (& pnpm --version 2>$null | Select-Object -First 1)
    if ($LASTEXITCODE -eq 0 -and $pnpmVersion -match '^(?<major>\d+)\.') {
        $pnpmReady = [int] $Matches.major -ge 10
    }
}
Write-CheckResult -Name 'pnpm' -Passed $pnpmReady
Write-CheckResult -Name 'local-virtual-environment' -Passed (Test-Path -LiteralPath $venvPython -PathType Leaf)

$backendImportPassed = $false
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = (Join-Path $repositoryRoot 'app')
        & $venvPython -c 'from backend.app import create_app, create_demo_app, create_test_app' *> $null
        $backendImportPassed = $LASTEXITCODE -eq 0
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
}
Write-CheckResult -Name 'backend-import' -Passed $backendImportPassed

Write-CheckResult -Name 'frontend-dependencies' -Passed (Test-Path -LiteralPath $frontendModules -PathType Container)
Write-CheckResult -Name 'frontend-production-build' -Passed (Test-Path -LiteralPath $frontendBuild -PathType Leaf)

$privateOverlayReady = if ($Mode -eq 'Standard') {
    Test-Path -LiteralPath $materialsPath -PathType Leaf
} else {
    $true
}
Write-CheckResult -Name 'private-overlay-requirement' -Passed $privateOverlayReady

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
$portReady = $null -eq $listener
if (-not $portReady) {
    try {
        $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 2
        $portReady = (
            $health.status -eq 'ok' -and
            $health.service -eq 'career-application-assistant' -and
            $health.mode -eq $expectedMode
        )
    } catch {
        $portReady = $false
    }
}
Write-CheckResult -Name "loopback-port-$port" -Passed $portReady

if ($script:FailureCount -eq 0) {
    Write-Output 'RESULT: PASS'
    exit 0
}

Write-Output "RESULT: FAIL ($($script:FailureCount) checks)"
exit 1
