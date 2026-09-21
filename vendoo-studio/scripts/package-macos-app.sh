#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
RELEASE="$ROOT/release"
APP="$RELEASE/List This Studio.app"
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
# The bundle and the VERSION the backend reports have to be the same build, or
# the shipped app shows a version number the UI does not correspond to.
"$PYTHON" - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
stamp_path = root / "dist" / "build-stamp.json"
if not stamp_path.is_file():
    raise SystemExit(f"Frontend build did not produce {stamp_path}.")
stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
version = (root / "VERSION").read_text(encoding="utf-8").strip()
if stamp.get("version") != version:
    raise SystemExit(
        f"Bundle was built from {stamp.get('version')!r} but VERSION is {version!r}. "
        "Re-run npm run build."
    )
print(f"Bundle stamp {version} ({stamp.get('short_sha') or 'no sha'})")
PY

SHA="$(git -C "$REPO" rev-parse HEAD)"
SHORT="$(git -C "$REPO" rev-parse --short HEAD)"
REF="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
"$PYTHON" - "$ROOT/desktop/build_info.json" "$SHA" "$SHORT" "$REF" "$VERSION" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(json.dumps({
    "version": sys.argv[5],
    "sha": sys.argv[2],
    "short_sha": sys.argv[3],
    "ref": sys.argv[4],
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

# macOS only draws the current (larger) traffic lights for binaries linked
# against the macOS 26 SDK. PyInstaller's bootloader reports a much older SDK;
# stamp the executable before deep-signing so the shipped app matches T3 Code.
EXE="$APP/Contents/MacOS/List This Studio"
if command -v vtool >/dev/null 2>&1 && [[ -f "$EXE" ]]; then
  MINOS="$(vtool -show-build "$EXE" 2>/dev/null | awk '/minos/{print $2; exit}')"
  MINOS="${MINOS:-13.0}"
  echo "Stamping $EXE with macOS SDK 26.0 (minos $MINOS)"
  vtool -set-build-version macos "$MINOS" 26.0 -replace -output "$EXE" "$EXE"
fi

# Keep PyInstaller framework symlinks. Flattening them breaks the .app layout.
# Nested Python.framework is often still signed with a different Team ID than the
# app executable; dyld then refuses to load it ("different Team IDs"). Deep-sign
# the whole bundle with one identity. Drop *.dist-info / *.egg-info first —
# codesign --deep treats those metadata dirs as bundles and fails.
if ! command -v codesign >/dev/null 2>&1; then
  echo "codesign is required to package List This Studio.app" >&2
  exit 1
fi
"$PYTHON" - "$APP" <<'PY'
import shutil
import sys
from pathlib import Path

app = Path(sys.argv[1])
removed = 0
for pattern in ("*.dist-info", "*.egg-info"):
    for path in app.rglob(pattern):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
            removed += 1
print(f"Removed {removed} package-metadata directories before deep sign")
PY
SIGN_IDENTITY="${MACOS_SIGNING_IDENTITY:--}"
echo "Deep-signing app with identity: $SIGN_IDENTITY"
codesign --force --deep --sign "$SIGN_IDENTITY" "$APP"
CODESIGN_DV="$(codesign -dv "$APP" 2>&1)" || {
  echo "$CODESIGN_DV" >&2
  exit 1
}
echo "$CODESIGN_DV"
if [[ "$CODESIGN_DV" == *"not signed at all"* ]]; then
  echo "Packaged app is unsigned." >&2
  exit 1
fi
if ! codesign --verify "$APP" 2>verify.err; then
  cat verify.err >&2
  if grep -Eq 'modified|invalid|not signed|Team ID' verify.err; then
    exit 1
  fi
  echo "codesign --verify reported a non-fatal warning; continuing."
fi
if [[ -n "${MACOS_SIGNING_IDENTITY:-}" ]]; then
  REQUIREMENT="$(codesign -d -r- "$APP" 2>&1)"
  echo "$REQUIREMENT"
  if [[ "$REQUIREMENT" != *"certificate leaf"* ]]; then
    echo "Signed app has no certificate-based designated requirement." >&2
    exit 1
  fi
else
  echo "MACOS_SIGNING_IDENTITY is not set; ad-hoc signed (Keychain re-prompts after updates)." >&2
fi

PAYLOAD="$RELEASE/payload"
rm -rf "$PAYLOAD" "$ZIP"
mkdir -p "$PAYLOAD"
ditto "$APP" "$PAYLOAD/List This Studio.app"
cp "$ROOT/desktop/HowToOpen.txt" "$PAYLOAD/How to Open.txt"
(
  cd "$PAYLOAD"
  ditto -c -k . "$ZIP"
)
"$PYTHON" - "$ZIP" <<'PY'
import sys
import tempfile
from pathlib import Path

from vendoo_studio.services.bundle_symlinks import zip_symlink_members
from vendoo_studio.services.packaged_updates import PackagedUpdateError, _validate_zip_members

archive = Path(sys.argv[1])
links = zip_symlink_members(archive)
print(f"Update zip has {len(links)} symbolic link member(s)")
try:
    with tempfile.TemporaryDirectory() as tmp:
        _validate_zip_members(archive, Path(tmp))
except PackagedUpdateError as exc:
    raise SystemExit(f"Update zip has unsafe symbolic links: {exc}") from exc
print("Update zip symlinks are safe in-bundle relative links")
PY
cp "$ROOT/desktop/build_info.json" "$RELEASE/build_info.json"
"$PYTHON" - "$ZIP" "$RELEASE/build_info.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

archive = Path(sys.argv[1])
info_path = Path(sys.argv[2])
digest = hashlib.sha256()
with archive.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
payload = json.loads(info_path.read_text(encoding="utf-8"))
payload["zip_sha256"] = digest.hexdigest()
info_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"Release build_info zip_sha256={payload['zip_sha256']}")
PY
echo "Built $APP"
echo "Share $ZIP"
echo "Publish with: $ROOT/scripts/publish-macos-release.sh"
echo "Recipients: unzip, read How to Open.txt, move List This Studio.app to Applications."
echo "They need macOS 13+, Google Chrome, and a ChatGPT account or Xiaomi MiMo API key. Python is included; the frontend is prebuilt."
