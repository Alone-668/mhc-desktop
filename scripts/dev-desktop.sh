#!/usr/bin/env bash
# Start the mhc-desktop base: desktop backend (:8765) + desktop frontend (:5180).
#
# This is the desktop client itself. It optionally talks to the skill-market
# backend (for market browse / sync) — start that too via dev-market-backend.sh.
#
# Env:
#   MHC_PORT           desktop backend port (default 8765)
#   MHC_FRONTEND_PORT  desktop frontend port (default 5180)
#   MHC_DATA_DIR       desktop data dir (default ~/.mhc-desktop)
#   MHC_MARKET_URL     market backend URL (default unset → market features off)
#   MHC_MARKET_SECRET  HMAC secret shared with market backend
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export NO_PROXY="localhost,127.0.0.1,0.0.0.0"
BACKEND_PORT="${MHC_PORT:-8765}"
FRONTEND_PORT="${MHC_FRONTEND_PORT:-5180}"
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"
export MHC_PORT="$BACKEND_PORT"
export MHC_BACKEND="${MHC_BACKEND:-http://127.0.0.1:$BACKEND_PORT}"
# Desktop data dir (per-user local store). Dev default to /tmp to avoid
# clobbering your real ~/.mhc-desktop unless you set MHC_DATA_DIR.
export MHC_DATA_DIR="${MHC_DATA_DIR:-/tmp/mhc-desktop-dev-data}"
# Market integration (optional): point at the running market backend.
if [ -n "${MHC_MARKET_URL:-}" ]; then
  export MHC_MARKET_URL
  export MHC_MARKET_SECRET="${MHC_MARKET_SECRET:-dev-secret}"
fi

pids=()
cleanup() {
  echo ""
  echo "[desktop] Stopping ..."
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait_for() {
  local url="$1" label="$2" max="${3:-40}" i
  for i in $(seq 1 "$max"); do
    if curl -sf "$url" >/dev/null 2>&1; then echo "  $label ready"; return 0; fi
    sleep 1
  done
  echo "  ERROR: $label not ready in ${max}s"; return 1
}

echo "[desktop] Backend on :$BACKEND_PORT ..."
(uv run python -m mhc_desktop_deploy) > "$LOG_DIR/desktop-backend.log" 2>&1 &
BACKEND_PID=$!
pids+=("$BACKEND_PID")
wait_for "http://127.0.0.1:$BACKEND_PORT/ready" "Desktop backend (:$BACKEND_PORT)" || { tail -30 "$LOG_DIR/desktop-backend.log"; exit 1; }

if [ ! -d "$ROOT/mhc-desktop-frontend/node_modules" ]; then
  echo "[desktop] Installing frontend deps ..."
  (cd "$ROOT/mhc-desktop-frontend" && npm install --cache "$ROOT/.npm-cache")
fi

echo "[desktop] Frontend on :$FRONTEND_PORT ..."
(cd "$ROOT/mhc-desktop-frontend" && npm run dev) > "$LOG_DIR/desktop-frontend.log" 2>&1 &
FRONTEND_PID=$!
pids+=("$FRONTEND_PID")
wait_for "http://localhost:$FRONTEND_PORT/" "Desktop frontend (:$FRONTEND_PORT)" || { tail -30 "$LOG_DIR/desktop-frontend.log"; exit 1; }

cat <<EOF

=============================================
  mhc-desktop (client) is up
=============================================
  Desktop backend  → http://127.0.0.1:$BACKEND_PORT
                         health: http://127.0.0.1:$BACKEND_PORT/api/v1/health
  Desktop frontend → http://127.0.0.1:$FRONTEND_PORT
  Logs:
    tail -f $LOG_DIR/desktop-backend.log
    tail -f $LOG_DIR/desktop-frontend.log
  (Market features need the market backend: bash scripts/dev-market-backend.sh)
  Ctrl+C → stop both.
=============================================
EOF
wait
