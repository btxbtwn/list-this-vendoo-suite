#!/usr/bin/env python3
import csv
import sys
from pathlib import Path

if len(sys.argv) != 8:
    print("usage: append_result.py <results.tsv> <run_tag> <target_skill> <baseline_score> <revised_score> <status> <notes>")
    sys.exit(1)

results_path = Path(sys.argv[1])
run_tag = sys.argv[2]
target_skill = sys.argv[3]
baseline = sys.argv[4]
revised = sys.argv[5]
status = sys.argv[6]
notes = sys.argv[7] if len(sys.argv) > 7 else ""

with results_path.open("a", newline="") as f:
    writer = csv.writer(f, delimiter='\t')
    writer.writerow([run_tag, target_skill, baseline, revised, status, notes])

print(f"Appended result to {results_path}")
