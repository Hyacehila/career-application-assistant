#requires -Version 5.1

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$privateRoot = Join-Path $repositoryRoot 'private'
$overlayFiles = @(
    @{
        Template = 'resume_materials.example.md'
        Destination = 'resume_materials.md'
    },
    @{
        Template = 'job_search_preferences.example.md'
        Destination = 'job_search_preferences.md'
    }
)

foreach ($overlayFile in $overlayFiles) {
    $templatePath = Join-Path $repositoryRoot $overlayFile.Template
    if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf)) {
        throw "The public repository is missing $($overlayFile.Template)."
    }
}

if (Test-Path -LiteralPath $privateRoot) {
    if (-not (Test-Path -LiteralPath $privateRoot -PathType Container)) {
        throw 'private exists and is not a directory.'
    }
}
else {
    New-Item -ItemType Directory -Path $privateRoot | Out-Null
}

foreach ($overlayFile in $overlayFiles) {
    $templatePath = Join-Path $repositoryRoot $overlayFile.Template
    $destinationPath = Join-Path $privateRoot $overlayFile.Destination
    $displayPath = "private/$($overlayFile.Destination)"

    if (Test-Path -LiteralPath $destinationPath) {
        if (-not (Test-Path -LiteralPath $destinationPath -PathType Leaf)) {
            throw "$displayPath exists and is not a file."
        }

        Write-Output "$displayPath is already initialized; existing content was not read or changed."
        continue
    }

    Copy-Item -LiteralPath $templatePath -Destination $destinationPath -ErrorAction Stop
    Write-Output "Created $displayPath from the public placeholder template."
}

Write-Output 'RESULT: PASS'
Write-Output 'Place personal attachments and applications.sqlite directly in private/.'
