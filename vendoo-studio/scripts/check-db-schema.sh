#!/bin/bash
# Report whether a Studio database has every table and column the current
# code expects. Run it after updating, or against a copy of a database that
# has been through several updates.
#
#   ./scripts/check-db-schema.sh                  # the database this install uses
#   ./scripts/check-db-schema.sh /path/to/db      # any other copy
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

PYTHON="$(find_python)" || { echo "Python 3.12+ not found. Run ./scripts/setup.sh first." >&2; exit 1; }

PYTHONPATH="$ROOT/server" "$PYTHON" - "$@" <<'PY'
import sys

from vendoo_studio.services.schema_drift import describe, inspect_database

target = sys.argv[1] if len(sys.argv) > 1 else None
try:
    drift = inspect_database(target)
except FileNotFoundError as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(2)

print(describe(drift))
raise SystemExit(0 if drift.clean or drift.healed_by_init_db else 1)
PY
