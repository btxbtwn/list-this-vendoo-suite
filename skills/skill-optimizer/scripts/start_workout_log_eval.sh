#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/../assets/workout-log-eval-run"
TAG="${1:-$(date +%Y%m%d-%H%M%S)}"
PROMPTS="$ROOT/test-prompts.json"
RESULTS="$ROOT/results.tsv"
RUN_DIR="$ROOT/runs/$TAG"

mkdir -p "$RUN_DIR"

cat <<EOF
Started workout-log eval run: $TAG
Run dir: $RUN_DIR
Prompts: $PROMPTS
Results file: $RESULTS

Next manual loop:
1. Read workout-log skill + references
2. Use the prompts in $PROMPTS
3. Score against references/workout-log-evals.md
4. Save raw outputs into $RUN_DIR/
5. Append score summary into $RESULTS
EOF
