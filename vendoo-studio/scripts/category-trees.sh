#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib.sh
source "${ROOT}/scripts/lib.sh"

PYTHON="$(find_python || true)"
if [[ -z "${PYTHON}" ]]; then
  echo "Python 3.12+ is required." >&2
  exit 1
fi

export PYTHONPATH="${ROOT}/server${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PYTHON}" -m vendoo_studio.category_trees_cli "$@"
