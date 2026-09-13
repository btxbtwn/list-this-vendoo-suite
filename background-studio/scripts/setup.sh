#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

find_python() {
  local candidate
  for candidate in python3.11 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 || [[ -x "$candidate" ]]; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        command -v "$candidate" 2>/dev/null || printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON="$(find_python)" || {
  echo "Python 3.11 or newer is required." >&2
  echo "On macOS: brew install python@3.11" >&2
  exit 1
}

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 20 or newer is required. Install it from https://nodejs.org" >&2
  exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  "$PYTHON" -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/backend/requirements.txt"
(cd "$ROOT/frontend" && npm install)

echo
echo "Background Studio is ready."
echo "Start it with: $ROOT/scripts/dev.sh"
echo "Then open http://127.0.0.1:5173"
