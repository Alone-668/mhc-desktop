# Build the SPA and copy it into mhc-desktop-backend's static dir.
# Mirrors scripts/build-spa.sh for Windows.
$ErrorActionPreference = "Stop"

$ROOT       = (Resolve-Path "$PSScriptRoot/..").Path
$FRONT_DIR  = Join-Path $ROOT "mhc-desktop-frontend"
$BACKEND_DIR= Join-Path $ROOT "mhc-desktop-backend"
$STATIC_DIR = Join-Path $BACKEND_DIR "src/mhc_desktop_backend/static"

# sherpa-onnx WASM voice model (~203MB) is intentionally NOT committed
# to git (binaries from https://github.com/k2-fsa/sherpa-onnx/releases,
# v1.13.6 wasm-simd zh-en-asr-zipformer — see docs/PACKAGING.md 6.4).
# Without the model files the SPA build still succeeds but the packaged
# app's voice input silently has no recognizer, so fail fast here
# instead of shipping a bad installer.
$SHERPA_DIR = Join-Path $FRONT_DIR "public/sherpa"
$sherpaFiles = @("sherpa-onnx-asr.js", "sherpa-onnx-wasm-main-asr.js", "sherpa-onnx-wasm-main-asr.wasm", "sherpa-onnx-wasm-main-asr.data")
$missing = 0
foreach ($f in $sherpaFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $SHERPA_DIR $f) -PathType Leaf)) {
        Write-Host "[build-spa] ERROR: missing voice model: $f"
        $missing = 1
    }
}
if ($missing -eq 1) {
    Write-Host "[build-spa] sherpa-onnx voice model not present. Restore it from"
    Write-Host "            https://github.com/k2-fsa/sherpa-onnx/releases (v1.13.6,"
    Write-Host "            sherpa-onnx-wasm-simd-v1.13.6-zh-en-asr-zipformer.tar.bz2)"
    Write-Host "            into $SHERPA_DIR before packaging. See docs/PACKAGING.md 6.4."
    throw "missing sherpa-onnx voice model"
}

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