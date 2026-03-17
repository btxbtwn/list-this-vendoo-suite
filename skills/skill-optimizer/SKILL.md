---
name: skill-optimizer
description: Improve another skill by running repeated test prompts, scoring outputs against binary eval criteria, and proposing tighter SKILL.md instructions. Use when the user wants to auto-improve a skill, build an eval suite for a skill, adapt Karpathy-style autoresearch to prompt/skill optimization, or run iterative optimization on a skill such as workout-log.
---

# Skill Optimizer

Use this skill to optimize another skill's instructions with an eval-driven loop.

Read `references/autoresearch-pattern.md` for the minimal pattern lifted from Karpathy's autoresearch repo.
Read `references/eval-design.md` when designing binary evals.
Read `references/workout-log-evals.md` when the separate `workout-log` skill is available and you want that optional example pack.
Use `scripts/start_workout_log_eval.sh` to initialize a repeatable workout-log eval run and store artifacts under `assets/workout-log-eval-run/`.
Use `scripts/score_template.md` as the scoring sheet for each pass.
Use `scripts/append_result.py` to append summary scores to the TSV after a pass.

Betting automation assets:
- `assets/betting-skill-eval-run/`
- `scripts/run_betting_review_pass.py`

The betting optimizer path is review-triggered: the separate `bet-journal` skill can call the runner after a supported betting review is submitted. The runner prepares a fixed eval pack, runs a Copilot-driven optimization pass, auto-applies the revised skill only when the revised score improves, and stores scores plus diffs for auditability.

## Bundle notes

- `references/workout-log-evals.md`, `scripts/start_workout_log_eval.sh`, and `assets/workout-log-eval-run/` are optional example assets for users who also keep the separate `workout-log` skill and workout data outside this bundle.
- `assets/betting-skill-eval-run/` and `scripts/run_betting_review_pass.py` are optional audit/example extras for separate betting skills plus the external `bet-journal` trigger path.
- The core optimizer loop still works without any of those sibling-skill extras.

## Core loop

1. Pick one target skill only.
2. Read the target `SKILL.md` and any required references.
3. Build a small test set of realistic user prompts.
4. Define binary eval questions for each prompt.
5. Run the target skill against the tests.
6. Score the outputs.
7. Tighten the target skill instructions.
8. Re-run the same tests.
9. Keep the improved version only if the score is better or meaningfully simpler at equal score.

The same rule applies to betting runs: no winning score, no auto-applied keep.

## Rules

- Keep evals binary whenever possible.
- Prefer 4-8 eval checks per test prompt.
- Test with realistic prompts, not idealized prompts.
- Do not optimize multiple skills in one pass.
- Preserve the target skill's purpose; improve reliability, not scope creep.
- If a result is ambiguous, mark the eval as failed instead of inventing a pass.
- Favor simpler prompt edits over bloated prompt edits.

## Output shape

When reporting an optimization pass, include:
- target skill
- test prompts used
- eval criteria
- baseline score
- revised score
- what changed
- whether to keep the revision

## Recommended first target

If you also have the separate `workout-log` skill available, start with it before trying browser-heavy skills.
It is easier to evaluate, less noisy, and failures are more obvious.
