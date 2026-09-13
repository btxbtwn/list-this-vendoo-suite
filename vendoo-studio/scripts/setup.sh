#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

echo "List This Studio setup"
echo

PYTHON="$(find_python)" || {
  echo "Python 3.12 or newer is required." >&2
  echo "On macOS: brew install python@3.12" >&2
  exit 1
}

NODE="$(command -v node || true)"
NPM="$(command -v npm || true)"
if [[ -z "$NODE" || -z "$NPM" ]]; then
  echo "Node.js 20 or newer is required. Install it from https://nodejs.org" >&2
  exit 1
fi
"$NODE" -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' || {
  echo "Node.js 20 or newer is required (found $($NODE -v))." >&2
  exit 1
}

if ! find_chrome >/dev/null; then
  echo "Google Chrome is required. Install it from https://www.google.com/chrome then run setup again." >&2
  exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Creating Python environment with $PYTHON"
  "$PYTHON" -m venv "$ROOT/.venv"
fi
VENV="$ROOT/.venv/bin/python"
"$VENV" -m pip install --upgrade pip
"$VENV" -m pip install -e "$ROOT[dev]"

if [[ ! -d "$ROOT/node_modules" ]]; then
  echo "Installing frontend packages"
  if [[ -f "$ROOT/package-lock.json" ]]; then
    (cd "$ROOT" && npm ci)
  else
    (cd "$ROOT" && npm install)
  fi
fi

(cd "$ROOT" && npm run build)

"$VENV" "$ROOT/desktop/make_icon.py" "$REPO/vendoo-extension/icons"

echo
echo "Setup finished."
echo "Start the app with: $ROOT/scripts/dev.sh"
echo "Or check this machine with: $ROOT/scripts/doctor.sh"
echo
echo "Then open http://127.0.0.1:5173"
echo "In Settings, sign in with ChatGPT or add a MiMo API key, then click Connect Chrome."
