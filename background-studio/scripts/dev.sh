#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  echo "Run $ROOT/scripts/setup.sh first." >&2
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

source .venv/bin/activate
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1 &
BACKEND_PID=$!

(cd frontend && npm run dev -- --host 127.0.0.1) &
FRONTEND_PID=$!

echo "Background Studio API  http://127.0.0.1:8000"
echo "Background Studio UI   http://127.0.0.1:5173"
echo "Press Ctrl+C to stop both processes."

if command -v open >/dev/null 2>&1; then
  sleep 1
  open "http://127.0.0.1:5173" >/dev/null 2>&1 || true
fi

wait
