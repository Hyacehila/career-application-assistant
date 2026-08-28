#requires -Version 5.1

[CmdletBinding()]
param(
    [switch] $Staged
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

function Get-IndexText {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    $contentLines = & git show (':' + $Path) 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    return ($contentLines -join "`n")
}

function Get-WorkTreeText {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Root,

        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    $fullPath = Join-Path $Root $Path
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        return $null
    }

    return Get-Content -LiteralPath $fullPath -Raw -Encoding UTF8
}

$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $gitCommand) {
    throw 'Git is required.'
}

$scriptRepositoryCandidate = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$repositoryRoot = (& git -C $scriptRepositoryCandidate rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($repositoryRoot -join ''))) {
    throw 'Run this script inside the public Git repository.'
}
$repositoryRoot = ($repositoryRoot -join '').Trim()
Set-Location -LiteralPath $repositoryRoot

if ($Staged) {
    $stagedPaths = @(& git diff --cached --name-only --diff-filter=ACDMR)
    Write-CheckResult -Name 'staged-change-present' -Passed ($stagedPaths.Count -gt 0)
}

$requiredFiles = @(
    '.gitignore',
    'AGENTS.md',
    'LICENSE',
    'README.md',
    'README.zh-CN.md',
    'pyproject.toml',
    'resume_materials.example.md',
    'uv.lock',
    'app/README.md',
    'app/server.py',
    'app/frontend/index.html',
    'app/frontend/package.json',
    'app/frontend/pnpm-lock.yaml',
    'app/frontend/tsconfig.json',
    'app/frontend/vite.config.ts',
    'app/frontend/src/main.tsx',
    'app/frontend/src/App.tsx',
    'scripts/Initialize-PrivateOverlay.ps1',
    'scripts/Start-BoardService.ps1',
    'scripts/Test-PrivateWorkspace.ps1',
    'scripts/Test-PublicRelease.ps1'
)

$trackedFiles = @(& git ls-files) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object
$missingRequiredFiles = @($requiredFiles | Where-Object { $_ -notin $trackedFiles })
Write-CheckResult -Name 'required-public-files-present' -Passed ($missingRequiredFiles.Count -eq 0)

$allowedPathPattern = '^(?:\.gitignore|AGENTS\.md|LICENSE|README\.md|README\.zh-CN\.md|pyproject\.toml|resume_materials\.example\.md|uv\.lock|app/.*|scripts/.*)$'
$unexpectedTrackedFiles = @($trackedFiles | Where-Object { $_ -notmatch $allowedPathPattern })
Write-CheckResult -Name 'tracked-file-allowlist' -Passed ($unexpectedTrackedFiles.Count -eq 0)

$forbiddenPathPatterns = @(
    '(^|/)resume_materials\.md$',
    '(^|/)\.resume\.sha256$',
    '(^|/)(private|private-workspace)(/|$)',
    '\.(pdf|jpe?g|png|docx?|sqlite3?|db)$'
)

# Release checks cover all reachable objects, while emitting aggregate results
# only, so a private path can never be approved merely because it is not present
# in the current checkout.
$historyObjectLines = @(& git rev-list --objects --all 2>$null)
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to inspect reachable Git objects.'
}

$historyPathsSafe = $true
foreach ($historyObjectLine in $historyObjectLines) {
    $separatorIndex = $historyObjectLine.IndexOf(' ')
    if ($separatorIndex -lt 0) {
        continue
    }

    $historicalPath = $historyObjectLine.Substring($separatorIndex + 1)
    foreach ($forbiddenPathPattern in $forbiddenPathPatterns) {
        if ($historicalPath -match $forbiddenPathPattern) {
            $historyPathsSafe = $false
            break
        }
    }
    if (-not $historyPathsSafe) {
        break
    }
}

Write-CheckResult -Name 'reachable-objects-have-no-private-paths' -Passed $historyPathsSafe

foreach ($trackedFile in $trackedFiles) {
    $pathAllowed = $true
    foreach ($forbiddenPathPattern in $forbiddenPathPatterns) {
        if ($trackedFile -match $forbiddenPathPattern) {
            $pathAllowed = $false
            break
        }
    }
    Write-CheckResult -Name "public-path:$trackedFile" -Passed $pathAllowed
}

$untrackedLines = @(
    @(& git status --porcelain --untracked-files=all) | Where-Object { $_ -match '^\?\?' }
)
Write-CheckResult -Name 'untracked-files-absent' -Passed ($untrackedLines.Count -eq 0)

$textExtensions = @('.md', '.ps1', '.txt', '.json', '.yml', '.yaml', '.py', '.js', '.ts', '.tsx', '.css', '.html', '.gitignore', '.toml')
$sensitivePatterns = @(
    '(?<!\d)1[3-9]\d{9}(?!\d)',
    '(?<!\d)\d{17}[\dXx](?!\d)',
    '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    '(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])',
    '(?i)(?<![A-Za-z0-9])[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s\\]+',
    '(?i)(?:gh[pousr]_|sk-)[A-Za-z0-9_-]{20,}'
)

foreach ($trackedFile in $trackedFiles) {
    $extension = [System.IO.Path]::GetExtension($trackedFile).ToLowerInvariant()
    $isTextFile = $textExtensions -contains $extension -or $trackedFile -in @('LICENSE', '.gitignore')
    if (-not $isTextFile) {
        continue
    }

    $sensitiveScanExempt = @('uv.lock', 'app/frontend/pnpm-lock.yaml', 'app/frontend/package-lock.json')
    if ($trackedFile -in $sensitiveScanExempt) {
        Write-CheckResult -Name "public-content:$trackedFile" -Passed $true
        continue
    }

    $text = if ($Staged) { Get-IndexText -Path $trackedFile } else { Get-WorkTreeText -Root $repositoryRoot -Path $trackedFile }
    $contentSafe = $null -ne $text
    if ($contentSafe) {
        foreach ($sensitivePattern in $sensitivePatterns) {
            if ($text -match $sensitivePattern) {
                $contentSafe = $false
                break
            }
        }
    }

    Write-CheckResult -Name "public-content:$trackedFile" -Passed $contentSafe
}

$agentsText = if ($Staged) { Get-IndexText -Path 'AGENTS.md' } else { Get-WorkTreeText -Root $repositoryRoot -Path 'AGENTS.md' }
$materialsText = if ($Staged) { Get-IndexText -Path 'resume_materials.example.md' } else { Get-WorkTreeText -Root $repositoryRoot -Path 'resume_materials.example.md' }

$requiredAgentRules = @(
    'Settings → Computer use',
    'Allow once',
    'Allow all',
    '不创建新账号',
    '无需再次确认资料传输',
    '## 多条经历的填写顺序',
    '按结束时间从近到远排列',
    '背景调查授权始终停止询问',
    '不愿自我披露',
    '最终提交',
    'private/resume_materials.md',
    'app/',
    '## 投递记录与状态更新',
    'api/agent/fill-completed',
    'private/applications.sqlite'
)

foreach ($requiredAgentRule in $requiredAgentRules) {
    $present = $null -ne $agentsText -and $agentsText.Contains($requiredAgentRule)
    Write-CheckResult -Name 'required-agent-rule' -Passed $present
}

$requiredMaterialSections = @(
    '## 投递默认值与授权',
    '### 招聘来源',
    '### 城市与面试',
    '### 到岗时间与实习周期',
    '### 经历与成果的填写顺序',
    '### 敏感个人信息填写授权',
    '### 站点填写与草稿保存授权',
    '### 简历附件替换授权',
    '### 声明与自愿披露授权'
)

foreach ($requiredMaterialSection in $requiredMaterialSections) {
    $present = $null -ne $materialsText -and $materialsText.Contains($requiredMaterialSection)
    Write-CheckResult -Name 'required-template-section' -Passed $present
}

$placeholderCount = if ($null -eq $materialsText) { 0 } else { [regex]::Matches($materialsText, '<[^>`r`n]+>').Count }
Write-CheckResult -Name 'template-has-placeholders' -Passed ($placeholderCount -ge 30)

if ($script:FailureCount -eq 0) {
    Write-Output 'RESULT: PASS'
    exit 0
}

Write-Output "RESULT: FAIL ($($script:FailureCount) checks)"
exit 1
