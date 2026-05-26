#!/usr/bin/env python3
"""
Score a frozen baseline-vs-revised eval run for list-this-direct.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = ROOT / "assets" / "list-this-direct-eval-run"
DEFAULT_RESULTS_PATH = ASSETS_ROOT / "results.tsv"


def load_json(path: Path) -> object:
    return json.loads(path.read_text())


def ensure_bool(value: object, *, prompt_id: str, check_id: str, variant: str) -> bool:
    if isinstance(value, bool):
        return value
    raise SystemExit(
        f"{variant} judgments missing boolean value for {prompt_id}.{check_id}: {value!r}"
    )


def score_variant(
    *,
    variant_path: Path,
    rubric_by_prompt: dict[str, dict],
    variant_name: str,
) -> dict:
    payload = load_json(variant_path)
    evaluations = payload.get("evaluations", [])
    total_score = 0
    max_score = 0
    per_prompt = []

    seen_prompts = set()
    for evaluation in evaluations:
        prompt_id = evaluation["promptId"]
        seen_prompts.add(prompt_id)
        rubric_entry = rubric_by_prompt.get(prompt_id)
        if rubric_entry is None:
            raise SystemExit(f"Unknown prompt id in {variant_name}: {prompt_id}")

        checks_by_id = {check["id"]: check for check in evaluation.get("checks", [])}
        prompt_score = 0
        prompt_max = 0

        for rubric_check in rubric_entry["checks"]:
            check_id = rubric_check["id"]
            if check_id not in checks_by_id:
                raise SystemExit(
                    f"Missing check {prompt_id}.{check_id} in {variant_name} judgments"
                )
            passed = ensure_bool(
                checks_by_id[check_id].get("passed"),
                prompt_id=prompt_id,
                check_id=check_id,
                variant=variant_name,
            )
            prompt_score += 1 if passed else 0
            prompt_max += 1

        total_score += prompt_score
        max_score += prompt_max
        per_prompt.append(
            {
                "promptId": prompt_id,
                "score": prompt_score,
                "maxScore": prompt_max,
            }
        )

    expected_prompts = set(rubric_by_prompt)
    if seen_prompts != expected_prompts:
        missing = sorted(expected_prompts - seen_prompts)
        extra = sorted(seen_prompts - expected_prompts)
        raise SystemExit(
            f"{variant_name} prompt mismatch: missing={missing}, extra={extra}"
        )

    return {
        "variant": variant_name,
        "totalScore": total_score,
        "maxScore": max_score,
        "perPrompt": sorted(per_prompt, key=lambda item: item["promptId"]),
    }


def append_result(
    *,
    results_path: Path,
    run_tag: str,
    baseline_score: int,
    revised_score: int,
    status: str,
    notes: str,
) -> None:
    if not results_path.exists() or results_path.stat().st_size == 0:
        results_path.write_text(
            "run_tag\ttarget_skill\tbaseline_score\trevised_score\tstatus\tnotes\n"
        )

    with results_path.open("a", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            [
                run_tag,
                "list-this-direct",
                baseline_score,
                revised_score,
                status,
                notes,
            ]
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score a frozen list-this-direct eval run"
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Path to assets/list-this-direct-eval-run/runs/<tag>",
    )
    parser.add_argument(
        "--results",
        default=str(DEFAULT_RESULTS_PATH),
        help="TSV file to append summary results to",
    )
    parser.add_argument(
        "--status",
        choices=("keep", "discard", "review"),
        help="Override the auto decision status",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Freeform note stored in results.tsv",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    rubric = load_json(run_dir / "eval-rubric.json")
    rubric_by_prompt = {entry["id"]: entry for entry in rubric["prompts"]}

    baseline = score_variant(
        variant_path=run_dir / "baseline" / "judgments.json",
        rubric_by_prompt=rubric_by_prompt,
        variant_name="baseline",
    )
    revised = score_variant(
        variant_path=run_dir / "revised" / "judgments.json",
        rubric_by_prompt=rubric_by_prompt,
        variant_name="revised",
    )

    if args.status:
        status = args.status
    elif revised["totalScore"] > baseline["totalScore"]:
        status = "keep"
    elif revised["totalScore"] < baseline["totalScore"]:
        status = "discard"
    else:
        status = "review"

    summary = {
        "targetSkill": "list-this-direct",
        "runTag": run_dir.name,
        "baseline": baseline,
        "revised": revised,
        "status": status,
        "notes": args.notes,
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    append_result(
        results_path=Path(args.results).resolve(),
        run_tag=run_dir.name,
        baseline_score=baseline["totalScore"],
        revised_score=revised["totalScore"],
        status=status,
        notes=args.notes,
    )

    print(
        f"Scored {run_dir.name}: baseline {baseline['totalScore']}/{baseline['maxScore']}, "
        f"revised {revised['totalScore']}/{revised['maxScore']}, status={status}"
    )
    print(f"Summary: {summary_path}")
    print(f"Results: {Path(args.results).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
