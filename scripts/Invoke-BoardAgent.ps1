#requires -Version 5.1
<#
.SYNOPSIS
    Safely write Agent workflow results to the local application board.

.DESCRIPTION
    Provides two typed actions for Codex and other local Agents:
      - FillCompleted: create or idempotently refresh a pending-review record.
      - StatusUpdate: append a validated status event using an exact record ID
        or the documented metadata matching rules.

    The script always targets http://127.0.0.1:8000, checks /api/health, and
    invokes Start-BoardService.ps1 when the service is unavailable. It accepts
    no raw JSON, database path, alternate host, or arbitrary endpoint.

    Standard output contains only a compact JSON result with record/event IDs
    and statuses. It never prints candidate materials or request payloads.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('FillCompleted', 'StatusUpdate')]
    [string] $Action,

    [ValidateRange(1, [long]::MaxValue)]
    [long] $ApplicationId,
    [string] $CompanyName,
    [string] $JobTitle,
    [string] $Department,
    [string] $JobCode,
    [ValidateSet('实习', '校招', '社招', '其他')]
    [string] $ApplicationType,
    [string] $Location,
    [string] $JobSource,
    [string] $JobUrl,
    [string] $FilledAt,

    [ValidateSet(
        'pending_review', 'applied', 'assessment',
        'interview_1', 'interview_2', 'interview_3', 'interview_hr',
        'offer', 'rejected', 'withdrawn'
    )]
    [string] $Stage,
    [string] $EventDate,
    [string] $ScheduledDate,
    [string] $ScheduledTime,
    [string] $DeadlineDate,
    [string] $DeadlineTime,
    [ValidateSet('user_confirmation', 'email_extract')]
    [string] $EventSource,
    [ValidateSet('online', 'offline', 'phone', 'unknown')]
    [string] $Mode,
    [string] $EventLocation,
    [string] $Note
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$baseUrl = 'http://127.0.0.1:8000'
$healthUrl = "$baseUrl/api/health"
$startScript = Join-Path $PSScriptRoot 'Start-BoardService.ps1'

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

function Add-OptionalValue {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary] $Target,
        [Parameter(Mandatory = $true)]
        [string] $Name,
        [AllowNull()]
        [object] $Value
    )

    if ($null -eq $Value) {
        return
    }
    if ($Value -is [string] -and [string]::IsNullOrWhiteSpace($Value)) {
        return
    }
    $Target[$Name] = if ($Value -is [string]) { $Value.Trim() } else { $Value }
}

function Assert-RequiredText {
    param(
        [AllowNull()]
        [string] $Value,
        [Parameter(Mandatory = $true)]
        [string] $Name
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name is required for $Action."
    }
}

function Assert-IsoDate {
    param(
        [AllowNull()]
        [string] $Value,
        [Parameter(Mandatory = $true)]
        [string] $Name,
        [switch] $Required
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        if ($Required) {
            throw "$Name is required for $Action."
        }
        return
    }
    try {
        $null = [DateTime]::ParseExact(
            $Value,
            'yyyy-MM-dd',
            [Globalization.CultureInfo]::InvariantCulture
        )
    } catch {
        throw "$Name must be a valid ISO date (YYYY-MM-DD)."
    }
}

function Get-ShanghaiTimestamp {
    $zone = $null
    foreach ($zoneId in @('China Standard Time', 'Asia/Shanghai')) {
        try {
            $zone = [TimeZoneInfo]::FindSystemTimeZoneById($zoneId)
            break
        } catch {
            continue
        }
    }
    if ($null -eq $zone) {
        throw 'Asia/Shanghai timezone is unavailable.'
    }
    return [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $zone).ToString('yyyy-MM-ddTHH:mm:sszzz')
}

function Invoke-BoardJson {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary] $Body
    )

    $json = $Body | ConvertTo-Json -Depth 6 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    try {
        $requestParameters = @{
            Method = 'Post'
            Uri = "$baseUrl$Path"
            ContentType = 'application/json; charset=utf-8'
            Body = $bytes
            UseBasicParsing = $true
            TimeoutSec = 10
        }
        $response = Invoke-WebRequest @requestParameters
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
                # Keep the fixed, non-sensitive fallback message.
            }
        }
        $statusLabel = if ($null -eq $status) { 'unavailable' } else { [string] $status }
        throw "Board API error ($statusLabel, $apiCode): $apiMessage"
    }
}

try {
    Ensure-BoardService

    if ($Action -eq 'FillCompleted') {
        Assert-RequiredText -Value $CompanyName -Name 'CompanyName'
        Assert-RequiredText -Value $JobTitle -Name 'JobTitle'

        $payload = [ordered]@{
            company_name = $CompanyName.Trim()
            job_title = $JobTitle.Trim()
            filled_at = if ([string]::IsNullOrWhiteSpace($FilledAt)) {
                Get-ShanghaiTimestamp
            } else {
                $FilledAt.Trim()
            }
        }
        Add-OptionalValue -Target $payload -Name 'department' -Value $Department
        Add-OptionalValue -Target $payload -Name 'job_code' -Value $JobCode
        Add-OptionalValue -Target $payload -Name 'application_type' -Value $ApplicationType
        Add-OptionalValue -Target $payload -Name 'location' -Value $Location
        Add-OptionalValue -Target $payload -Name 'source' -Value $JobSource
        Add-OptionalValue -Target $payload -Name 'job_url' -Value $JobUrl

        $response = Invoke-BoardJson -Path '/api/agent/fill-completed' -Body $payload
        [ordered]@{
            ok = $true
            action = 'fill_completed'
            application_id = [long] $response.id
            current_status = [string] $response.current_status
        } | ConvertTo-Json -Compress
        exit 0
    }

    Assert-RequiredText -Value $Stage -Name 'Stage'
    Assert-IsoDate -Value $EventDate -Name 'EventDate' -Required
    Assert-RequiredText -Value $EventSource -Name 'EventSource'
    Assert-IsoDate -Value $ScheduledDate -Name 'ScheduledDate'
    Assert-IsoDate -Value $DeadlineDate -Name 'DeadlineDate'

    if ($Stage -eq 'applied' -and $EventSource -ne 'user_confirmation') {
        throw 'The applied stage requires EventSource=user_confirmation.'
    }
    if ($Stage -eq 'assessment' -and [string]::IsNullOrWhiteSpace($ScheduledDate) -and [string]::IsNullOrWhiteSpace($DeadlineDate)) {
        throw 'The assessment stage requires ScheduledDate or DeadlineDate.'
    }
    if ($Stage -match '^interview_' -and [string]::IsNullOrWhiteSpace($ScheduledDate)) {
        throw 'Interview stages require ScheduledDate.'
    }
    if (-not [string]::IsNullOrWhiteSpace($ScheduledTime) -and [string]::IsNullOrWhiteSpace($ScheduledDate)) {
        throw 'ScheduledTime requires ScheduledDate.'
    }
    if (-not [string]::IsNullOrWhiteSpace($DeadlineTime) -and [string]::IsNullOrWhiteSpace($DeadlineDate)) {
        throw 'DeadlineTime requires DeadlineDate.'
    }

    $match = [ordered]@{}
    if ($PSBoundParameters.ContainsKey('ApplicationId')) {
        $match['application_id'] = $ApplicationId
    }
    Add-OptionalValue -Target $match -Name 'company_name' -Value $CompanyName
    Add-OptionalValue -Target $match -Name 'job_title' -Value $JobTitle
    Add-OptionalValue -Target $match -Name 'job_code' -Value $JobCode
    Add-OptionalValue -Target $match -Name 'location' -Value $Location
    Add-OptionalValue -Target $match -Name 'job_url' -Value $JobUrl

    $hasId = $match.Contains('application_id')
    $hasUrl = $match.Contains('job_url')
    $hasCompanyCode = $match.Contains('company_name') -and $match.Contains('job_code')
    $hasCompanyTitleLocation = (
        $match.Contains('company_name') -and
        $match.Contains('job_title') -and
        $match.Contains('location')
    )
    if (-not ($hasId -or $hasUrl -or $hasCompanyCode -or $hasCompanyTitleLocation)) {
        throw 'StatusUpdate requires ApplicationId, JobUrl, CompanyName+JobCode, or CompanyName+JobTitle+Location.'
    }

    $event = [ordered]@{
        stage = $Stage
        event_date = $EventDate
        source = $EventSource
    }
    Add-OptionalValue -Target $event -Name 'scheduled_date' -Value $ScheduledDate
    Add-OptionalValue -Target $event -Name 'scheduled_time' -Value $ScheduledTime
    Add-OptionalValue -Target $event -Name 'deadline_date' -Value $DeadlineDate
    Add-OptionalValue -Target $event -Name 'deadline_time' -Value $DeadlineTime
    Add-OptionalValue -Target $event -Name 'mode' -Value $Mode
    Add-OptionalValue -Target $event -Name 'location' -Value $EventLocation
    Add-OptionalValue -Target $event -Name 'note' -Value $Note

    $payload = [ordered]@{ match = $match; event = $event }
    $response = Invoke-BoardJson -Path '/api/agent/status-update' -Body $payload
    [ordered]@{
        ok = $true
        action = 'status_update'
        application_id = [long] $response.application.id
        current_status = [string] $response.application.current_status
        event_id = [long] $response.event.id
        event_stage = [string] $response.event.stage
    } | ConvertTo-Json -Compress
    exit 0
} catch {
    [Console]::Error.WriteLine("FAIL: $($_.Exception.Message)")
    exit 1
}
