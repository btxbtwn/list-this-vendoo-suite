# First Pass Plan

## Goal
Run a manual first optimization pass on `workout-log` before attempting a fully autonomous loop.

## Steps
1. Read `workout-log` skill + references.
2. Score the current version against the eval pack.
3. Identify failures, ambiguities, or duplicated instructions.
4. Edit the skill for clarity and reliability.
5. Re-score using the same eval prompts.
6. Keep the revision only if it improved.

## What to look for in workout-log
- duplicate rules between SKILL.md and references
- unclear precedence between the log and rules files
- unclear handling of already-completed workouts versus planned workouts
- unclear policy for when to ask follow-up questions vs log immediately
- missing guidance for linking substitutions instead of original exercises

## Success condition
The skill becomes easier to follow and more reliable on the 5 test prompts without expanding scope unnecessarily.
