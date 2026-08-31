#requires -Version 5.1

[CmdletBinding()]
param(
    [string] $WorkspaceRoot,
    [switch] $InitializeResumeHash
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
        return
    }

    $script:FailureCount += 1
    Write-Output "FAIL: $Name"
}

function ConvertTo-DateKey {
    param(
        [AllowEmptyString()]
        [string] $Value
    )

    $trimmedValue = if ($null -eq $Value) { '' } else { $Value.Trim() }
    if ([string]::IsNullOrWhiteSpace($trimmedValue)) {
        return [pscustomobject]@{ Valid = $true; Comparable = $false; Key = [int64]0 }
    }

    if ($trimmedValue -eq '至今') {
        return [pscustomobject]@{ Valid = $true; Comparable = $true; Key = [int64]::MaxValue }
    }

    if ($trimmedValue -notmatch '^(?<year>\d{4})(?:-(?<month>\d{1,2}))?$') {
        return [pscustomobject]@{ Valid = $false; Comparable = $false; Key = [int64]0 }
    }

    $year = [int]$Matches.year
    $month = if ([string]::IsNullOrWhiteSpace($Matches.month)) { 0 } else { [int]$Matches.month }
    if ($month -lt 0 -or $month -gt 12) {
        return [pscustomobject]@{ Valid = $false; Comparable = $false; Key = [int64]0 }
    }

    return [pscustomobject]@{ Valid = $true; Comparable = $true; Key = [int64]($year * 100 + $month) }
}

function Compare-RecordOrder {
    param(
        [Parameter(Mandatory = $true)] $Left,
        [Parameter(Mandatory = $true)] $Right
    )

    if ($Left.End.Comparable -ne $Right.End.Comparable) {
        return $(if ($Left.End.Comparable) { 1 } else { -1 })
    }
    if ($Left.End.Comparable -and $Left.End.Key -ne $Right.End.Key) {
        return $(if ($Left.End.Key -gt $Right.End.Key) { 1 } else { -1 })
    }
    if ($Left.Start.Comparable -ne $Right.Start.Comparable) {
        return $(if ($Left.Start.Comparable) { 1 } else { -1 })
    }
    if ($Left.Start.Comparable -and $Left.Start.Key -ne $Right.Start.Key) {
        return $(if ($Left.Start.Key -gt $Right.Start.Key) { 1 } else { -1 })
    }
    return 0
}

function Get-DeclaredAttachment {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Text,

        [Parameter(Mandatory = $true)]
        [string] $Label
    )

    $pattern = '(?m)^-[ \t]*' + [regex]::Escape($Label) + '[：:][ \t]*(?<path>[^\r\n]+)'
    $match = [regex]::Match($Text, $pattern)
    if (-not $match.Success) {
        return $null
    }
    return $match.Groups['path'].Value.Trim()
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$workspacePath = if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    Join-Path $repositoryRoot 'private'
}
else {
    $WorkspaceRoot
}

if (-not (Test-Path -LiteralPath $workspacePath -PathType Container)) {
    throw "Private workspace directory does not exist: $workspacePath"
}

$workspaceRoot = (Resolve-Path -LiteralPath $workspacePath).Path
$gitRoot = (& git -C $workspaceRoot rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($gitRoot -join ''))) {
    throw 'The private workspace must be inside the public Git repository.'
}
$gitRoot = (($gitRoot -join '').Trim() -replace '/', '\')
if (-not $gitRoot.Equals($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The private workspace must belong to this repository.'
}

$workspaceRelative = $workspaceRoot.Substring($repositoryRoot.Length).TrimStart('\', '/')
if ([string]::IsNullOrWhiteSpace($workspaceRelative)) {
    throw 'WorkspaceRoot must point to the private/ directory, not the repository root.'
}
$ignoreResult = & git -C $repositoryRoot check-ignore --quiet -- $workspaceRelative 2>$null
Write-CheckResult -Name 'private-directory-is-gitignored' -Passed ($LASTEXITCODE -eq 0)

$requiredFiles = @('resume_materials.md', 'job_search_preferences.md')

foreach ($requiredFile in $requiredFiles) {
    $requiredPath = Join-Path $workspaceRoot $requiredFile
    Write-CheckResult -Name "required-file:$requiredFile" -Passed (Test-Path -LiteralPath $requiredPath -PathType Leaf)
}

$agentsPath = Join-Path $repositoryRoot 'AGENTS.md'
$materialsPath = Join-Path $workspaceRoot 'resume_materials.md'
$preferencesPath = Join-Path $workspaceRoot 'job_search_preferences.md'
$agentsText = if (Test-Path -LiteralPath $agentsPath -PathType Leaf) { Get-Content -LiteralPath $agentsPath -Raw -Encoding UTF8 } else { $null }
$materialsText = if (Test-Path -LiteralPath $materialsPath -PathType Leaf) { Get-Content -LiteralPath $materialsPath -Raw -Encoding UTF8 } else { $null }
$preferencesText = if (Test-Path -LiteralPath $preferencesPath -PathType Leaf) { Get-Content -LiteralPath $preferencesPath -Raw -Encoding UTF8 } else { $null }

$requiredAgentRules = @(
    'Settings → Computer use',
    '## 多条经历的填写顺序',
    '背景调查授权始终停止询问',
    '最终提交'
)
foreach ($requiredAgentRule in $requiredAgentRules) {
    $present = $null -ne $agentsText -and $agentsText.Contains($requiredAgentRule)
    Write-CheckResult -Name 'required-agent-rule' -Passed $present
}

$requiredMaterialSections = @(
    '## 附件与外链资料',
    '## 基本信息',
    '## 投递默认值与授权',
    '### 经历与成果的填写顺序',
    '### 声明与自愿披露授权'
)
foreach ($requiredMaterialSection in $requiredMaterialSections) {
    $present = $null -ne $materialsText -and $materialsText.Contains($requiredMaterialSection)
    Write-CheckResult -Name 'required-material-section' -Passed $present
}

$requiredPreferenceSections = @(
    '## 岗位范围',
    '## 优先方向',
    '## JD 判断偏好'
)
foreach ($requiredPreferenceSection in $requiredPreferenceSections) {
    $present = $null -ne $preferencesText -and $preferencesText.Contains($requiredPreferenceSection)
    Write-CheckResult -Name 'required-preference-section' -Passed $present
}

$materialsHavePlaceholder = $null -eq $materialsText -or [regex]::IsMatch($materialsText, '<[^>`r`n]+>')
$preferencesHavePlaceholder = $null -eq $preferencesText -or [regex]::IsMatch($preferencesText, '<[^>`r`n]+>')
Write-CheckResult -Name 'unresolved-placeholders-absent' -Passed (-not $materialsHavePlaceholder -and -not $preferencesHavePlaceholder)

$resumeFullPath = $null
if ($null -ne $materialsText) {
    $attachmentLabels = @('简历附件', '证件照附件')
    foreach ($attachmentLabel in $attachmentLabels) {
        $declaredPath = Get-DeclaredAttachment -Text $materialsText -Label $attachmentLabel
        $isResume = $attachmentLabel -eq '简历附件'
        $isSkipped = $declaredPath -in @($null, '', '无')

        if ($isSkipped) {
            Write-CheckResult -Name "attachment-declared:$attachmentLabel" -Passed (-not $isResume)
            continue
        }

        $pathSafe = -not [System.IO.Path]::IsPathRooted($declaredPath)
        $attachmentFullPath = $null
        if ($pathSafe) {
            $attachmentFullPath = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $declaredPath))
            $workspacePrefix = $workspaceRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
            $pathSafe = $attachmentFullPath.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)
        }
        Write-CheckResult -Name "attachment-path-safe:$attachmentLabel" -Passed $pathSafe

        $attachmentExists = $pathSafe -and (Test-Path -LiteralPath $attachmentFullPath -PathType Leaf)
        Write-CheckResult -Name "attachment-exists:$attachmentLabel" -Passed $attachmentExists

        if ($isResume -and $attachmentExists) {
            $resumeFullPath = $attachmentFullPath
        }
    }
}

$orderedCategories = @(
    '教育经历',
    '实习经历',
    '校园 / 社会经历',
    '工作经历',
    '项目经历',
    '竞赛获奖',
    '证书'
)

if ($null -ne $materialsText) {
    foreach ($category in $orderedCategories) {
        $sectionPattern = '(?ms)^##[ \t]+' + [regex]::Escape($category) + '[ \t]*\r?\n(?<body>.*?)(?=^##[ \t]+|\z)'
        $sectionMatch = [regex]::Match($materialsText, $sectionPattern)
        if (-not $sectionMatch.Success) {
            continue
        }

        $entryMatches = [regex]::Matches($sectionMatch.Groups['body'].Value, '(?ms)^###[ \t]+[^\r\n]+\r?\n(?<body>.*?)(?=^###[ \t]+|\z)')
        $records = @()
        for ($entryIndex = 0; $entryIndex -lt $entryMatches.Count; $entryIndex += 1) {
            $entryBody = $entryMatches[$entryIndex].Groups['body'].Value
            $startMatch = [regex]::Match($entryBody, '(?m)^-[ \t]*开始时间[：:][ \t]*(?<value>[^\r\n]*)')
            $endMatch = [regex]::Match($entryBody, '(?m)^-[ \t]*结束时间[：:][ \t]*(?<value>[^\r\n]*)')
            $startValue = if ($startMatch.Success) { $startMatch.Groups['value'].Value } else { '' }
            $endValue = if ($endMatch.Success) { $endMatch.Groups['value'].Value } else { '' }
            $startKey = ConvertTo-DateKey -Value $startValue
            $endKey = ConvertTo-DateKey -Value $endValue
            Write-CheckResult -Name "date-format:$($category):$($entryIndex + 1)" -Passed ($startKey.Valid -and $endKey.Valid)
            $records += [pscustomobject]@{ Start = $startKey; End = $endKey }
        }

        for ($recordIndex = 0; $recordIndex -lt ($records.Count - 1); $recordIndex += 1) {
            $comparison = Compare-RecordOrder -Left $records[$recordIndex] -Right $records[$recordIndex + 1]
            Write-CheckResult -Name "record-order:$($category):$($recordIndex + 1)" -Passed ($comparison -ge 0)
        }
    }
}

$hashStatePath = Join-Path $workspaceRoot '.resume.sha256'
if ($InitializeResumeHash) {
    $canInitialize = $null -ne $resumeFullPath
    Write-CheckResult -Name 'resume-hash-initializable' -Passed $canInitialize
    if ($canInitialize) {
        $resumeHash = (Get-FileHash -LiteralPath $resumeFullPath -Algorithm SHA256).Hash
        Set-Content -LiteralPath $hashStatePath -Value $resumeHash -Encoding ASCII
    }
}

$hashStateExists = Test-Path -LiteralPath $hashStatePath -PathType Leaf
Write-CheckResult -Name 'resume-hash-state-exists' -Passed $hashStateExists
if ($hashStateExists -and $null -ne $resumeFullPath) {
    $expectedHash = (Get-Content -LiteralPath $hashStatePath -Raw -Encoding ASCII).Trim()
    $hashStateValid = $expectedHash -match '^[0-9A-Fa-f]{64}$'
    Write-CheckResult -Name 'resume-hash-state-valid' -Passed $hashStateValid
    if ($hashStateValid) {
        $actualHash = (Get-FileHash -LiteralPath $resumeFullPath -Algorithm SHA256).Hash
        Write-CheckResult -Name 'resume-hash-matches' -Passed ($actualHash -eq $expectedHash)
    }
}

if ($script:FailureCount -eq 0) {
    Write-Output 'RESULT: PASS'
    exit 0
}

Write-Output "RESULT: FAIL ($($script:FailureCount) checks)"
exit 1
