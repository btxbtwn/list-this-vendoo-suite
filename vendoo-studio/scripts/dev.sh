#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python || ! -d node_modules ]]; then
  echo "Run $ROOT/scripts/setup.sh first." >&2
  exit 1
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:4318 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 4318 is already in use. Quit the other Studio process and try again." >&2
  exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

export PYTHONPATH="$ROOT/server"
.venv/bin/python -m vendoo_studio.main &
BACKEND_PID=$!

npm run dev -- --host 127.0.0.1 --port 5173 &
FRONTEND_PID=$!

echo "Studio backend  http://127.0.0.1:4318"
echo "Studio frontend http://127.0.0.1:5173"
echo "Open the frontend URL. Press Ctrl+C to stop both processes."

if command -v open >/dev/null 2>&1; then
  sleep 1
  open "http://127.0.0.1:5173" >/dev/null 2>&1 || true
fi

wait
