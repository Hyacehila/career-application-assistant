#requires -Version 5.1
<#
.SYNOPSIS
    Start the local career-application board service if it is not already running.

.DESCRIPTION
    Performs a fixed, minimal behavior contract:
      1. Calls /api/health. If healthy, returns success immediately.
      2. Otherwise launches the local service in a hidden window, pinned to the
         repository root working directory.
      3. Polls /api/health for up to ~10 seconds.
      4. Emits a status line that contains no personal data.
      5. Returns a non-zero exit code on failure.
    It never installs dependencies, never downloads content, and never deletes files.
    It accepts no database path argument.
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repositoryRoot

$baseUrl = 'http://127.0.0.1:8000'
$healthUrl = "$baseUrl/api/health"

# Prefer the repository-local uv virtualenv interpreter, falling back to PATH python.
$preferredPython = Join-Path $repositoryRoot '.local\venv\Scripts\python.exe'
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonCandidate = if (Test-Path -LiteralPath $preferredPython) {
    $preferredPython
} elseif ($null -ne $pythonCommand) {
    $pythonCommand.Source
} else {
    $null
}
if ([string]::IsNullOrWhiteSpace($pythonCandidate)) {
    Write-Output 'FAIL: no python interpreter found. Create .local\venv with uv first.'
    exit 1
}

function Test-ServiceHealthy {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -ne 200) {
            return $false
        }
        $health = $response.Content | ConvertFrom-Json
        return (
            $health.status -eq 'ok' -and
            $health.database -eq 'available' -and
            $health.schema_version -eq 5 -and
            $health.service -eq 'career-application-assistant' -and
            $health.mode -eq 'standard' -and
            $health.synthetic_data -eq $false -and
            $health.mail_ingestion -eq $true
        )
    } catch {
        return $false
    }
}

# 1-2. If already healthy, succeed without launching anything.
if (Test-ServiceHealthy) {
    Write-Output 'OK: board service already running at http://127.0.0.1:8000'
    exit 0
}

if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output 'FAIL: port 8000 is occupied by a service that is not the standard Career Application Assistant.'
    exit 1
}

# 3. Launch the service in a hidden window pinned to the repository root.
$serverScript = Join-Path $repositoryRoot 'app\server.py'
if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf)) {
    Write-Output 'FAIL: server entry point is missing.'
    exit 1
}

$process = Start-Process -FilePath $pythonCandidate -ArgumentList "`"$serverScript`"" -WorkingDirectory $repositoryRoot -WindowStyle Hidden -PassThru

# 5. Poll for up to ~10 seconds.
$deadline = (Get-Date).AddSeconds(10)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    if (-not $process.HasExited) {
        if (Test-ServiceHealthy) {
            $healthy = $true
            break
        }
    } else {
        break
    }
    Start-Sleep -Milliseconds 500
}

if ($healthy) {
    Write-Output "OK: board service started at http://127.0.0.1:8000 (pid $($process.Id))"
    exit 0
}

# 8. Failure path: report and exit non-zero. Clean up the child we started.
if (-not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
Write-Output 'FAIL: board service did not become healthy within 10 seconds.'
exit 1
