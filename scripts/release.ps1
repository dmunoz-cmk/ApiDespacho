#Requires -Version 5.1
<#
.SYNOPSIS
  Release local: tests, bump de VERSION, tag y push. No toca la VM.

.DESCRIPTION
  1) unittest
  2) commit de cambios pendientes (si hay)
  3) incrementa VERSION (patch | minor | major)
  4) tag vX.Y.Z
  5) git push origin <rama> --follow-tags

  Despues: .\scripts\deploy.ps1  (o deploy.bat) para publicar en la VM.

.PARAMETER Bump
  patch | minor | major (por defecto: patch)

.PARAMETER CommitMessage
  Mensaje si hay cambios sin commitear (no incluye VERSION).

.PARAMETER SkipTests
  No corre unittest.

.PARAMETER SkipPush
  Deja el tag solo en local.

.EXAMPLE
  .\scripts\release.ps1 -Bump patch -CommitMessage "fix: ajuste cryo"

.EXAMPLE
  .\release.bat
#>
[CmdletBinding()]
param(
  [ValidateSet('patch', 'minor', 'major')]
  [string] $Bump = 'patch',
  [string] $CommitMessage = '',
  [string] $Branch = 'main',
  [switch] $SkipTests,
  [switch] $SkipPush
)

$ErrorActionPreference = 'Stop'

foreach ($gitDir in @('C:\Program Files\Git\bin', 'C:\Program Files (x86)\Git\bin')) {
  if ((Test-Path $gitDir) -and ($env:Path -notlike "*${gitDir}*")) {
    $env:Path = "${gitDir};" + $env:Path
  }
}

function Write-Step([string] $Message) {
  Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Get-Semver([string] $Raw) {
  if ($Raw -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
    throw "VERSION invalida: '$Raw'. Use X.Y.Z"
  }
  return @{ Major = [int]$Matches[1]; Minor = [int]$Matches[2]; Patch = [int]$Matches[3] }
}

function Format-Semver($v) {
  return '{0}.{1}.{2}' -f $v.Major, $v.Minor, $v.Patch
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw 'Git no esta en el PATH.'
}

Write-Step '1. Estado'
git status -sb

if (-not $SkipTests) {
  Write-Step '2. Tests'
  $py = Join-Path $RepoRoot '.venv\Scripts\python.exe'
  if (-not (Test-Path -LiteralPath $py)) { $py = 'python' }
  $env:PYTHONPATH = $RepoRoot
  & $py -m unittest discover -s tests -v
  if ($LASTEXITCODE -ne 0) { throw "Los tests fallaron (codigo $LASTEXITCODE)." }
} else {
  Write-Host "`n(Tests omitidos: -SkipTests)" -ForegroundColor DarkYellow
}

git add -u
git add VERSION scripts app/main.py
git diff --cached --quiet
$stagedEmpty = ($LASTEXITCODE -eq 0)

if (-not $stagedEmpty) {
  if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
    $CommitMessage = Read-Host 'Mensaje del commit (antes del bump de VERSION)'
  }
  if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
    throw 'Hay cambios pendientes. Indique -CommitMessage.'
  }
  Write-Step "3. Commit`n   $CommitMessage"
  git commit -m $CommitMessage
} else {
  Write-Host "`n(No hay cambios pendientes; se salta el commit previo.)" -ForegroundColor DarkYellow
}

$versionFile = Join-Path $RepoRoot 'VERSION'
if (-not (Test-Path -LiteralPath $versionFile)) {
  Set-Content -LiteralPath $versionFile -Value '0.1.0' -Encoding ascii
}
$actual = (Get-Content -LiteralPath $versionFile -TotalCount 1).Trim()
$v = Get-Semver $actual
switch ($Bump) {
  'major' { $v.Major += 1; $v.Minor = 0; $v.Patch = 0 }
  'minor' { $v.Minor += 1; $v.Patch = 0 }
  default { $v.Patch += 1 }
}
$nueva = Format-Semver $v
Set-Content -LiteralPath $versionFile -Value $nueva -Encoding ascii
Write-Step "4. VERSION $actual -> $nueva"
git add VERSION
git commit -m "chore: release v$nueva"
if ($LASTEXITCODE -ne 0) { throw 'No se pudo commitear VERSION.' }
git tag -a "v$nueva" -m "ApiDespacho v$nueva"

if (-not $SkipPush) {
  Write-Step "5. Push origin/$Branch --follow-tags"
  git push origin $Branch --follow-tags
  if ($LASTEXITCODE -ne 0) { throw 'git push fallo.' }
} else {
  Write-Host "`n(Push omitido: -SkipPush)" -ForegroundColor DarkYellow
}

Write-Host ''
Write-Host "Release listo: v$nueva" -ForegroundColor Green
Write-Host 'Para publicar en la VM:  .\deploy.bat   o   .\scripts\deploy.ps1' -ForegroundColor Green
