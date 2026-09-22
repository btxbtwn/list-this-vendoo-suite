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
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version") or "")' "$INFO")"
BUILT_AT="$(date -u +'%Y-%m-%d %H:%M UTC')"

# The tag has to end up on this commit, which means GitHub has to have it. Catch
# that here rather than after a 90 MB upload.
if ! gh api "repos/${GITHUB_REPO}/commits/${SHA}" --jq '.sha' >/dev/null 2>&1; then
  echo "Commit $SHORT is not on GitHub. Push $REF before publishing." >&2
  exit 1
fi

# Read the old tag before uploading or moving it. A cancelled build can leave
# several merged PRs between that tag and this SHA, and every one belongs in
# the update message.
RELEASE_EXISTS=0
PREVIOUS_SHA=""
if gh release view "$TAG" --repo "$GITHUB_REPO" >/dev/null 2>&1; then
  RELEASE_EXISTS=1
  PREVIOUS_SHA="$(gh api "repos/${GITHUB_REPO}/git/refs/tags/${TAG}" --jq '.object.sha')"
fi

if [[ -n "$PREVIOUS_SHA" && "$PREVIOUS_SHA" != "$SHA" ]] && \
   ! git -C "$REPO" cat-file -e "${PREVIOUS_SHA}^{commit}" 2>/dev/null; then
  git -C "$REPO" fetch --no-tags origin "$PREVIOUS_SHA"
fi
if [[ -n "$PREVIOUS_SHA" && "$PREVIOUS_SHA" != "$SHA" ]] && \
   ! git -C "$REPO" merge-base --is-ancestor "$PREVIOUS_SHA" "$SHA"; then
  echo "Published build $PREVIOUS_SHA is not an ancestor of $SHORT; refusing incomplete release notes." >&2
  exit 1
fi

PR_ARGS=(
  --repo-path "$REPO"
  --repository "$GITHUB_REPO"
  --head "$SHA"
  --base-ref main
)
if [[ -n "$PREVIOUS_SHA" ]]; then
  PR_ARGS+=(--base "$PREVIOUS_SHA")
fi
PULL_REQUESTS_JSON="$(python3 "$ROOT/scripts/release_pull_requests.py" "${PR_ARGS[@]}")"

# Prefer an explicit override, then the newest included PR, then the commit subject.
TITLE="${VENDOO_STUDIO_RELEASE_TITLE:-}"
if [[ -z "$TITLE" ]]; then
  TITLE="$(python3 -c 'import json,sys; p=json.loads(sys.argv[1]); print(p[0]["title"] if p else "")' "$PULL_REQUESTS_JSON")"
fi
if [[ -z "$TITLE" ]]; then
  TITLE="$(git -C "$REPO" log -1 --format=%s "$SHA" 2>/dev/null || true)"
fi
TITLE="${TITLE:-$DEFAULT_TITLE}"

python3 - "$INFO" "$TITLE" "$PULL_REQUESTS_JSON" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["title"] = sys.argv[2]
payload["pull_requests"] = json.loads(sys.argv[3])
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

# GitHub stamps a release with the date it was first published and never
# refreshes it, so the page can read months old beside a zip built minutes ago.
# State the build date in the notes, where it is accurate.
CHANGES="$(python3 -c 'import json,sys; print("\n".join("- [#{number}]({url}) {title}".format(**p) for p in json.loads(sys.argv[1])))' "$PULL_REQUESTS_JSON")"
NOTES=$(printf 'version: %s\nbuilt: %s\nsha: %s\nref: %s\n\nIncluded pull requests\n%s\n\nInstall\n1. Unzip List-This-Studio-macos.zip\n2. Move List This Studio.app into Applications\n3. Control-click the app and choose Open (first launch only)\n4. In Settings, sign in with ChatGPT or add a MiMo API key\n5. Click Connect Chrome, load the listing extension once, and sign in to Vendoo\n\nNeeds macOS 13+ and Google Chrome. Listing data stays on this Mac.\n' "${VERSION:-unknown}" "$BUILT_AT" "$SHA" "$REF" "${CHANGES:-- None detected}")

if [[ "$RELEASE_EXISTS" == 1 ]]; then
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

# --target only applies when the tag is created. Re-publishing clobbers the
# assets and leaves the tag wherever it first landed, so the release page shows
# an unrelated old commit next to a current build. Move the ref itself.
TAG_SHA="$PREVIOUS_SHA"
if [[ "$TAG_SHA" != "$SHA" ]]; then
  PREVIOUS="${TAG_SHA:-unset}"
  if gh api -X PATCH "repos/${GITHUB_REPO}/git/refs/tags/${TAG}" \
    -f "sha=${SHA}" -F force=true --jq '.object.sha' >/dev/null; then
    echo "Moved tag $TAG to $SHORT (was ${PREVIOUS:0:7})"
  else
    echo "Warning: could not move tag $TAG to $SHORT; the release page will show the old commit." >&2
  fi
fi

echo "Published $SHORT ($TITLE) to https://github.com/${GITHUB_REPO}/releases/tag/$TAG"
