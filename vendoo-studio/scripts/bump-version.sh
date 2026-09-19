#!/usr/bin/env bash
# Bump the Studio patch version (0.1.0 → 0.1.1) and sync package manifests.
# Usage: ./scripts/bump-version.sh           # patch
#        ./scripts/bump-version.sh minor    # 0.1.1 → 0.2.0
#        ./scripts/bump-version.sh major    # 0.1.1 → 1.0.0
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KIND="${1:-patch}"
VERSION_FILE="$ROOT/VERSION"

current="$(tr -d '[:space:]' < "$VERSION_FILE")"
IFS=. read -r major minor patch <<< "$current"
major="${major:-0}"
minor="${minor:-0}"
patch="${patch:-0}"

case "$KIND" in
  major) major=$((major + 1)); minor=0; patch=0 ;;
  minor) minor=$((minor + 1)); patch=0 ;;
  patch) patch=$((patch + 1)) ;;
  *)
    echo "Usage: $0 [patch|minor|major]" >&2
    exit 1
    ;;
esac

next="${major}.${minor}.${patch}"
printf '%s\n' "$next" > "$VERSION_FILE"

# Keep npm / Python package metadata in lockstep with VERSION.
python3 - "$ROOT" "$next" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
version = sys.argv[2]

pkg = root / "package.json"
data = json.loads(pkg.read_text(encoding="utf-8"))
data["version"] = version
pkg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

lock = root / "package-lock.json"
if lock.is_file():
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    lock_data["version"] = version
    packages = lock_data.get("packages")
    if isinstance(packages, dict) and "" in packages and isinstance(packages[""], dict):
        packages[""]["version"] = version
    lock.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")

pyproject = root / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
updated, n = re.subn(
    r'(?m)^version\s*=\s*"[^"]*"',
    f'version = "{version}"',
    text,
    count=1,
)
if n != 1:
    raise SystemExit("Could not update version in pyproject.toml")
pyproject.write_text(updated, encoding="utf-8")

info = root / "desktop" / "build_info.json"
if info.is_file():
    payload = json.loads(info.read_text(encoding="utf-8"))
    payload["version"] = version
    info.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

print(version)
PY
