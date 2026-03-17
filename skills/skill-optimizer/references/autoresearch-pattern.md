# Autoresearch Pattern

Adapt the Karpathy autoresearch idea to skills/prompts, not model training.

## Minimal transferable pattern
The original repo has three important ideas:
- a fixed thing to improve
- a fixed measurement process
- a loop that keeps winners and discards losers

## Mapping to skills
- `train.py` -> target `SKILL.md`
- `prepare.py` -> fixed eval harness / test prompts / constraints
- `program.md` -> optimizer instructions for the agent

## Skill optimization loop
1. Freeze a target skill version.
2. Freeze a small realistic test set.
3. Freeze a binary eval rubric.
4. Run the current skill against the test set.
5. Score the responses.
6. Edit the skill instructions or references.
7. Re-run the same tests.
8. Keep the new version only if it scores better or is clearly simpler at equal score.

## Why this works
Skills are prompts. Prompts are noisy. Repeated tests plus binary evals make prompt changes more comparable over time.

## What not to do
- Do not keep changing the eval rubric during a pass.
- Do not optimize for vibes-only criteria.
- Do not use huge prompt suites at the start.
- Do not start with browser/UI skills when a text skill can validate the method faster.
