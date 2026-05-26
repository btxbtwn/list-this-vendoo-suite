#!/usr/bin/env python3
"""
Initialize a frozen baseline-vs-revised eval run for list-this-direct.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = ROOT / "assets" / "list-this-direct-eval-run"
PROMPTS_PATH = ASSETS_ROOT / "test-prompts.json"
RUBRIC_PATH = ASSETS_ROOT / "eval-rubric.json"


def load_json(path: Path) -> object:
    return json.loads(path.read_text())


def build_judgments_template(
    *,
    run_tag: str,
    variant: str,
    prompts: list[dict],
    rubric_by_prompt: dict[str, dict],
) -> dict:
    evaluations = []
    for prompt in prompts:
        rubric_entry = rubric_by_prompt[prompt["id"]]
        evaluations.append(
            {
                "promptId": prompt["id"],
                "promptTitle": prompt["title"],
                "maxScore": prompt["maxScore"],
                "checks": [
                    {
                        "id": check["id"],
                        "label": check["label"],
                        "passed": None,
                        "notes": "",
                    }
                    for check in rubric_entry["checks"]
                ],
            }
        )

    return {
        "runTag": run_tag,
        "targetSkill": "list-this-direct",
        "variant": variant,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "instructions": (
            "Set each check to true or false after reviewing the raw outputs, "
            "trace artifacts, and final report for this pass. If a check is "
            "ambiguous, mark it false."
        ),
        "evaluations": evaluations,
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start a frozen list-this-direct baseline-vs-revised eval run"
    )
    parser.add_argument(
        "tag",
        nargs="?",
        default=datetime.now().strftime("%Y%m%d-%H%M%S"),
        help="Run tag to use for the eval directory",
    )
    args = parser.parse_args()

    prompts = load_json(PROMPTS_PATH)
    rubric = load_json(RUBRIC_PATH)
    rubric_by_prompt = {entry["id"]: entry for entry in rubric["prompts"]}

    prompt_ids = {prompt["id"] for prompt in prompts}
    rubric_ids = set(rubric_by_prompt)
    if prompt_ids != rubric_ids:
        missing_in_rubric = sorted(prompt_ids - rubric_ids)
        missing_in_prompts = sorted(rubric_ids - prompt_ids)
        raise SystemExit(
            "Prompt/rubric mismatch: "
            f"missing_in_rubric={missing_in_rubric}, "
            f"missing_in_prompts={missing_in_prompts}"
        )

    run_dir = ASSETS_ROOT / "runs" / args.tag
    if run_dir.exists():
        raise SystemExit(f"Run directory already exists: {run_dir}")

    run_dir.mkdir(parents=True)
    shutil.copy2(PROMPTS_PATH, run_dir / "test-prompts.json")
    shutil.copy2(RUBRIC_PATH, run_dir / "eval-rubric.json")

    instructions = [
        f"Started list-this-direct eval run: {args.tag}",
        f"Run dir: {run_dir}",
        "",
        "Next loop:",
        "1. Use the frozen prompts in this run directory for the baseline pass.",
        "2. Save raw outputs, action traces, and final reports under baseline/raw/.",
        "3. Fill baseline/judgments.json with true/false values only.",
        "4. Tighten the skill or references.",
        "5. Re-run the exact same prompts for the revised pass.",
        "6. Save raw outputs, action traces, and final reports under revised/raw/.",
        "7. Fill revised/judgments.json.",
        "8. Run python3 scripts/score_eval_run.py --run-dir "
        f"assets/list-this-direct-eval-run/runs/{args.tag}",
        "",
        "Rule: if a check is ambiguous, fail it.",
    ]
    (run_dir / "instructions.txt").write_text("\n".join(instructions) + "\n")

    for variant in ("baseline", "revised"):
        variant_dir = run_dir / variant
        raw_dir = variant_dir / "raw"
        raw_dir.mkdir(parents=True)
        template = build_judgments_template(
            run_tag=args.tag,
            variant=variant,
            prompts=prompts,
            rubric_by_prompt=rubric_by_prompt,
        )
        write_json(variant_dir / "judgments.json", template)

    print("\n".join(instructions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
