# Scoring Template

Run tag: <run-tag>
Target skill: workout-log

## Prompt 1 — workout-tonight
Score: <x>/6
- [ ] correct next workout
- [ ] respects no-stretch preference
- [ ] conservative weights
- [ ] includes warm-up/cooldown
- [ ] includes video links for every exercise
- [ ] avoids invented completed stats

## Prompt 2 — row-substitution
Score: <x>/4
- [ ] evaluates swap against equipment/practicality
- [ ] avoids blind repetition when better substitute exists
- [ ] explains swap briefly
- [ ] stays beginner-friendly

## Prompt 3 — done-strength
Score: <x>/4
- [ ] acknowledges completion first
- [ ] asks only for missing details if needed
- [ ] avoids asking for already-known data
- [ ] moves toward logging

## Prompt 4 — exercise-links
Score: <x>/4
- [ ] groups links by exercise
- [ ] covers all exercises
- [ ] uses stable form-demo links
- [ ] keeps commentary short

## Prompt 5 — weekly-summary
Score: <x>/4
- [ ] summarizes last completed workout correctly
- [ ] identifies next scheduled workout correctly
- [ ] mentions preferences/substitutions
- [ ] stays concise

## Total
Baseline: <x>/22
Revised: <x>/22
Decision: keep / discard
Notes:
- 
