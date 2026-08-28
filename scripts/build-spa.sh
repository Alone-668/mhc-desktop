#!/usr/bin/env bash
# Build the SPA and copy it into mhc-desktop-backend's static dir.
# The Electron host loads the SPA from the backend itself, so the renderer
# sees the SPA at the same origin as the API (no CORS, no file:// pitfalls).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONT_DIR="$ROOT/mhc-desktop-frontend"
BACKEND_DIR="$ROOT/mhc-desktop-backend"
STATIC_DIR="$BACKEND_DIR/src/mhc_desktop_backend/static"

# sherpa-onnx WASM voice model (~203MB) is intentionally NOT committed
# to git (binaries from https://github.com/k2-fsa/sherpa-onnx/releases,
# v1.13.6 wasm-simd zh-en-asr-zipformer — see docs/PACKAGING.md §6.4).
# Without the model files the SPA build still succeeds but the packaged
# app's voice input silently has no recognizer, so fail fast here
# instead of shipping a bad installer.
SHERPA_DIR="$FRONT_DIR/public/sherpa"
missing=0
for f in sherpa-onnx-asr.js sherpa-onnx-wasm-main-asr.js sherpa-onnx-wasm-main-asr.wasm sherpa-onnx-wasm-main-asr.data; do
    if [ ! -f "$SHERPA_DIR/$f" ]; then
        echo "[build-spa] ERROR: missing voice model: $SHERPA_DIR/$f"
        missing=1
    fi
done
if [ "$missing" = "1" ]; then
    echo "[build-spa] sherpa-onnx voice model not present. Restore it from"
    echo "            https://github.com/k2-fsa/sherpa-onnx/releases (v1.13.6,"
    echo "            sherpa-onnx-wasm-simd-v1.13.6-zh-en-asr-zipformer.tar.bz2)"
    echo "            into $SHERPA_DIR/ before packaging. See docs/PACKAGING.md §6.4."
    exit 1
fi

echo "[build-spa] vite build"
( cd "$FRONT_DIR" && npm install --cache "$ROOT/.npm-cache" && npx vite build )

echo "[build-spa] copy dist -> $STATIC_DIR"
mkdir -p "$STATIC_DIR"
# Clean only the dirs we own; leave anything else (favicon, etc.) alone.
rm -rf "$STATIC_DIR/assets" "$STATIC_DIR/fonts" "$STATIC_DIR/index.html"
cp -R "$FRONT_DIR/dist/." "$STATIC_DIR/"

echo "[build-spa] done: $(du -sh "$STATIC_DIR" | cut -f1)"