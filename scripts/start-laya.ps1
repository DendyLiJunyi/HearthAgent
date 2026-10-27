param(
    [ValidateSet('cuda', 'cpu')][string]$Device = 'cuda',
    [ValidateRange(1, 65535)][int]$Port = 8791
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run scripts/setup-laya.ps1 first' }
$statePath = Join-Path $projectRoot '.data/laya-service.json'
if (Test-Path -LiteralPath $statePath) {
    $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $existing = Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if ($existing -and $existing.StartTime.ToUniversalTime().Ticks.ToString() -eq $saved.start_ticks) {
        throw 'The project Laya service is already running; use scripts/stop-laya.ps1 first'
    }
}
New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot '.data') | Out-Null
$service = Start-Process -FilePath $pythonPath -ArgumentList 'services/laya/run_server.py','--device',$Device,'--port',$Port -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot '.data/laya-stdout.log') -RedirectStandardError (Join-Path $projectRoot '.data/laya-stderr.log')
@{ pid = $service.Id; start_ticks = $service.StartTime.ToUniversalTime().Ticks.ToString(); port = $Port } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output "Laya startup requested: PID=$($service.Id), URL=http://127.0.0.1:$Port. Check /health or .data/laya-stderr.log for readiness."
