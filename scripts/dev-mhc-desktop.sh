#!/usr/bin/env bash
# Start the mhc-desktop dev loop: backend (uvicorn --reload) + frontend (vite).
#
# Usage: bash scripts/dev-mhc-desktop.sh
# Env:
#   MHC_PORT          backend port (default 8765)
#   MHC_FRONTEND_PORT frontend port (default 5180)
#   MHC_HOST          backend bind (default 127.0.0.1)
#   MHC_BACKEND       frontend→backend target (default http://127.0.0.1:8765)
#   MHC_RELOAD        1 to enable uvicorn reload (default 1)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# macOS system proxies interfere with localhost service-to-service calls.
export NO_PROXY="localhost,127.0.0.1,0.0.0.0"

BACKEND_PORT="${MHC_PORT:-8765}"
FRONTEND_PORT="${MHC_FRONTEND_PORT:-5180}"
export MHC_PORT="$BACKEND_PORT"
export MHC_BACKEND="${MHC_BACKEND:-http://127.0.0.1:$BACKEND_PORT}"

LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"

pids=()

cleanup() {
  echo ""
  echo "[mhc-dev] Stopping ..."
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait_for() {
  local url="$1" label="$2" max="${3:-30}"
  local i
  for i in $(seq 1 "$max"); do
    if curl -sf "$url" > /dev/null 2>&1; then
      echo "[mhc-dev]   $label ready"
      return 0
    fi
    sleep 1
  done
  echo "[mhc-dev]   ERROR: $label did not become ready within ${max}s"
  return 1
}

echo "[mhc-dev] Starting backend on :$BACKEND_PORT ..."
(python -m mhc_desktop_deploy) > "$LOG_DIR/mhc-desktop-backend.log" 2>&1 &
BACKEND_PID=$!
pids+=("$BACKEND_PID")

wait_for "http://127.0.0.1:$BACKEND_PORT/ready" "Backend (:$BACKEND_PORT)" || {
  echo "[mhc-dev]   tail: $LOG_DIR/mhc-desktop-backend.log"
  exit 1
}

echo "[mhc-dev] Installing frontend deps (if needed) ..."
if [ ! -d "$ROOT/packages/mhc-desktop-frontend/node_modules" ]; then
  (cd "$ROOT/packages/mhc-desktop-frontend" && npm install --cache "$ROOT/.npm-cache")
fi

echo "[mhc-dev] Starting frontend on :$FRONTEND_PORT ..."
(cd "$ROOT/packages/mhc-desktop-frontend" && npm run dev) > "$LOG_DIR/mhc-desktop-frontend.log" 2>&1 &
FRONTEND_PID=$!
pids+=("$FRONTEND_PID")

wait_for "http://localhost:$FRONTEND_PORT/" "Frontend (:$FRONTEND_PORT)" || {
  echo "[mhc-dev]   tail: $LOG_DIR/mhc-desktop-frontend.log"
  exit 1
}

cat <<EOF

=============================================
  mhc-desktop dev loop is up
=============================================

  Backend   → http://127.0.0.1:$BACKEND_PORT
               health: http://127.0.0.1:$BACKEND_PORT/api/v1/health
               docs:   http://127.0.0.1:$BACKEND_PORT/docs
  Frontend  → http://127.0.0.1:$FRONTEND_PORT

  Logs:
    tail -f $LOG_DIR/mhc-desktop-backend.log
    tail -f $LOG_DIR/mhc-desktop-frontend.log

  Backend has hot reload (uvicorn --reload).
  Frontend has HMR (vite).

  Press Ctrl+C to stop.
=============================================
EOF

wait
