#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
FAILED=0

ok() { printf '  ok    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; FAILED=1; }
warn() { printf '  warn  %s\n' "$1"; }

echo "List This Studio doctor"
echo

if command -v python3.12 >/dev/null 2>&1 || command -v python3.13 >/dev/null 2>&1; then
  ok "Python 3.12+"
elif python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
  ok "Python 3.12+"
else
  bad "Python 3.12+ not found (brew install python@3.12)"
fi

if command -v node >/dev/null 2>&1 && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'; then
  ok "Node.js $(node -v)"
else
  bad "Node.js 20+ not found"
fi

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  if "$ROOT/.venv/bin/python" -c 'import fastapi, uvicorn, pydantic, sqlalchemy, keyring' 2>/dev/null; then
    ok "Python packages in .venv"
  else
    bad "Python environment exists but packages are missing. Run scripts/setup.sh"
  fi
else
  bad "Missing $ROOT/.venv. Run scripts/setup.sh"
fi

if [[ -d "$ROOT/node_modules" ]]; then
  ok "Frontend packages (node_modules)"
else
  bad "Missing node_modules. Run scripts/setup.sh"
fi

if [[ -f "$ROOT/dist/index.html" ]]; then
  ok "Frontend build (dist/index.html)"
else
  warn "No production frontend build yet. scripts/dev.sh still works; scripts/setup.sh builds it."
fi

if [[ -f "$REPO/skills/list-this/SKILL.md" ]]; then
  ok "Listing skill at skills/list-this"
else
  bad "Missing skills/list-this/SKILL.md"
fi

if [[ -f "$REPO/vendoo-extension/manifest.json" ]]; then
  ok "Chrome extension manifest"
else
  bad "Missing vendoo-extension/manifest.json"
fi

for icon in icon16.png icon48.png icon128.png; do
  if [[ -f "$REPO/vendoo-extension/icons/$icon" ]]; then
    ok "Extension icon $icon"
  else
    bad "Missing vendoo-extension/icons/$icon"
  fi
done

CHROME=""
for candidate in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
do
  if [[ -x "$candidate" ]]; then
    CHROME="$candidate"
    break
  fi
done
if [[ -n "$CHROME" ]]; then
  ok "Google Chrome"
else
  warn "Google Chrome not found. Install it from https://www.google.com/chrome before Connect Chrome."
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:4318 -sTCP:LISTEN >/dev/null 2>&1; then
  warn "Port 4318 is already in use. Quit the other Studio process before starting a new one."
else
  ok "Port 4318 is free"
fi

echo
if [[ "$FAILED" -ne 0 ]]; then
  echo "Doctor found problems. Run $ROOT/scripts/setup.sh and install the missing tools."
  exit 1
fi
echo "Ready. Start with $ROOT/scripts/dev.sh"
