$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$uvPath = Join-Path $projectRoot '.tools/uv/uv.exe'
if (-not (Test-Path -LiteralPath $uvPath)) {
    New-Item -ItemType Directory -Force -Path '.tools' | Out-Null
    & curl.exe -fL --connect-timeout 15 --max-time 180 'https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-pc-windows-msvc.zip' -o '.tools/uv.zip'
    if ($LASTEXITCODE -ne 0) { throw 'uv download failed' }
    $expectedHash = 'a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f'
    if ((Get-FileHash -LiteralPath '.tools/uv.zip' -Algorithm SHA256).Hash -ne $expectedHash) { throw 'uv checksum mismatch' }
    Expand-Archive -LiteralPath '.tools/uv.zip' -DestinationPath '.tools/uv' -Force
}
$env:UV_CACHE_DIR = Join-Path $projectRoot '.tools/uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools/python'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
& $uvPath python install 3.12.16 --no-bin --no-registry
if ($LASTEXITCODE -ne 0) { throw 'Python installation failed' }
& $uvPath sync --project services/laya --locked
if ($LASTEXITCODE -ne 0) { throw 'Laya dependency installation failed' }
Write-Output 'Runtime ready. Download and test the pinned model with: .venv/Scripts/python.exe services/laya/probe.py'
