#!/usr/bin/env bash
# Build the SPA and copy it into mhc-desktop-backend's static dir.
# The Electron host loads the SPA from the backend itself, so the renderer
# sees the SPA at the same origin as the API (no CORS, no file:// pitfalls).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONT_DIR="$ROOT/mhc-desktop-frontend"
BACKEND_DIR="$ROOT/mhc-desktop-backend"
STATIC_DIR="$BACKEND_DIR/src/mhc_desktop_backend/static"

echo "[build-spa] vite build"
( cd "$FRONT_DIR" && npm install --cache "$ROOT/.npm-cache" && npx vite build )

echo "[build-spa] copy dist -> $STATIC_DIR"
mkdir -p "$STATIC_DIR"
# Clean only the dirs we own; leave anything else (favicon, etc.) alone.
rm -rf "$STATIC_DIR/assets" "$STATIC_DIR/fonts" "$STATIC_DIR/index.html"
cp -R "$FRONT_DIR/dist/." "$STATIC_DIR/"

echo "[build-spa] done: $(du -sh "$STATIC_DIR" | cut -f1)"