This folder stores repeatable eval artifacts for the `list-this-direct` skill.

Files:
- `test-prompts.json`: fixed live-run scenario prompts for the optimization track
- `eval-rubric.json`: fixed binary checks for each prompt
- `results.tsv`: score history across baseline vs revised passes
- `runs/`: per-run frozen copies of the prompt pack plus manual judgments and raw outputs

Recommended loop:
1. Run `python3 scripts/start_eval_run.py [tag]`
2. Execute the current skill as the baseline using the frozen prompts in the new run directory
3. Save raw outputs, traces, and notes under `baseline/raw/`
4. Fill `baseline/judgments.json`
5. Tighten the skill
6. Re-run the same prompts with the revised skill
7. Save raw outputs, traces, and notes under `revised/raw/`
8. Fill `revised/judgments.json`
9. Run `python3 scripts/score_eval_run.py --run-dir assets/list-this-direct-eval-run/runs/<tag>`
10. Keep the revised skill only if the score improves, or if it ties with a meaningfully simpler instruction set

For browser-heavy skills, treat the prompts as fixed scenario targets:
- pick real items or live runs that exercise the required failure mode
- keep the rubric stable during the pass
- if a check is ambiguous, fail it
