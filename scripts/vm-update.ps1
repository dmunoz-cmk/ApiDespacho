#Requires -Version 5.1
<#
.SYNOPSIS
  En la VM: detiene el servicio, trae main y vuelve a levantar ApiDespacho.

.DESCRIPTION
  Corre en el servidor (C:\Servicios_DM\ApiDespacho). Desde la notebook use
  scripts\deploy.ps1, que dispara este flujo por SSH.

.PARAMETER ServiceName
  Servicio Windows NSSM (por defecto: ApiDespacho).

.PARAMETER Branch
  Rama a traer (por defecto: main).
#>
[CmdletBinding()]
param(
  [string] $ServiceName = 'ApiDespacho',
  [string] $Branch = 'main'
)

$ErrorActionPreference = 'Stop'

function Write-Step([string] $Message) {
  Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path (Join-Path $RepoRoot 'app\main.py'))) {
  throw "No se encontro app\main.py en $RepoRoot."
}

$svc = $null
if ($ServiceName) {
  $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
}

if ($svc) {
  Write-Step "1. Detener servicio '$ServiceName' (estado: $($svc.Status))"
  if ($svc.Status -ne 'Stopped') {
    Stop-Service -Name $ServiceName
    (Get-Service -Name $ServiceName).WaitForStatus('Stopped', '00:00:30')
  }
} else {
  Write-Step "1. Sin servicio '$ServiceName'; se omite el stop"
}

Write-Step "2. git pull origin $Branch"
git pull origin $Branch
if ($LASTEXITCODE -ne 0) { throw "git pull fallo (codigo $LASTEXITCODE)" }

$venvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
  throw "No esta el venv en $venvPy"
}

Write-Step '3. Dependencias del venv'
& $venvPy -m pip install -r (Join-Path $RepoRoot 'requirements.txt') -q
if ($LASTEXITCODE -ne 0) { throw "pip install fallo (codigo $LASTEXITCODE)" }

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.env'))) {
  Write-Host "AVISO: no hay .env. La API no va a leer SQL." -ForegroundColor Yellow
}

if ($svc) {
  Write-Step "4. Iniciar servicio '$ServiceName'"
  Start-Service -Name $ServiceName
  (Get-Service -Name $ServiceName).WaitForStatus('Running', '00:00:30')
} else {
  Write-Step '4. Sin servicio para iniciar'
}

Write-Step '5. Salud'
$ok = $false
$ultimo = ''
for ($i = 0; $i -lt 12; $i += 1) {
  try {
    $ultimo = (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:4190/salud' -TimeoutSec 3).Content
    $ok = $true
    break
  } catch {
    Start-Sleep -Seconds 1
  }
}
if (-not $ok) { throw "El servicio no respondio /salud. Ultimo error: $ultimo" }
Write-Host $ultimo -ForegroundColor Green

$version = (Get-Content -LiteralPath (Join-Path $RepoRoot 'VERSION') -ErrorAction SilentlyContinue | Select-Object -First 1)
Write-Host "`nListo. Version desplegada: $version" -ForegroundColor Green
