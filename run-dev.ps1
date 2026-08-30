# StudyThing dev mode for Windows (PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { Write-Host "Run .\setup.ps1 first."; exit 1 }

Start-Process powershell -ArgumentList "-NoExit", "-Command", ".\.venv\Scripts\python -m uvicorn backend.main:app --port 8765"
Set-Location frontend
npm run dev