# StudyThing setup for Windows 10/11 (PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> 1/5 Python venv"
$py = $null
foreach ($c in @(@("py", "-3.11"), @("py", "-3.12"), @("python"))) {
  try { & $c[0] $c[1] --version *> $null; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch {}
}
if (-not $py) { Write-Error "Python 3.11+ not found — install from python.org first."; exit 1 }
Write-Host ("    using " + (& $py[0] $py[1] --version))
if (-not (Test-Path .venv)) { & $py[0] $py[1] -m venv .venv }
.\.venv\Scripts\python -m pip install --quiet --upgrade pip
.\.venv\Scripts\python -m pip install --quiet -r requirements.txt

Write-Host "==> 2/5 winget deps (ffmpeg, ollama, node)"
function Ensure-Winget($id, $cmd) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    Write-Host "    installing $id ..."
    winget install -e --id $id --accept-source-agreements --accept-package-agreements
  } else { Write-Host "    $cmd ok" }
}
Ensure-Winget "Gyan.FFmpeg" "ffmpeg"
Ensure-Winget "Ollama.Ollama" "ollama"
Ensure-Winget "OpenJS.NodeJS.LTS" "node"
Write-Host "    (if ffmpeg/ollama not found after install: open a NEW terminal and re-run this script)"

Write-Host "==> 3/5 ollama daemon"
try { ollama list *> $null } catch {
  Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe" -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 5
}

Write-Host "==> 4/5 pulling qwen3:8b (~5 GB, one time)"
$have = (ollama list | Select-String "qwen3:8b") -ne $null
if (-not $have) { ollama pull qwen3:8b }

Write-Host "==> 5/5 frontend deps"
Push-Location frontend
npm install --silent
Pop-Location

Write-Host ""
Write-Host "Setup complete. Start the app:"
Write-Host "  .\run-dev.ps1          # backend :8765 + Vite :5173"
Write-Host ""
Write-Host "First transcription downloads the Whisper model (~1.5 GB, one time)."
Write-Host "GPU (NVIDIA CUDA) is used automatically if present; otherwise CPU (slower)."