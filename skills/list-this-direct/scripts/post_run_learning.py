#!/usr/bin/env python3
"""
Persist list-this-direct run artifacts locally, merge learned field-memory data,
and export a portable seed snapshot that can be committed to the repo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from field_memory import (
    DATA_DIR,
    DEFAULT_DB_PATH,
    SEED_PATH,
    ensure_database,
    load_json_payload,
    merge_delta_payload,
    summarize_database,
    utc_now,
    write_export_seed_file,
)


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
RUNS_DIR = DATA_DIR / "runs"
LATEST_RESEARCHER_BUNDLE_PATH = DATA_DIR / "latest_researcher_bundle.json"


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def portable_path(path: Path) -> str:
    return os.path.relpath(path, SKILL_DIR).replace(os.sep, "/")


def slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in clean_text(value))
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "run"


def default_run_id(trace_path: Path) -> str:
    stem = slugify(trace_path.stem)
    return f"{stem}-{utc_now().replace(':', '').replace('.', '').replace('Z', 'z')}"


def copy_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persist run artifacts and export post-run learning")
    parser.add_argument("--trace", required=True, help="Path to the YAML MCP action trace for the completed run")
    parser.add_argument("--delta", required=True, help="Path to the JSON field_memory_delta artifact")
    parser.add_argument("--run-id", help="Optional stable run identifier")
    parser.add_argument("--notes-file", help="Optional trace-linked notes file to copy alongside the run bundle")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    trace_path = Path(args.trace).expanduser().resolve()
    delta_path = Path(args.delta).expanduser().resolve()
    notes_path = Path(args.notes_file).expanduser().resolve() if args.notes_file else None

    if not trace_path.exists():
        print(f"Error: trace file not found: {trace_path}", file=sys.stderr)
        return 1
    if not delta_path.exists():
        print(f"Error: delta file not found: {delta_path}", file=sys.stderr)
        return 1
    if notes_path and not notes_path.exists():
        print(f"Error: notes file not found: {notes_path}", file=sys.stderr)
        return 1

    run_id = clean_text(args.run_id) or default_run_id(trace_path)
    run_dir = RUNS_DIR / run_id
    stored_trace_path = run_dir / "mcp_action_trace.yaml"
    stored_delta_path = run_dir / "field_memory_delta.json"
    stored_notes_path = run_dir / notes_path.name if notes_path else None

    copy_artifact(trace_path, stored_trace_path)
    copy_artifact(delta_path, stored_delta_path)
    if notes_path and stored_notes_path is not None:
        copy_artifact(notes_path, stored_notes_path)

    delta_payload = load_json_payload(str(stored_delta_path))
    with ensure_database(DEFAULT_DB_PATH, SEED_PATH) as connection:
        merge_summary = merge_delta_payload(connection, delta_payload, run_id_override=run_id)
        exported_seed = write_export_seed_file(connection, SEED_PATH)
        field_memory_summary = summarize_database(connection)

    bundle = {
        "run_id": run_id,
        "stored_at": utc_now(),
        "researcher_skill": "../list-this-researcher/SKILL.md",
        "trace_path": portable_path(stored_trace_path),
        "field_memory_delta_path": portable_path(stored_delta_path),
        "notes_path": portable_path(stored_notes_path) if stored_notes_path else None,
        "seed_path": portable_path(SEED_PATH),
        "db_path": portable_path(DEFAULT_DB_PATH),
        "merge_summary": merge_summary,
        "field_memory_summary": field_memory_summary,
        "next_step": (
            "Invoke list-this-researcher immediately with the stored trace and field_memory_delta, "
            "apply only winning minimal edits, then keep the resulting repo changes uncommitted and ready to push."
        ),
        "exported_seed": {
            "seed_version": exported_seed.get("seed_version"),
            "entries": len(exported_seed.get("entries", [])),
            "generated_at": exported_seed.get("generated_at"),
        },
    }

    LATEST_RESEARCHER_BUNDLE_PATH.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "researcher_bundle.json").write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print_json(bundle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
