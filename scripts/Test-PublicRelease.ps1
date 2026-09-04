#requires -Version 5.1

[CmdletBinding()]
param(
    [switch] $Staged,
    [switch] $PolicySelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:FailureCount = 0

$documentationFiles = @(
    'README.md',
    'README.zh-CN.md',
    'CONTRIBUTING.md',
    'SECURITY.md',
    'ROADMAP.md',
    'CHANGELOG.md',
    'THIRD_PARTY_NOTICES.md',
    'app/README.md',
    'docs/README.md',
    'docs/README.zh-CN.md',
    'docs/getting-started.md',
    'docs/getting-started.zh-CN.md',
    'docs/application-workflow.md',
    'docs/application-workflow.zh-CN.md',
    'docs/mail-ingestion.md',
    'docs/mail-ingestion.zh-CN.md',
    'docs/security-and-privacy.md',
    'docs/security-and-privacy.zh-CN.md',
    'docs/development.md',
    'docs/development.zh-CN.md'
)

$communityFiles = @(
    'CONTRIBUTING.md',
    'SECURITY.md',
    'ROADMAP.md',
    'CHANGELOG.md'
)

$githubFiles = @(
    '.github/ISSUE_TEMPLATE/bug_report.yml',
    '.github/ISSUE_TEMPLATE/feature_request.yml',
    '.github/ISSUE_TEMPLATE/config.yml',
    '.github/workflows/ci.yml'
)

$skillFiles = @(
    '.agents/skills/job-discovery/SKILL.md',
    '.agents/skills/outlook-recruitment-sync/SKILL.md'
)

$publicScreenshotFiles = @(
    'docs/assets/screenshots/career-application-assistant-hero.png',
    'docs/assets/screenshots/demo-board.png',
    'docs/assets/screenshots/demo-assessment-detail.png'
)

$coreExactFiles = @(
    '.gitignore',
    'AGENTS.md',
    'LICENSE',
    'README.md',
    'README.zh-CN.md',
    'THIRD_PARTY_NOTICES.md',
    'job_search_preferences.example.md',
    'pyproject.toml',
    'resume_materials.example.md',
    'uv.lock'
)

$allowedExactFiles = @(
    $coreExactFiles
    $communityFiles
    $documentationFiles | Where-Object { $_ -like 'docs/*' }
    $githubFiles
    $skillFiles
    $publicScreenshotFiles
) | Select-Object -Unique

$requiredFiles = @(
    $coreExactFiles
    $communityFiles
    $documentationFiles | Where-Object { $_ -like 'docs/*' }
    $githubFiles
    $skillFiles
    $publicScreenshotFiles
    'app/README.md',
    'app/server.py',
    'app/demo_server.py',
    'app/backend/demo.py',
    'app/backend/routers/demo.py',
    'app/frontend/index.html',
    'app/frontend/package.json',
    'app/frontend/pnpm-lock.yaml',
    'app/frontend/e2e/agent-fill.spec.ts',
    'app/frontend/e2e/demo.playwright.config.ts',
    'app/frontend/e2e/demo.spec.ts',
    'app/frontend/e2e/playwright.config.ts',
    'app/frontend/tsconfig.json',
    'app/frontend/vite.config.ts',
    'app/frontend/src/main.tsx',
    'app/frontend/src/App.tsx',
    'app/frontend/src/hooks/useServiceHealth.ts',
    'app/frontend/src/productIdentity.test.ts',
    'app/tests/e2e/mock_recruitment.html',
    'app/tests/e2e/mock_server.py',
    'app/tests/test_demo.py',
    'app/tests/test_public_documentation.py',
    'app/tests/test_public_scripts.py',
    'app/tests/test_startup.py',
    'scripts/Initialize-PrivateOverlay.ps1',
    'scripts/Invoke-BoardAgent.ps1',
    'scripts/Start-BoardService.ps1',
    'scripts/Start-Demo.ps1',
    'scripts/Test-AgentBrowserE2E.ps1',
    'scripts/Test-Environment.ps1',
    'scripts/Test-PrivateWorkspace.ps1',
    'scripts/Test-PublicRelease.ps1'
) | Select-Object -Unique

$forbiddenPathPatterns = @(
    '(^|/)resume_materials\.md$',
    '(^|/)job_search_preferences\.md$',
    '(^|/)\.resume\.sha256$',
    '(^|/)(private|private-workspace)(/|$)',
    '\.(pdf|jpe?g|png|gif|webp|svg|docx?|sqlite3?|db|mp3|mp4|m4a|m4v|mov|avi|webm|wav|ogg|oga|opus|flac|aac|wma|wmv|mkv|mpeg|mpg|flv|aif|aiff|mid|midi)$'
)

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

function Test-ForbiddenPath {
    param([Parameter(Mandatory = $true)][string] $Path)

    $normalized = $Path.Replace('\', '/')
    if ($normalized -cin $publicScreenshotFiles) {
        return $false
    }
    foreach ($pattern in $forbiddenPathPatterns) {
        if ($normalized -match $pattern) {
            return $true
        }
    }
    return $false
}

function Test-AllowedPublicPath {
    param([Parameter(Mandatory = $true)][string] $Path)

    $normalized = $Path.Replace('\', '/')
    if (Test-ForbiddenPath -Path $normalized) {
        return $false
    }
    if ($normalized -in $allowedExactFiles) {
        return $true
    }
    return $normalized.StartsWith('app/', [StringComparison]::Ordinal) -or
        $normalized.StartsWith('scripts/', [StringComparison]::Ordinal)
}

function Test-BytePrefix {
    param(
        [Parameter(Mandatory = $true)][byte[]] $Bytes,
        [Parameter(Mandatory = $true)][byte[]] $Prefix,
        [int] $Offset = 0
    )

    if ($Bytes.Length -lt ($Offset + $Prefix.Length)) {
        return $false
    }
    for ($index = 0; $index -lt $Prefix.Length; $index += 1) {
        if ($Bytes[$Offset + $index] -ne $Prefix[$index]) {
            return $false
        }
    }
    return $true
}

function Read-PngUInt32BigEndian {
    param(
        [Parameter(Mandatory = $true)][byte[]] $Bytes,
        [Parameter(Mandatory = $true)][int] $Offset
    )

    if ($Offset -lt 0 -or $Bytes.Length -lt ($Offset + 4)) {
        throw 'PNG integer is outside the byte buffer.'
    }
    $value = ([uint64] $Bytes[$Offset] * 16777216) +
        ([uint64] $Bytes[$Offset + 1] * 65536) +
        ([uint64] $Bytes[$Offset + 2] * 256) +
        [uint64] $Bytes[$Offset + 3]
    return [uint32] $value
}

function Test-PublicScreenshotSafe {
    param([AllowNull()][byte[]] $Bytes)

    $pngSignature = [byte[]](0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
    if ($null -eq $Bytes -or $Bytes.Length -lt 1024 -or $Bytes.Length -gt (5 * 1024 * 1024)) {
        return $false
    }
    if (-not (Test-BytePrefix -Bytes $Bytes -Prefix $pngSignature)) {
        return $false
    }

    $offset = 8
    $chunkIndex = 0
    $seenHeader = $false
    $seenImageData = $false
    $forbiddenMetadataChunks = @('tEXt', 'zTXt', 'iTXt', 'eXIf')

    while ($offset -lt $Bytes.Length) {
        if (($Bytes.Length - $offset) -lt 12) {
            return $false
        }

        $chunkLength = [uint64](Read-PngUInt32BigEndian -Bytes $Bytes -Offset $offset)
        $chunkType = [Text.Encoding]::ASCII.GetString($Bytes, $offset + 4, 4)
        if ($chunkType -cnotmatch '^[A-Za-z]{4}$') {
            return $false
        }

        $nextOffset = [uint64] $offset + 12 + $chunkLength
        if ($nextOffset -gt [uint64] $Bytes.Length) {
            return $false
        }
        if ($forbiddenMetadataChunks -ccontains $chunkType) {
            return $false
        }

        if ($chunkIndex -eq 0 -and $chunkType -cne 'IHDR') {
            return $false
        }
        if ($chunkType -ceq 'IHDR') {
            if ($seenHeader -or $chunkLength -ne 13) {
                return $false
            }
            $width = Read-PngUInt32BigEndian -Bytes $Bytes -Offset ($offset + 8)
            $height = Read-PngUInt32BigEndian -Bytes $Bytes -Offset ($offset + 12)
            if ($width -lt 640 -or $width -gt 3840 -or $height -lt 360 -or $height -gt 2160) {
                return $false
            }
            $seenHeader = $true
        } elseif ($chunkType -ceq 'IDAT') {
            if (-not $seenHeader -or $chunkLength -eq 0) {
                return $false
            }
            $seenImageData = $true
        } elseif ($chunkType -ceq 'IEND') {
            return $seenHeader -and $seenImageData -and $chunkLength -eq 0 -and
                $nextOffset -eq [uint64] $Bytes.Length
        }

        $offset = [int] $nextOffset
        $chunkIndex += 1
    }

    return $false
}

function Test-MediaSignature {
    param([AllowNull()][byte[]] $Bytes)

    if ($null -eq $Bytes -or $Bytes.Length -eq 0) {
        return $false
    }

    $binarySignatures = @(
        [byte[]](0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a),
        [byte[]](0xff, 0xd8, 0xff),
        [Text.Encoding]::ASCII.GetBytes('GIF87a'),
        [Text.Encoding]::ASCII.GetBytes('GIF89a'),
        [Text.Encoding]::ASCII.GetBytes('OggS'),
        [Text.Encoding]::ASCII.GetBytes('fLaC'),
        [Text.Encoding]::ASCII.GetBytes('ID3'),
        [Text.Encoding]::ASCII.GetBytes('FLV'),
        [Text.Encoding]::ASCII.GetBytes('MThd'),
        [byte[]](0x1a, 0x45, 0xdf, 0xa3),
        [byte[]](0x30, 0x26, 0xb2, 0x75, 0x8e, 0x66, 0xcf, 0x11, 0xa6, 0xd9, 0x00, 0xaa, 0x00, 0x62, 0xce, 0x6c),
        [Text.Encoding]::ASCII.GetBytes('%PDF-')
    )
    foreach ($signature in $binarySignatures) {
        if (Test-BytePrefix -Bytes $Bytes -Prefix $signature) {
            return $true
        }
    }

    if ($Bytes.Length -ge 12 -and (Test-BytePrefix -Bytes $Bytes -Prefix ([Text.Encoding]::ASCII.GetBytes('RIFF')))) {
        $riffType = [Text.Encoding]::ASCII.GetString($Bytes, 8, 4)
        if ($riffType -in @('WEBP', 'WAVE', 'AVI ')) {
            return $true
        }
    }
    if ($Bytes.Length -ge 8 -and [Text.Encoding]::ASCII.GetString($Bytes, 4, 4) -eq 'ftyp') {
        return $true
    }
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xff -and $Bytes[1] -in @(0xfb, 0xf3, 0xf2)) {
        return $true
    }
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xff -and $Bytes[1] -in @(0xf1, 0xf9)) {
        return $true
    }
    if ($Bytes.Length -ge 4 -and (Test-BytePrefix -Bytes $Bytes -Prefix ([byte[]](0x00, 0x00, 0x01))) -and $Bytes[3] -in @(0xba, 0xb3)) {
        return $true
    }
    if ($Bytes.Length -ge 12 -and (Test-BytePrefix -Bytes $Bytes -Prefix ([Text.Encoding]::ASCII.GetBytes('FORM')))) {
        $formType = [Text.Encoding]::ASCII.GetString($Bytes, 8, 4)
        if ($formType -in @('AIFF', 'AIFC')) {
            return $true
        }
    }

    $prefixLength = [Math]::Min($Bytes.Length, 4096)
    $textPrefix = if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xff -and $Bytes[1] -eq 0xfe) {
        [Text.Encoding]::Unicode.GetString($Bytes, 0, $prefixLength - ($prefixLength % 2))
    } elseif ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xfe -and $Bytes[1] -eq 0xff) {
        [Text.Encoding]::BigEndianUnicode.GetString($Bytes, 0, $prefixLength - ($prefixLength % 2))
    } elseif ($Bytes.Length -ge 4 -and $Bytes[1] -eq 0x00) {
        [Text.Encoding]::Unicode.GetString($Bytes, 0, $prefixLength - ($prefixLength % 2))
    } elseif ($Bytes.Length -ge 4 -and $Bytes[0] -eq 0x00) {
        [Text.Encoding]::BigEndianUnicode.GetString($Bytes, 0, $prefixLength - ($prefixLength % 2))
    } else {
        [Text.Encoding]::UTF8.GetString($Bytes, 0, $prefixLength)
    }
    return $textPrefix -match '(?is)^(?:\uFEFF)?\s*(?:<\?xml[^>]*>\s*)?(?:<!--.*?-->\s*)*(?:<!DOCTYPE\s+svg[^>]*>\s*)?<svg\b'
}

function Test-DocumentationTextSafe {
    param(
        [AllowNull()][string] $Text,
        [Parameter(Mandatory = $true)][string] $DocumentPath
    )

    if ($null -eq $Text) {
        return $false
    }

    $normalizedDocumentPath = $DocumentPath.Replace('\', '/')
    $readmeScreenshotTargets = @(
        'docs/assets/screenshots/career-application-assistant-hero.png',
        'docs/assets/screenshots/demo-board.png',
        'docs/assets/screenshots/demo-assessment-detail.png'
    )
    $markdownImagePattern = [regex]::new('!\[[^\]\r\n]*\]\s*\(([^)\r\n]+)\)')
    $imageMatches = @($markdownImagePattern.Matches($Text))
    $isScreenshotReadme = $normalizedDocumentPath -cin @('README.md', 'README.zh-CN.md')
    $sanitizedText = $Text

    if ($isScreenshotReadme) {
        if ($imageMatches.Count -ne $readmeScreenshotTargets.Count) {
            return $false
        }
        $imageTargets = @($imageMatches | ForEach-Object { $_.Groups[1].Value.Trim() })
        foreach ($target in $readmeScreenshotTargets) {
            if (@($imageTargets | Where-Object { $_ -ceq $target }).Count -ne 1) {
                return $false
            }
        }
        if (@($imageTargets | Where-Object { $_ -cnotin $readmeScreenshotTargets }).Count -ne 0) {
            return $false
        }
        $sanitizedText = $markdownImagePattern.Replace($Text, '')
    } elseif ($imageMatches.Count -ne 0) {
        return $false
    }

    $forbiddenDocumentPatterns = @(
        '(?im)!\[[^\]]*\]\s*(?:\([^)]*\)|\[[^\]]*\])',
        '(?i)<\s*img\b',
        '(?i)shields\.io',
        '(?im)^\s*(?:```|~~~)\s*mermaid\b',
        '(?i)\bclass\s*=\s*["'']mermaid["'']',
        '(?i)\]\([^\)\r\n]*\.(?:png|jpe?g|gif|webp|svg|mp3|mp4|m4a|m4v|mov|avi|webm|wav|ogg|oga|opus|flac|aac|wma|wmv|mkv|mpeg|mpg|flv|aif|aiff|mid|midi)(?:[?#][^\)\r\n]*)?\)',
        '(?i)<(?:https?://|\.\.?/)[^>\r\n]+\.(?:png|jpe?g|gif|webp|svg|mp3|mp4|m4a|m4v|mov|avi|webm|wav|ogg|oga|opus|flac|aac|wma|wmv|mkv|mpeg|mpg|flv|aif|aiff|mid|midi)(?:[?#][^>\r\n]*)?>',
        '(?i)https?://[^\s<>\)]+\.(?:png|jpe?g|gif|webp|svg|mp3|mp4|m4a|m4v|mov|avi|webm|wav|ogg|oga|opus|flac|aac|wma|wmv|mkv|mpeg|mpg|flv|aif|aiff|mid|midi)(?:[?#][^\s<>\)]*)?'
    )
    foreach ($pattern in $forbiddenDocumentPatterns) {
        if ($sanitizedText -match $pattern) {
            return $false
        }
    }
    return $true
}

function New-PolicyPngFixture {
    param([AllowEmptyString()][string] $MetadataChunk = '')

    $signature = [byte[]](0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
    $headerData = [byte[]](
        0x00, 0x00, 0x05, 0x00, # 1280 pixels
        0x00, 0x00, 0x02, 0xd0, # 720 pixels
        0x08, 0x06, 0x00, 0x00, 0x00
    )
    $headerChunk = [byte[]](
        ([byte[]](0x00, 0x00, 0x00, 0x0d)) +
        [Text.Encoding]::ASCII.GetBytes('IHDR') +
        $headerData +
        ([byte[]](0x00, 0x00, 0x00, 0x00))
    )
    $metadataBytes = [byte[]]@()
    if (-not [string]::IsNullOrEmpty($MetadataChunk)) {
        $metadataBytes = [byte[]](
            ([byte[]](0x00, 0x00, 0x00, 0x00)) +
            [Text.Encoding]::ASCII.GetBytes($MetadataChunk) +
            ([byte[]](0x00, 0x00, 0x00, 0x00))
        )
    }
    $imageData = [byte[]]::new(1024)
    $imageChunk = [byte[]](
        ([byte[]](0x00, 0x00, 0x04, 0x00)) +
        [Text.Encoding]::ASCII.GetBytes('IDAT') +
        $imageData +
        ([byte[]](0x00, 0x00, 0x00, 0x00))
    )
    $endChunk = [byte[]](
        ([byte[]](0x00, 0x00, 0x00, 0x00)) +
        [Text.Encoding]::ASCII.GetBytes('IEND') +
        ([byte[]](0x00, 0x00, 0x00, 0x00))
    )
    return ,([byte[]]($signature + $headerChunk + $metadataBytes + $imageChunk + $endChunk))
}

function Invoke-PolicySelfTest {
    $requiredPolicyPaths = @(
        'app/demo_server.py',
        'app/backend/demo.py',
        'app/backend/routers/demo.py',
        'scripts/Start-Demo.ps1',
        'scripts/Test-Environment.ps1',
        'app/frontend/e2e/demo.playwright.config.ts',
        'app/frontend/e2e/demo.spec.ts',
        'app/tests/test_demo.py',
        'app/tests/test_public_documentation.py',
        'app/tests/test_public_scripts.py',
        'app/tests/test_startup.py'
    ) + $communityFiles + ($documentationFiles | Where-Object { $_ -like 'docs/*' }) + $githubFiles + $skillFiles

    $allowedSamples = @(
        'README.md',
        'job_search_preferences.example.md',
        'docs/assets/screenshots/career-application-assistant-hero.png',
        'docs/assets/screenshots/demo-board.png',
        'docs/assets/screenshots/demo-assessment-detail.png',
        '.agents/skills/job-discovery/SKILL.md',
        'app/backend/app.py',
        'scripts/Start-Demo.ps1',
        'docs/security-and-privacy.zh-CN.md',
        '.github/ISSUE_TEMPLATE/config.yml',
        '.github/workflows/ci.yml'
    )
    $rejectedSamples = @(
        'private/resume_materials.md',
        'private/job_search_preferences.md',
        'job_search_preferences.md',
        'docs/unreviewed.md',
        '.github/workflows/extra.yml',
        '.github/PULL_REQUEST_TEMPLATE.md',
        'app/demo.png',
        'docs/assets/screenshots/career-application-assistant-hero-copy.png',
        'docs/assets/screenshots/demo-board-copy.png',
        'docs/assets/screenshots/demo-assessment.png',
        'docs/assets/screenshots/demo-third.png',
        'docs/assets/screenshots/archive/demo-board.png',
        'scripts/walkthrough.mp4'
    )

    Write-CheckResult -Name 'policy-allowlist-positive' -Passed (
        @($allowedSamples | Where-Object { -not (Test-AllowedPublicPath -Path $_) }).Count -eq 0
    )
    Write-CheckResult -Name 'policy-allowlist-negative' -Passed (
        @($rejectedSamples | Where-Object { Test-AllowedPublicPath -Path $_ }).Count -eq 0
    )
    Write-CheckResult -Name 'policy-screenshot-paths-exact-positive' -Passed (
        @($publicScreenshotFiles | Where-Object { -not (Test-AllowedPublicPath -Path $_) }).Count -eq 0
    )
    Write-CheckResult -Name 'policy-screenshot-paths-near-miss-negative' -Passed (
        @(
            'docs/assets/screenshots/career-application-assistant-hero-copy.png',
            'docs/assets/screenshots/career-application-assistant-cover.png',
            'docs/assets/screenshots/demo-board-copy.png',
            'docs/assets/screenshots/demo-assessment.png',
            'docs/assets/screenshots/demo-third.png',
            'docs/assets/screenshots/archive/demo-board.png'
        | Where-Object { Test-AllowedPublicPath -Path $_ }).Count -eq 0
    )
    Write-CheckResult -Name 'policy-required-paths' -Passed (
        @($requiredPolicyPaths | Where-Object { $_ -notin $requiredFiles }).Count -eq 0
    )

    $mediaSamples = @(
        [byte[]](0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a),
        [byte[]](0xff, 0xd8, 0xff, 0xe0),
        [Text.Encoding]::ASCII.GetBytes('GIF89a fixture'),
        [Text.Encoding]::ASCII.GetBytes('RIFF0000WEBP'),
        [Text.Encoding]::UTF8.GetBytes('<?xml version="1.0"?><svg></svg>'),
        [Text.Encoding]::Unicode.GetBytes('<svg></svg>'),
        [Text.Encoding]::ASCII.GetBytes('0000ftypisom'),
        [Text.Encoding]::ASCII.GetBytes('OggSfixture'),
        [Text.Encoding]::ASCII.GetBytes('FLVfixture')
    )
    Write-CheckResult -Name 'policy-media-signatures-positive' -Passed (
        @($mediaSamples | Where-Object { -not (Test-MediaSignature -Bytes $_) }).Count -eq 0
    )
    Write-CheckResult -Name 'policy-media-signatures-negative' -Passed (
        -not (Test-MediaSignature -Bytes ([Text.Encoding]::UTF8.GetBytes('# Plain text')))
    )

    $validScreenshotFixture = New-PolicyPngFixture
    Write-CheckResult -Name 'policy-public-screenshot-positive' -Passed (
        Test-PublicScreenshotSafe -Bytes $validScreenshotFixture
    )
    $forbiddenPngMetadata = @('tEXt', 'zTXt', 'iTXt', 'eXIf')
    Write-CheckResult -Name 'policy-public-screenshot-metadata-negative' -Passed (
        @($forbiddenPngMetadata | Where-Object {
            Test-PublicScreenshotSafe -Bytes (New-PolicyPngFixture -MetadataChunk $_)
        }).Count -eq 0
    )

    $unsafeDocuments = @(
        '![preview](preview.png)',
        '<img src="preview.example.test">',
        '[status](https://img.shields.io/example)',
        ('```mermaid' + "`n" + 'graph TD' + "`n" + '```'),
        '[recording](walkthrough.webm)',
        '<https://media.example.test/walkthrough.mp4>'
    )
    Write-CheckResult -Name 'policy-document-media-positive' -Passed (
        Test-DocumentationTextSafe -Text '# Text-only documentation`n[Guide](docs/README.md)' -DocumentPath 'docs/development.md'
    )
    Write-CheckResult -Name 'policy-document-media-negative' -Passed (
        @($unsafeDocuments | Where-Object {
            Test-DocumentationTextSafe -Text $_ -DocumentPath 'docs/development.md'
        }).Count -eq 0
    )

    $safeScreenshotReadme = @'
# Demo

![Hero](docs/assets/screenshots/career-application-assistant-hero.png)
![Board](docs/assets/screenshots/demo-board.png)
![Assessment](docs/assets/screenshots/demo-assessment-detail.png)
'@
    $unsafeScreenshotReadmes = @(
        $safeScreenshotReadme.Replace('demo-board.png', 'demo-board-copy.png'),
        ($safeScreenshotReadme + "`n![Third](docs/assets/screenshots/demo-third.png)"),
        ($safeScreenshotReadme + "`n![Remote](https://media.example.test/demo-board.png)")
    )
    Write-CheckResult -Name 'policy-document-screenshot-exact-positive' -Passed (
        Test-DocumentationTextSafe -Text $safeScreenshotReadme -DocumentPath 'README.md'
    )
    Write-CheckResult -Name 'policy-document-screenshot-near-miss-negative' -Passed (
        @($unsafeScreenshotReadmes | Where-Object {
            Test-DocumentationTextSafe -Text $_ -DocumentPath 'README.md'
        }).Count -eq 0
    )

    if ($script:FailureCount -eq 0) {
        Write-Output 'RESULT: PASS'
        exit 0
    }
    Write-Output "RESULT: FAIL ($($script:FailureCount) checks)"
    exit 1
}

if ($PolicySelfTest) {
    Invoke-PolicySelfTest
}

function Get-IndexText {
    param([Parameter(Mandatory = $true)][string] $Path)

    $contentLines = & git show (':' + $Path) 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return ($contentLines -join "`n")
}

function Get-WorkTreeText {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string] $Path
    )

    $fullPath = Join-Path $Root $Path
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $fullPath -Raw -Encoding UTF8
}

function Get-IndexBytes {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string] $Path
    )

    if ($Path.Contains('"')) {
        return $null
    }
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = 'git'
    $startInfo.Arguments = "show --no-textconv `":$Path`""
    $startInfo.WorkingDirectory = $Root
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $memory = [IO.MemoryStream]::new()
    try {
        $null = $process.Start()
        $process.StandardOutput.BaseStream.CopyTo($memory)
        $null = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            return $null
        }
        return ,$memory.ToArray()
    } finally {
        $memory.Dispose()
        $process.Dispose()
    }
}

function Get-WorkTreeBytes {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string] $Path
    )

    $fullPath = Join-Path $Root $Path
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        return $null
    }
    return ,[IO.File]::ReadAllBytes($fullPath)
}

if ($null -eq (Get-Command git -ErrorAction SilentlyContinue)) {
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
    Write-CheckResult -Name 'staged-path-allowlist' -Passed (
        @($stagedPaths | Where-Object { -not (Test-AllowedPublicPath -Path $_) }).Count -eq 0
    )
}

$trackedFiles = @(& git ls-files) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object
$missingRequiredFiles = @($requiredFiles | Where-Object { $_ -notin $trackedFiles })
Write-CheckResult -Name 'required-public-files-present' -Passed ($missingRequiredFiles.Count -eq 0)
Write-CheckResult -Name 'tracked-file-allowlist' -Passed (
    @($trackedFiles | Where-Object { -not (Test-AllowedPublicPath -Path $_) }).Count -eq 0
)

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
    if ([string]::IsNullOrWhiteSpace($historicalPath)) {
        continue
    }
    if (Test-ForbiddenPath -Path $historicalPath) {
        $historyPathsSafe = $false
        break
    }
}
Write-CheckResult -Name 'reachable-objects-have-no-private-paths' -Passed $historyPathsSafe

foreach ($trackedFile in $trackedFiles) {
    Write-CheckResult -Name "public-path:$trackedFile" -Passed (-not (Test-ForbiddenPath -Path $trackedFile))
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
$sensitiveScanExempt = @('uv.lock', 'app/frontend/pnpm-lock.yaml', 'app/frontend/package-lock.json')

foreach ($trackedFile in $trackedFiles) {
    [byte[]] $bytes = if ($Staged) {
        Get-IndexBytes -Root $repositoryRoot -Path $trackedFile
    } else {
        Get-WorkTreeBytes -Root $repositoryRoot -Path $trackedFile
    }
    $signatureSafe = if ($publicScreenshotFiles -ccontains $trackedFile) {
        Test-PublicScreenshotSafe -Bytes $bytes
    } else {
        $null -ne $bytes -and -not (Test-MediaSignature -Bytes $bytes)
    }
    Write-CheckResult -Name "public-signature:$trackedFile" -Passed $signatureSafe

    $extension = [IO.Path]::GetExtension($trackedFile).ToLowerInvariant()
    $isTextFile = $textExtensions -contains $extension -or $trackedFile -in @('LICENSE', '.gitignore')
    if (-not $isTextFile) {
        continue
    }
    if ($trackedFile -in $sensitiveScanExempt) {
        Write-CheckResult -Name "public-content:$trackedFile" -Passed $true
        continue
    }

    $text = if ($Staged) {
        Get-IndexText -Path $trackedFile
    } else {
        Get-WorkTreeText -Root $repositoryRoot -Path $trackedFile
    }
    $contentSafe = $null -ne $text
    if ($contentSafe) {
        foreach ($pattern in $sensitivePatterns) {
            if ($text -match $pattern) {
                $contentSafe = $false
                break
            }
        }
    }
    Write-CheckResult -Name "public-content:$trackedFile" -Passed $contentSafe
}

foreach ($documentFile in $documentationFiles) {
    if ($documentFile -notin $trackedFiles) {
        continue
    }
    $documentText = if ($Staged) {
        Get-IndexText -Path $documentFile
    } else {
        Get-WorkTreeText -Root $repositoryRoot -Path $documentFile
    }
    Write-CheckResult -Name "text-only-document:$documentFile" -Passed (
        Test-DocumentationTextSafe -Text $documentText -DocumentPath $documentFile
    )
}

$agentsText = if ($Staged) { Get-IndexText -Path 'AGENTS.md' } else { Get-WorkTreeText -Root $repositoryRoot -Path 'AGENTS.md' }
$materialsText = if ($Staged) { Get-IndexText -Path 'resume_materials.example.md' } else { Get-WorkTreeText -Root $repositoryRoot -Path 'resume_materials.example.md' }
$preferencesText = if ($Staged) { Get-IndexText -Path 'job_search_preferences.example.md' } else { Get-WorkTreeText -Root $repositoryRoot -Path 'job_search_preferences.example.md' }
$e2eSpecText = if ($Staged) { Get-IndexText -Path 'app/frontend/e2e/agent-fill.spec.ts' } else { Get-WorkTreeText -Root $repositoryRoot -Path 'app/frontend/e2e/agent-fill.spec.ts' }
$e2eServerText = if ($Staged) { Get-IndexText -Path 'app/tests/e2e/mock_server.py' } else { Get-WorkTreeText -Root $repositoryRoot -Path 'app/tests/e2e/mock_server.py' }

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
    'private/job_search_preferences.md',
    '不设置固定页数或岗位数量上限',
    '不能把单个关键词结果视为全站结果',
    'app/',
    '## 投递记录与状态更新',
    'api/agent/fill-completed',
    'Invoke-BoardAgent.ps1',
    'ApplicationId',
    'email_extract',
    'private/applications.sqlite'
)
foreach ($rule in $requiredAgentRules) {
    Write-CheckResult -Name 'required-agent-rule' -Passed ($null -ne $agentsText -and $agentsText.Contains($rule))
}

$requiredE2ESafetyRules = @(
    @{ Name = 'e2e-agent-command'; Text = $e2eSpecText; Snippet = 'Invoke-BoardAgent.ps1' },
    @{ Name = 'e2e-final-submit-remains-zero'; Text = $e2eSpecText; Snippet = "data-final-submit-count', '0'" },
    @{ Name = 'e2e-private-fields-not-persisted'; Text = $e2eSpecText; Snippet = "not.toContain('mock-resume.pdf')" },
    @{ Name = 'e2e-database-is-temp-isolated'; Text = $e2eServerText; Snippet = 'career-board-e2e-' }
)
foreach ($rule in $requiredE2ESafetyRules) {
    Write-CheckResult -Name $rule.Name -Passed ($null -ne $rule.Text -and $rule.Text.Contains($rule.Snippet))
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
foreach ($section in $requiredMaterialSections) {
    Write-CheckResult -Name 'required-template-section' -Passed ($null -ne $materialsText -and $materialsText.Contains($section))
}

$placeholderCount = if ($null -eq $materialsText) { 0 } else { [regex]::Matches($materialsText, '<[^>`r`n]+>').Count }
Write-CheckResult -Name 'template-has-placeholders' -Passed ($placeholderCount -ge 30)

$requiredPreferenceSections = @(
    '## 岗位范围',
    '## 优先方向',
    '## JD 判断偏好'
)
foreach ($section in $requiredPreferenceSections) {
    Write-CheckResult -Name 'required-preference-template-section' -Passed ($null -ne $preferencesText -and $preferencesText.Contains($section))
}

$preferencePlaceholderCount = if ($null -eq $preferencesText) { 0 } else { [regex]::Matches($preferencesText, '<[^>`r`n]+>').Count }
Write-CheckResult -Name 'preference-template-has-placeholders' -Passed ($preferencePlaceholderCount -ge 6)

if ($script:FailureCount -eq 0) {
    Write-Output 'RESULT: PASS'
    exit 0
}

Write-Output "RESULT: FAIL ($($script:FailureCount) checks)"
exit 1
