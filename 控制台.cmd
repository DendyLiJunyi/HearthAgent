@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run scripts\setup-runtime.ps1 in PowerShell first.
    pause
    exit /b 1
)
start "" /b ".venv\Scripts\pythonw.exe" -X utf8 -m agent.control_panel
