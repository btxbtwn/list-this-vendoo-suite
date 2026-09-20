#!/bin/bash
# Put a snapshot back in place of the working database.
#
#   ./scripts/check-db-schema.sh                    # list what you have first
#   ./scripts/restore-db.sh <snapshot.db>           # asks before replacing
#   ./scripts/restore-db.sh <snapshot.db> --yes     # no prompt
#
# Quit Studio first. The current database is snapshotted before it is
# replaced, so a restore onto the wrong copy is itself reversible.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

SNAPSHOT="${1:-}"
CONFIRM="${2:-}"

if [[ -z "$SNAPSHOT" ]]; then
  echo "Usage: $0 <snapshot.db> [--yes]" >&2
  exit 64
fi
if [[ ! -f "$SNAPSHOT" ]]; then
  echo "No such snapshot: $SNAPSHOT" >&2
  exit 66
fi

PYTHON="$(find_python)" || { echo "Python 3.12+ not found. Run ./scripts/setup.sh first." >&2; exit 1; }
DATABASE="$(PYTHONPATH="$ROOT/server" "$PYTHON" -c 'from vendoo_studio.config import DATABASE_PATH; print(DATABASE_PATH)')"

# A running Studio holds writes in the -wal beside the file it has open.
# Replacing that file underneath it mixes two databases together.
PORT="$(PYTHONPATH="$ROOT/server" "$PYTHON" -c 'from vendoo_studio.config import PORT; print(PORT)')"
if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "Studio is running on port ${PORT}. Quit it first, then run this again." >&2
  exit 69
fi

echo "Checking $SNAPSHOT ..."
PYTHONPATH="$ROOT/server" "$PYTHON" - "$SNAPSHOT" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
result = connection.execute("PRAGMA integrity_check").fetchone()
connection.close()
if not result or result[0] != "ok":
    print(f"  {path} is damaged: {result[0] if result else 'unreadable'}", file=sys.stderr)
    raise SystemExit(65)
print("  integrity_check ok")
PY

echo
echo "  restore : $SNAPSHOT"
echo "  over    : $DATABASE"
echo
if [[ "$CONFIRM" != "--yes" ]]; then
  read -r -p "Replace the current database? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "Left alone."; exit 0; }
fi

if [[ -f "$DATABASE" ]]; then
  echo "Snapshotting the current database first ..."
  PYTHONPATH="$ROOT/server" "$PYTHON" -c "
from vendoo_studio.services.backups import take_snapshot
print('  kept as', take_snapshot('pre-restore').path)
"
fi

# The -wal and -shm belong to the database being replaced. Left behind, SQLite
# would replay them onto the restored file and mix the two together.
rm -f "${DATABASE}-wal" "${DATABASE}-shm"
cp "$SNAPSHOT" "$DATABASE"

echo "Restored. Start Studio and check your listings."
