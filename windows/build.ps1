# Build StudyThing-windows.zip: exe + bundled ffmpeg + whisper.cpp + model.
# Runs on Windows (CI or a friend's machine with git + python 3.11 + node 20).
param(
  [switch]$SkipFrontend,   # frontend/dist already built
  [switch]$SkipPyInstaller # StudyThing.exe already built, just repack
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ---------- 1. frontend ----------
if (-not $SkipFrontend) {
  Push-Location ..\frontend
  npm install --no-audit --no-fund
  npm run build
  Pop-Location
}
if (-not (Test-Path ..\frontend\dist\index.html)) { Write-Error "frontend/dist missing"; exit 1 }

# ---------- 2. python deps + pyinstaller ----------
Push-Location ..
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet pyinstaller
Pop-Location

# ---------- 3. pyinstaller exe ----------
if (-not $SkipPyInstaller) {
  Push-Location ..
  python -m PyInstaller --clean --noconfirm windows\studything.spec
  Pop-Location
}
if (-not (Test-Path ..\dist\StudyThing.exe)) { Write-Error "StudyThing.exe not built"; exit 1 }

# ---------- 4. bundle dir ----------
$out = "bundle"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force -Path "$out\bin" | Out-Null
Copy-Item ..\dist\StudyThing.exe "$out\StudyThing.exe"
Copy-Item "START-HERE.txt" "$out\START-HERE.txt"
# app version for the update checker: tag name in CI, date+hash locally
$ver = if ($env:GITHUB_REF_NAME) { $env:GITHUB_REF_NAME } else { "v1.0.0-$(Get-Date -Format yyyyMMdd)-$(git -C .. rev-parse --short HEAD)" }
Set-Content "$out\version.txt" $ver
Write-Host "    version: $ver"


function Fetch-WithRetry {
  param([string[]]$Urls, [string]$Out, [int]$Tries = 4)
  for ($i = 1; $i -le $Tries; $i++) {
    foreach ($u in $Urls) {
      try {
        Write-Host "    attempt $i -> $u"
        Invoke-WebRequest $u -OutFile $Out -UseBasicParsing -TimeoutSec 600
        if ((Get-Item $Out).Length -gt 50000) { return }
        Remove-Item $Out -ErrorAction SilentlyContinue
      } catch { Write-Host "    failed: $_" }
    }
    Start-Sleep -Seconds (5 * $i)
  }
  throw "download failed after $Tries attempts: $Out"
}

Write-Host "==> ffmpeg (static essentials)"
if (-not (Test-Path "$out\bin\ffmpeg.exe")) {
  Fetch-WithRetry @("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip") -OutFile ff.zip
  Expand-Archive -Force ff.zip ff
  $ffRoot = (Get-ChildItem ff -Directory | Select-Object -First 1).FullName
  Copy-Item "$ffRoot\bin\ffmpeg.exe" "$out\bin\ffmpeg.exe"
  Copy-Item "$ffRoot\bin\ffprobe.exe" "$out\bin\ffprobe.exe"
  Remove-Item -Recurse -Force ff, ff.zip
}

Write-Host "==> whisper.cpp (Vulkan build + large-v3-turbo q5_0 model, ~550 MB)"
if (-not (Test-Path "$out\bin\whisper-cli.exe")) {
  Fetch-WithRetry @("https://github.com/ggml-org/whisper.cpp/releases/latest/download/whisper-bin-x64.zip", "https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.4/whisper-bin-x64.zip") -OutFile wc.zip
  Expand-Archive -Force wc.zip wctmp
  $cli = Get-ChildItem -Recurse -Filter "whisper-cli.exe" wctmp | Select-Object -First 1
  Copy-Item $cli.FullName "$out\bin\whisper-cli.exe"
  # bring any DLLs next to the exe
  Get-ChildItem -Recurse -Include *.dll -Path (Split-Path $cli.FullName) | Copy-Item -Destination "$out\bin"
  Remove-Item -Recurse -Force wctmp, wc.zip
}
if (-not (Test-Path "$out\bin\ggml-large-v3-turbo-q5_0.bin")) {
  Fetch-WithRetry @("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin") -OutFile "$out\bin\ggml-large-v3-turbo-q5_0.bin"
}

# ---------- 5. zip ----------
$zipName = "..\StudyThing-windows.zip"
if (Test-Path $zipName) { Remove-Item $zipName }
Compress-Archive -Path "$out\*" -DestinationPath $zipName
Remove-Item -Recurse -Force $out
Write-Host ""
Write-Host "DONE -> StudyThing-windows.zip"
