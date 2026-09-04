#requires -Version 5.1
<#
.SYNOPSIS
    Pass bounded Outlook connector data to the fixed local board API.

.DESCRIPTION
    Starts the local service when necessary and exposes only the five Outlook
    connector run actions. Except for Start, request JSON is read from standard
    input so mail data never appears in process arguments or temporary files.
    Responses and failures are already structured and sanitized by the API.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Start', 'Headers', 'Messages', 'Complete', 'Fail')]
    [string] $Action,

    [ValidatePattern('^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')]
    [string] $RunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$baseUrl = 'http://127.0.0.1:8000'
$healthUrl = "$baseUrl/api/health"
$startScript = Join-Path $PSScriptRoot 'Start-BoardService.ps1'
$maximumInputCharacters = 4 * 1024 * 1024

function Test-BoardHealth {
    try {
        $health = Invoke-RestMethod -Method Get -Uri $healthUrl -TimeoutSec 2
        $modeAllowed = (
            $health.mode -eq 'standard' -or
            (
                $health.mode -eq 'test' -and
                $env:CAREER_APPLICATION_ASSISTANT_ALLOW_TEST_MODE -eq '1'
            )
        )
        return (
            $health.status -eq 'ok' -and
            $health.database -eq 'available' -and
            [int] $health.schema_version -eq 5 -and
            $health.service -eq 'career-application-assistant' -and
            $modeAllowed -and
            $health.mode -ne 'demo' -and
            $health.synthetic_data -eq $false -and
            $health.mail_ingestion -eq $true
        )
    } catch {
        return $false
    }
}

function Ensure-BoardService {
    if (Test-BoardHealth) {
        return
    }
    if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
        throw 'Board startup script is missing.'
    }
    $null = & $startScript
    if ($LASTEXITCODE -ne 0 -or -not (Test-BoardHealth)) {
        throw 'Board service could not be started or did not become healthy.'
    }
}

function Read-BoundedJsonObject {
    # One compact JSON document per invocation. ReadLine lets the orchestrator
    # stream through standard input without creating a file or using argv.
    if ([Console]::IsInputRedirected) {
        $inputText = [Console]::In.ReadLine()
    } else {
        if ($null -eq ('OutlookConnectorConsoleMode' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class OutlookConnectorConsoleMode
{
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
}
'@
        }

        $inputHandle = [OutlookConnectorConsoleMode]::GetStdHandle(-10)
        [uint32] $originalMode = 0
        if (-not [OutlookConnectorConsoleMode]::GetConsoleMode($inputHandle, [ref] $originalMode)) {
            throw 'Standard input privacy mode is unavailable.'
        }
        # Clear ENABLE_LINE_INPUT (0x2) as well as ENABLE_ECHO_INPUT (0x4).
        # This avoids the Windows console line-length ceiling for bounded JSON.
        $privateInputMode = $originalMode -band [uint32] 4294967289
        if (-not [OutlookConnectorConsoleMode]::SetConsoleMode($inputHandle, $privateInputMode)) {
            throw 'Standard input privacy mode could not be enabled.'
        }
        try {
            [Console]::Out.WriteLine('INPUT_READY')
            $builder = New-Object System.Text.StringBuilder
            while ($true) {
                $next = [Console]::In.Read()
                if ($next -lt 0) {
                    throw 'Standard input ended before the JSON object was complete.'
                }
                if ($next -eq 10 -or $next -eq 13) {
                    break
                }
                $null = $builder.Append([char] $next)
                if ($builder.Length -gt $maximumInputCharacters) {
                    throw 'Standard input exceeds the fixed size limit.'
                }
            }
            $inputText = $builder.ToString()
        } finally {
            $null = [OutlookConnectorConsoleMode]::SetConsoleMode($inputHandle, $originalMode)
        }
    }
    if ([string]::IsNullOrWhiteSpace($inputText)) {
        throw 'A JSON object is required on standard input.'
    }
    if ($inputText.Length -gt $maximumInputCharacters) {
        throw 'Standard input exceeds the fixed size limit.'
    }
    try {
        $parsed = $inputText | ConvertFrom-Json
    } catch {
        throw 'Standard input must be valid JSON.'
    }
    if ($null -eq $parsed -or $parsed -is [System.Array] -or $parsed -is [string]) {
        throw 'Standard input must be a JSON object.'
    }
    return $parsed
}

function Invoke-FixedJsonRequest {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [object] $Payload
    )

    $json = $Payload | ConvertTo-Json -Depth 8 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    try {
        $response = Invoke-WebRequest `
            -Method Post `
            -Uri "$baseUrl$Path" `
            -ContentType 'application/json; charset=utf-8' `
            -Body $bytes `
            -UseBasicParsing `
            -TimeoutSec 30
        return $response.Content | ConvertFrom-Json
    } catch {
        $status = $null
        if ($null -ne $_.Exception.Response) {
            try { $status = [int] $_.Exception.Response.StatusCode } catch { $status = $null }
        }
        $apiCode = 'request_failed'
        $apiMessage = 'Board API request failed.'
        if (-not [string]::IsNullOrWhiteSpace($_.ErrorDetails.Message)) {
            try {
                $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
                if ($errorBody.code) { $apiCode = [string] $errorBody.code }
                if ($errorBody.message) { $apiMessage = [string] $errorBody.message }
            } catch {
                # Keep the fixed fallback and never echo the submitted payload.
            }
        }
        $statusLabel = if ($null -eq $status) { 'unavailable' } else { [string] $status }
        throw "Board API error ($statusLabel, $apiCode): $apiMessage"
    }
}

function Write-BoundedResult {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Value
    )

    $json = $Value | ConvertTo-Json -Depth 8 -Compress
    if ([Console]::IsOutputRedirected) {
        [Console]::Out.WriteLine($json)
        return
    }

    # Keep every terminal frame below the console width so ConPTY cannot add
    # visual line wraps inside JSON. Connector responses contain only bounded
    # status/count fields and opaque temporary tokens, never mail content.
    $chunkSize = 60
    [int] $chunkCount = [Math]::Ceiling($json.Length / $chunkSize)
    for ($index = 0; $index -lt $chunkCount; $index++) {
        $start = $index * $chunkSize
        $length = [Math]::Min($chunkSize, $json.Length - $start)
        $chunk = $json.Substring($start, $length)
        [Console]::Out.WriteLine(('RESULT_CHUNK:{0:D4}:{1}' -f $index, $chunk))
    }
    [Console]::Out.WriteLine(('RESULT_END:{0}' -f $chunkCount))
}

try {
    Ensure-BoardService

    if ($Action -eq 'Start') {
        if ($PSBoundParameters.ContainsKey('RunId')) {
            throw 'RunId is not accepted for Start.'
        }
        $payload = [ordered]@{}
        $path = '/api/mail/outlook-connector/runs'
    } else {
        if ([string]::IsNullOrWhiteSpace($RunId)) {
            throw "RunId is required for $Action."
        }
        $payload = Read-BoundedJsonObject
        $suffix = $Action.ToLowerInvariant()
        $path = "/api/mail/outlook-connector/runs/$RunId/$suffix"
    }

    $result = Invoke-FixedJsonRequest -Path $path -Payload $payload
    Write-BoundedResult -Value $result
    exit 0
} catch {
    [Console]::Error.WriteLine("FAIL: $($_.Exception.Message)")
    exit 1
}
