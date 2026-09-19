#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
ZIP="$ROOT/release/List-This-Studio-macos.zip"
INFO="$ROOT/release/build_info.json"
TAG="${VENDOO_STUDIO_RELEASE_TAG:-studio-macos}"
DEFAULT_TITLE="List This Studio (macOS)"
GITHUB_REPO="${VENDOO_STUDIO_GITHUB_REPO:-btxbtwn/list-this-vendoo-suite}"

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

# Prefer an explicit override, then the PR that landed this SHA, then the commit subject.
TITLE="${VENDOO_STUDIO_RELEASE_TITLE:-}"
if [[ -z "$TITLE" ]]; then
  TITLE="$(
    gh api "repos/${GITHUB_REPO}/commits/${SHA}/pulls" \
      --jq '.[0].title // empty' 2>/dev/null || true
  )"
fi
if [[ -z "$TITLE" ]]; then
  TITLE="$(git -C "$REPO" log -1 --format=%s "$SHA" 2>/dev/null || true)"
fi
TITLE="${TITLE:-$DEFAULT_TITLE}"

NOTES=$(printf 'sha: %s\nref: %s\n\nInstall\n1. Unzip List-This-Studio-macos.zip\n2. Move List This Studio.app into Applications\n3. Control-click the app and choose Open (first launch only)\n4. In Settings, sign in with ChatGPT or add a MiMo API key\n5. Click Connect Chrome, load the listing extension once, and sign in to Vendoo\n\nNeeds macOS 13+ and Google Chrome. Listing data stays on this Mac.\n' "$SHA" "$REF")

if gh release view "$TAG" --repo "$GITHUB_REPO" >/dev/null 2>&1; then
  gh release upload "$TAG" "$ZIP" "$INFO" --clobber --repo "$GITHUB_REPO"
  gh release edit "$TAG" --title "$TITLE" --notes "$NOTES" --latest --repo "$GITHUB_REPO"
else
  gh release create "$TAG" "$ZIP" "$INFO" \
    --latest \
    --title "$TITLE" \
    --notes "$NOTES" \
    --target "$SHA" \
    --repo "$GITHUB_REPO"
fi

echo "Published $SHORT ($TITLE) to https://github.com/${GITHUB_REPO}/releases/tag/$TAG"
