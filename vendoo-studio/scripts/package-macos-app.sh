#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
RELEASE="$ROOT/release"
CHANNEL="${VENDOO_STUDIO_CHANNEL:-production}"
case "$CHANNEL" in
  production) APP_NAME="List This Studio" ;;
  staging) APP_NAME="List This Studio Staging" ;;
  *) echo "VENDOO_STUDIO_CHANNEL must be production or staging." >&2; exit 1 ;;
esac
APP="$RELEASE/$APP_NAME.app"
ZIP="$RELEASE/List-This-Studio-macos.zip"

if [[ ! -x "$PYTHON" ]]; then
  echo "Create the Python environment first:" >&2
  echo "  cd $ROOT && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e '.[package]'" >&2
  exit 1
fi

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' || {
  echo "Packaging requires Python 3.12 or newer." >&2
  exit 1
}

cd "$ROOT"
"$PYTHON" -m pip install -e ".[package]"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run build
if [[ ! -f dist/index.html ]]; then
  echo "Frontend build did not produce dist/index.html." >&2
  exit 1
fi

SHA="$(git -C "$REPO" rev-parse HEAD)"
SHORT="$(git -C "$REPO" rev-parse --short HEAD)"
REF="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
"$PYTHON" - "$ROOT/desktop/build_info.json" "$SHA" "$SHORT" "$REF" "$CHANNEL" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(json.dumps({
    "version": "0.1.0",
    "sha": sys.argv[2],
    "short_sha": sys.argv[3],
    "ref": sys.argv[4],
    "channel": sys.argv[5],
}, indent=2) + "\n", encoding="utf-8")
print(path)
PY

"$PYTHON" "$ROOT/desktop/make_icon.py" "$ROOT/desktop/AppIcon.icns"
rm -rf "$RELEASE" "$ROOT/build/pyinstaller"
mkdir -p "$RELEASE"
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --distpath "$RELEASE" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/desktop/ListThisStudio.spec"

if [[ ! -d "$APP" ]]; then
  echo "PyInstaller did not create $APP" >&2
  exit 1
fi

# Older Studio builds rejected every symlink zip member. Materialize links
# before signing/zipping so those clients can still install this update.
"$PYTHON" - "$APP" <<'PY'
import sys
from pathlib import Path

from vendoo_studio.services.bundle_symlinks import flatten_symlinks

app = Path(sys.argv[1])
count = flatten_symlinks(app)
print(f"Flattened {count} symlinks in {app.name}")
PY

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
fi

PAYLOAD="$RELEASE/payload"
rm -rf "$PAYLOAD" "$ZIP"
mkdir -p "$PAYLOAD"
ditto "$APP" "$PAYLOAD/$APP_NAME.app"
sed "s/List This Studio/$APP_NAME/g" "$ROOT/desktop/HowToOpen.txt" >"$PAYLOAD/How to Open.txt"
(
  cd "$PAYLOAD"
  ditto -c -k . "$ZIP"
)
"$PYTHON" - "$ZIP" <<'PY'
import sys
from pathlib import Path

from vendoo_studio.services.bundle_symlinks import assert_zip_has_no_symlinks

assert_zip_has_no_symlinks(Path(sys.argv[1]))
print("Update zip has no symbolic link members")
PY
cp "$ROOT/desktop/build_info.json" "$RELEASE/build_info.json"
echo "Built $APP"
echo "Share $ZIP"
echo "Publish with: $ROOT/scripts/publish-macos-release.sh"
echo "Recipients: unzip, read How to Open.txt, move $APP_NAME.app to Applications."
echo "They need macOS 13+, Google Chrome, and a ChatGPT account or Xiaomi MiMo API key. Python is included; the frontend is prebuilt."
