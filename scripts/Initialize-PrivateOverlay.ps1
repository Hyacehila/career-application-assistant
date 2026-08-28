#requires -Version 5.1

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$privateRoot = Join-Path $repositoryRoot 'private'
$templatePath = Join-Path $repositoryRoot 'resume_materials.example.md'
$materialsPath = Join-Path $privateRoot 'resume_materials.md'

if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf)) {
    throw 'The public repository is missing resume_materials.example.md.'
}

if (Test-Path -LiteralPath $privateRoot) {
    if (-not (Test-Path -LiteralPath $privateRoot -PathType Container)) {
        throw 'private exists and is not a directory.'
    }

    $existingItems = @(Get-ChildItem -LiteralPath $privateRoot -Force)
    if ($existingItems.Count -ne 0) {
        throw 'private must be empty; existing files are never overwritten.'
    }
}
else {
    New-Item -ItemType Directory -Path $privateRoot | Out-Null
}

Copy-Item -LiteralPath $templatePath -Destination $materialsPath

Write-Output 'RESULT: PASS'
Write-Output 'Created private/resume_materials.md from the public placeholder template.'
Write-Output 'Place personal attachments and applications.sqlite directly in private/.'
