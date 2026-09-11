#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
ZIP="$ROOT/release/List-This-Studio-macos.zip"
INFO="$ROOT/release/build_info.json"
TAG="${VENDOO_STUDIO_RELEASE_TAG:-studio-macos}"
TITLE="${VENDOO_STUDIO_RELEASE_TITLE:-List This Studio (macOS)}"

if [[ ! -f "$ZIP" ]]; then
  echo "Missing $ZIP. Run scripts/package-macos-app.sh first." >&2
  exit 1
fi
if [[ ! -f "$INFO" ]]; then
  echo "Missing $INFO. Run scripts/package-macos-app.sh first." >&2
  exit 1
fi

SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha"])' "$INFO")"
SHORT="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("short_sha") or d["sha"][:7])' "$INFO")"
REF="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("ref") or "main")' "$INFO")"
NOTES=$(printf 'sha: %s\nref: %s\n\nUnzip List-This-Studio-macos.zip and move List This Studio.app to Applications.\n' "$SHA" "$REF")

if gh release view "$TAG" --repo btxbtwn/list-this-vendoo-suite >/dev/null 2>&1; then
  gh release upload "$TAG" "$ZIP" "$INFO" --clobber --repo btxbtwn/list-this-vendoo-suite
  gh release edit "$TAG" --title "$TITLE" --notes "$NOTES" --latest --repo btxbtwn/list-this-vendoo-suite
else
  gh release create "$TAG" "$ZIP" "$INFO" \
    --latest \
    --title "$TITLE" \
    --notes "$NOTES" \
    --target "$SHA" \
    --repo btxbtwn/list-this-vendoo-suite
fi

echo "Published $SHORT to https://github.com/btxbtwn/list-this-vendoo-suite/releases/tag/$TAG"
