$ErrorActionPreference = "Stop"

$frontendDir = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $frontendDir
$sidecarDist = Join-Path $repoRoot "dist\rivenforge-api.exe"
$targetDir = Join-Path $frontendDir "src-tauri\binaries"
$targetExe = Join-Path $targetDir "rivenforge-api-x86_64-pc-windows-msvc.exe"

Push-Location $repoRoot
try {
    python -m PyInstaller api_sidecar.spec
}
finally {
    Pop-Location
}

New-Item -ItemType Directory -Force $targetDir | Out-Null
Copy-Item -Force $sidecarDist $targetExe
Write-Host "Copied sidecar to $targetExe"
