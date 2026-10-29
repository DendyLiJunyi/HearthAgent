$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectRoot '.data/laya-service.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Output 'No recorded Laya service'; exit 0 }
$saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$service = Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
if (-not $service) { Write-Output 'Recorded Laya service has exited'; exit 0 }
if ($service.StartTime.ToUniversalTime().Ticks.ToString() -ne $saved.start_ticks) { throw 'PID was reused; refusing to stop an unrelated process' }
Stop-Process -Id $service.Id
Write-Output 'Project Laya service stopped'
