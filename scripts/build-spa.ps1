# Build the SPA and copy it into mhc-desktop-backend's static dir.
# Mirrors scripts/build-spa.sh for Windows.
$ErrorActionPreference = "Stop"

$ROOT       = (Resolve-Path "$PSScriptRoot/..").Path
$FRONT_DIR  = Join-Path $ROOT "mhc-desktop-frontend"
$BACKEND_DIR= Join-Path $ROOT "mhc-desktop-backend"
$STATIC_DIR = Join-Path $BACKEND_DIR "src/mhc_desktop_backend/static"

Write-Host "[build-spa] vite build"
Push-Location $FRONT_DIR
try {
    npm install --cache "$ROOT/.npm-cache" | Out-Host
    npx vite build | Out-Host
} finally { Pop-Location }

Write-Host "[build-spa] copy dist -> $STATIC_DIR"
New-Item -ItemType Directory -Force -Path $STATIC_DIR | Out-Null
foreach ($d in @("assets","fonts")) {
    $p = Join-Path $STATIC_DIR $d
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
$idx = Join-Path $STATIC_DIR "index.html"
if (Test-Path $idx) { Remove-Item -Force $idx }

Copy-Item -Recurse -Force (Join-Path $FRONT_DIR "dist/*") $STATIC_DIR

Write-Host "[build-spa] done"