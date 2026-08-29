#!/usr/bin/env bash
# Start the skill-market web frontend (Vite dev, :5181, proxies /api → market backend).
#
# The market backend must already be running on :8766 (see dev-market-backend.sh).
# Use dev-market-web-standalone.sh to also boot the backend.
#
# Env:
#   MHC_MARKET_WEB_PORT  port (default 5181)
#   MHC_MARKET_URL       backend target (default http://127.0.0.1:8766)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/mhc-market-frontend"

export NO_PROXY="localhost,127.0.0.1,0.0.0.0"
PORT="${MHC_MARKET_WEB_PORT:-5181}"
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"
export MHC_MARKET_URL="${MHC_MARKET_URL:-http://127.0.0.1:8766}"

# Ensure vite proxies /api to the market backend (edit vite.config.ts if different).
echo "[market-web] Frontend on :$PORT (-> $MHC_MARKET_URL) ..."
npm run dev > "$LOG_DIR/market-web.log" 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT INT TERM

for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
    echo "  Web ready: http://127.0.0.1:$PORT"
    break
  fi
  sleep 1
done

cat <<EOF

=============================================
  Skill-market web is up (HMR)
=============================================
  Web       → http://127.0.0.1:$PORT
  Logs      → tail -f $LOG_DIR/market-web.log
  Ctrl+C    → stop
  (Requires market backend on :8766 first.)
=============================================
EOF
wait
