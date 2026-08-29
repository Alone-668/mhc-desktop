#!/usr/bin/env bash
# Start the skill-market backend (standalone, :8766).
#
# Usage: bash scripts/dev-market-backend.sh
# Env:
#   MHC_MARKET_HOST      bind (default 127.0.0.1)
#   MHC_MARKET_PORT      port (default 8766)
#   MHC_MARKET_SECRET    HMAC secret shared with desktop backend (REQUIRED in prod)
#   MHC_MARKET_ADMIN_TOKEN  admin token for /api/v1/admin/* (optional, else 403)
#   MHC_MARKET_ADMIN_USERS  comma-separated admin usernames (default alice,bob,demo)
#   MHC_MARKET_DATA      data root (default ~/.mhc-market)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export NO_PROXY="localhost,127.0.0.1,0.0.0.0"
HOST="${MHC_MARKET_HOST:-127.0.0.1}"
PORT="${MHC_MARKET_PORT:-8766}"
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"

# Sensible dev defaults; override via env for prod.
export MHC_MARKET_SECRET="${MHC_MARKET_SECRET:-dev-secret}"
export MHC_MARKET_DATA="${MHC_MARKET_DATA:-/tmp/mhc-market-dev}"
export MHC_MARKET_ADMIN_TOKEN="${MHC_MARKET_ADMIN_TOKEN:-admin-secret-123}"
export MHC_MARKET_ADMIN_USERS="${MHC_MARKET_ADMIN_USERS:-alice,bob,demo}"

wait_for() {
  local url="$1" label="$2" max="${3:-30}" i
  for i in $(seq 1 "$max"); do
    if curl -sf "$url" >/dev/null 2>&1; then echo "  $label ready"; return 0; fi
    sleep 1
  done
  echo "  ERROR: $label not ready in ${max}s — tail: $LOG_DIR/market-backend.log"
  return 1
}

echo "[market-backend] Starting on :$PORT ..."
(uv run python -m mhc_market_backend) > "$LOG_DIR/market-backend.log" 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT INT TERM

wait_for "http://127.0.0.1:$PORT/api/v1/health" "Market backend (:$PORT)" || {
  echo "[market-backend] tail:"; tail -30 "$LOG_DIR/market-backend.log"; exit 1
}

cat <<EOF

=============================================
  Skill-market backend is up
=============================================
  API       → http://127.0.0.1:$PORT/api/v1
  Health    → http://127.0.0.1:$PORT/api/v1/health
  Docs      → http://127.0.0.1:$PORT/docs
  Logs      → tail -f $LOG_DIR/market-backend.log
  Ctrl+C    → stop
=============================================
EOF
wait
