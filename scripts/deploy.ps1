#Requires -Version 5.1
<#
.SYNOPSIS
  Desde la notebook: despliega ApiDespacho en la VM por SSH.

.DESCRIPTION
  No corre el update en este PC. Abre SSH a 172.16.100.12 y en la VM:
  stop ApiDespacho + git pull + pip + start + /salud.

  Use -CheckOnly para probar SSH, repo y servicio SIN detener nada.

  Variables (opcionales; tambien acepta las de CCL):
    API_DESPACHO_VM_HOST / CCL_VM_HOST     default 172.16.100.12
    API_DESPACHO_VM_USER / CCL_VM_USER     default nmartinez
    API_DESPACHO_VM_SSH_KEY / CCL_VM_SSH_KEY
    API_DESPACHO_VM_REPO                   default C:\Servicios_DM\ApiDespacho

.EXAMPLE
  .\scripts\deploy.ps1 -CheckOnly

.EXAMPLE
  .\scripts\deploy.ps1
#>
[CmdletBinding()]
param(
  [switch] $CheckOnly,
  [string] $Branch = 'main',
  [string] $ServiceName = 'ApiDespacho'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string] $Message) {
  Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Get-EnvOr([string] $Primary, [string] $Fallback, [string] $Default) {
  foreach ($name in @($Primary, $Fallback)) {
    $v = [string] (Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue).Value
    if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
  }
  return $Default
}

function Get-DefaultIdentity {
  $configured = Get-EnvOr 'API_DESPACHO_VM_SSH_KEY' 'CCL_VM_SSH_KEY' ''
  if (-not [string]::IsNullOrWhiteSpace($configured)) { return $configured }
  $candidates = @(
    (Join-Path $env:USERPROFILE '.ssh\ccl_vm_deploy'),
    (Join-Path $env:USERPROFILE '.ssh\id_ed25519')
  )
  foreach ($path in $candidates) {
    if (Test-Path -LiteralPath $path) { return $path }
  }
  return $candidates[0]
}

function Invoke-VmEncodedScript {
  param([string] $ScriptBody)
  $b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($ScriptBody))
  $sshArgs = @(
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-i', $IdentityFile,
    ('{0}@{1}' -f $VmUser, $VmHost),
    "powershell -NoProfile -EncodedCommand $b64"
  )
  & ssh @sshArgs | ForEach-Object { Write-Host $_ }
  return [int] $LASTEXITCODE
}

$VmHost = Get-EnvOr 'API_DESPACHO_VM_HOST' 'CCL_VM_HOST' '172.16.100.12'
$VmUser = Get-EnvOr 'API_DESPACHO_VM_USER' 'CCL_VM_USER' 'nmartinez'
$RepoPath = Get-EnvOr 'API_DESPACHO_VM_REPO' 'CCL_VM_REPO' 'C:\Servicios_DM\ApiDespacho'
if ($RepoPath -eq 'C:\Servicios_DM\CCL') { $RepoPath = 'C:\Servicios_DM\ApiDespacho' }
$IdentityFile = Get-DefaultIdentity

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
  throw 'No se encontro el cliente ssh. Active OpenSSH Client o Git en el PATH.'
}
if (-not (Test-Path -LiteralPath $IdentityFile)) {
  throw "No se encontro la llave SSH: $IdentityFile"
}

$repoLiteral = $RepoPath.Replace("'", "''")
$branchLiteral = $Branch.Replace("'", "''")
$serviceLiteral = $ServiceName.Replace("'", "''")

Write-Step 'Destino'
Write-Host "  Host:     $VmUser@$VmHost"
Write-Host "  Repo:     $RepoPath"
Write-Host "  Llave:    $IdentityFile"
Write-Host "  Rama:     $Branch"
Write-Host "  Servicio: $ServiceName"
Write-Host "  Modo:     $(if ($CheckOnly) { 'solo chequeo' } else { 'deploy remoto' })"

if ($CheckOnly) {
  Write-Step 'Chequeo remoto (sin stop / pull)'
  $checkScript = @"
`$ProgressPreference = 'SilentlyContinue'
`$ErrorActionPreference = 'Continue'
function Out-Check([string] `$Message) { Write-Output `$Message }
Out-Check '=== HOST / USUARIO ==='
Out-Check ((hostname) + ' / ' + (whoami))
`$repo = '$repoLiteral'
if (-not (Test-Path -LiteralPath (Join-Path `$repo 'app\main.py'))) {
  Out-Check "FALLO: no existe `$repo\app\main.py"
  exit 2
}
Set-Location -LiteralPath `$repo
Out-Check ("OK repo " + `$repo)
if (Test-Path -LiteralPath (Join-Path `$repo 'VERSION')) {
  Out-Check ("VERSION=" + (Get-Content -LiteralPath (Join-Path `$repo 'VERSION') -TotalCount 1))
}
git status -sb
git log -1 --oneline
Out-Check '=== GIT REMOTO ==='
git ls-remote origin HEAD
if (`$LASTEXITCODE -ne 0) {
  Out-Check 'FALLO: git no autentica contra origin.'
  `$gitOk = `$false
} else {
  Out-Check 'OK git ls-remote'
  `$gitOk = `$true
}
Out-Check '=== SERVICIO ==='
`$svc = Get-Service -Name '$serviceLiteral' -ErrorAction SilentlyContinue
if (-not `$svc) {
  Out-Check "FALLO: no existe el servicio '$serviceLiteral'"
  exit 3
}
Out-Check ("OK servicio " + `$svc.Name + " Status=" + `$svc.Status)
try {
  `$salud = (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:4190/salud' -TimeoutSec 5).Content
  Out-Check ("salud=" + `$salud)
} catch {
  Out-Check ("AVISO: /salud no respondio: " + `$_.Exception.Message)
}
if (-not `$gitOk) { exit 4 }
Out-Check '=== CHEQUEO OK ==='
exit 0
"@
  $code = Invoke-VmEncodedScript -ScriptBody $checkScript
  if ($code -ne 0) { throw "El chequeo remoto termino con codigo $code." }
  Write-Host "`nChequeo listo. El servicio no se detuvo." -ForegroundColor Green
  exit 0
}

Write-Step 'Update remoto'
$updateScript = @"
`$ProgressPreference = 'SilentlyContinue'
`$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath '$repoLiteral'
if (Test-Path -LiteralPath '.\scripts\vm-update.ps1') {
  & .\scripts\vm-update.ps1 -ServiceName '$serviceLiteral' -Branch '$branchLiteral'
  exit `$LASTEXITCODE
}
`$svc = Get-Service -Name '$serviceLiteral' -ErrorAction SilentlyContinue
if (`$svc -and `$svc.Status -ne 'Stopped') {
  Stop-Service -Name '$serviceLiteral'
  (Get-Service -Name '$serviceLiteral').WaitForStatus('Stopped', '00:00:30')
}
git pull origin '$branchLiteral'
if (`$LASTEXITCODE -ne 0) { throw 'git pull fallo' }
`$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& `$py -m pip install -r requirements.txt -q
if (`$svc) {
  Start-Service -Name '$serviceLiteral'
  (Get-Service -Name '$serviceLiteral').WaitForStatus('Running', '00:00:30')
}
`$ok = `$false
for (`$i = 0; `$i -lt 12; `$i += 1) {
  try {
    Write-Output (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:4190/salud' -TimeoutSec 3).Content
    `$ok = `$true
    break
  } catch { Start-Sleep -Seconds 1 }
}
if (-not `$ok) { throw 'Sin respuesta en /salud' }
exit 0
"@
$code = Invoke-VmEncodedScript -ScriptBody $updateScript
if ($code -ne 0) { throw "El deploy remoto termino con codigo $code." }
Write-Host "`nDeploy remoto listo." -ForegroundColor Green
