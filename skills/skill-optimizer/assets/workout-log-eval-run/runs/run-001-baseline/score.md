# Scoring Template

Run tag: run-001-baseline
Target skill: workout-log

## Prompt 1 — workout-tonight
Score: 6/6
- [x] correct next workout
- [x] respects no-stretch preference
- [x] conservative weights
- [x] includes warm-up/cooldown
- [x] includes video links for every exercise
- [x] avoids invented completed stats

## Prompt 2 — row-substitution
Score: 4/4
- [x] evaluates swap against equipment/practicality
- [x] avoids blind repetition when better substitute exists
- [x] explains swap briefly
- [x] stays beginner-friendly

## Prompt 3 — done-strength
Score: 4/4
- [x] acknowledges completion first
- [x] asks only for missing details if needed
- [x] avoids asking for already-known data
- [x] moves toward logging

## Prompt 4 — exercise-links
Score: 4/4
- [x] groups links by exercise
- [x] covers all exercises
- [x] uses stable form-demo links
- [x] keeps commentary short

## Prompt 5 — weekly-summary
Score: 4/4
- [x] summarizes last completed workout correctly
- [x] identifies next scheduled workout correctly
- [x] mentions preferences/substitutions
- [x] stays concise

## Total
Baseline: 22/22
Revised: 22/22
Decision: keep
Notes:
- Current workout-log skill is already tightly aligned to the fixed eval pack.
- The explicit precedence rules and bundled exercise library eliminated the main ambiguities.
- No revision needed on this pass.
