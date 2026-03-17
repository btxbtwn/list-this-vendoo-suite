# Eval Design

## Principles
- Prefer yes/no checks.
- Keep each check narrow.
- Score against what the user actually asked for.
- Penalize hallucinations and omissions.
- Use the same prompts across revisions.

## Good eval examples
- Did the answer use the correct source file?
- Did it preserve the user's known preferences?
- Did it include video links for every listed exercise?
- Did it avoid inventing stats that were not reported?
- Did it update the correct log section?

## Bad eval examples
- Was this inspiring?
- Did this feel smart?
- Was this probably useful?

## Pass/fail guidance
If you have to squint, fail it.
Tight evals are more useful than generous evals.

## Suggested scoring
- 1 point per binary pass
- total score = sum of checks
- compare total score across revisions

## Simplicity tiebreaker
If two versions score equally, keep the one with:
- shorter instructions
- fewer duplicated rules
- clearer trigger logic
