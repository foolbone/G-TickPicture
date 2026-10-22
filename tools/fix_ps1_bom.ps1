<#
.SYNOPSIS
    Re-encode every .ps1 under a directory as UTF-8 WITH BOM.

.DESCRIPTION
    Windows PowerShell 5.1 decodes a BOM-less .ps1 file as ANSI
    (code page 936 / GBK on zh-CN Windows). Chinese text then turns into
    mojibake, and worse: some UTF-8 byte triplets decode into a GBK lead byte
    that swallows the following newline, so reported line numbers also drift.
    The result is a flood of ParserError.

    PowerShell 7.x reads UTF-8 by default and never shows the problem, which
    makes this a classic "works on my machine" trap.

    This script is intentionally ASCII-only so that it can always run, even
    when every other script in the folder is broken by the same issue.

    Safety:
      - never deletes, moves or renames anything
      - only rewrites the file encoding; text content is preserved as-is
      - refuses to touch a file that is not valid UTF-8 (avoids double-damage)
      - idempotent: files that already carry a BOM are skipped

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\fix_ps1_bom.ps1
    powershell -ExecutionPolicy Bypass -File .\tools\fix_ps1_bom.ps1 -DryRun
#>

[CmdletBinding()]
param(
    [string] $Dir = $PSScriptRoot,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Dir)) { $Dir = (Get-Location).Path }
if (-not (Test-Path $Dir)) { throw "Directory not found: $Dir" }

$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)   # throws on invalid bytes
$utf8Bom    = New-Object System.Text.UTF8Encoding($true)

Write-Host ''
Write-Host ('-' * 62) -ForegroundColor DarkGray
Write-Host '  PS1 encoding check (UTF-8 with BOM)' -ForegroundColor Cyan
Write-Host ('-' * 62) -ForegroundColor DarkGray
Write-Host "  dir: $Dir"

$files = @(Get-ChildItem -Path $Dir -Filter '*.ps1' -Recurse -File -ErrorAction SilentlyContinue)
if ($files.Count -eq 0) {
    Write-Host '  no .ps1 file found'
    exit 0
}

$fixed = 0
$skipped = 0

foreach ($f in $files) {
    $bytes = [IO.File]::ReadAllBytes($f.FullName)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)

    if ($hasBom) {
        Write-Host ("  [SKIP] " + $f.Name + "  (already UTF-8 BOM)") -ForegroundColor DarkGray
        $skipped++
        continue
    }

    $text = $null
    try {
        $text = $utf8Strict.GetString($bytes)
    } catch {
        Write-Host ("  [SKIP] " + $f.Name + "  (not valid UTF-8 - refusing to touch, fix it by hand)") -ForegroundColor Yellow
        $skipped++
        continue
    }

    if ($DryRun) {
        Write-Host ("  [DRY ] " + $f.Name + "  would add BOM") -ForegroundColor Cyan
        $fixed++
        continue
    }

    [IO.File]::WriteAllText($f.FullName, $text, $utf8Bom)
    Write-Host ("  [ OK ] " + $f.Name + "  BOM added") -ForegroundColor Green
    $fixed++
}

Write-Host ('-' * 62) -ForegroundColor DarkGray
if ($DryRun) {
    Write-Host ("  dry run: $fixed file(s) would be fixed, $skipped skipped") -ForegroundColor Cyan
} else {
    Write-Host ("  fixed: $fixed   skipped: $skipped   total: " + $files.Count) -ForegroundColor Green
}
Write-Host '  Note: re-run this after editing any .ps1 with a tool that writes plain UTF-8.'
Write-Host ''

if ($fixed -gt 0 -and -not $DryRun) { exit 0 }
exit 0
