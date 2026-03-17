# Raw Outputs — run-001-baseline

Target skill: workout-log

## Prompt 1 — workout-tonight
**Prompt:** Can you give me my workout for tonight?

**Expected current output shape:**
- Return next scheduled workout from `WORKOUT_LOG.md`
- Use Monday 3/17 Full Strength Day 3 because it is already written in the log
- Include warm-up and cooldown
- No stretches
- Include exercise video links

## Prompt 2 — row-substitution
**Prompt:** Can I do bent over rows instead?

**Expected current output shape:**
- Briefly evaluate the swap against equipment and plan rotation
- Allow the substitution if preferred, but note PowerBlock-friendly single-arm rows may still be cleaner depending on setup
- Stay beginner-friendly

## Prompt 3 — done-strength
**Prompt:** Done with strength workout

**Expected current output shape:**
- Acknowledge completion first
- Ask only for missing details needed to log accurately if no screenshot or details are present
- Move directly toward logging and next-workout generation

## Prompt 4 — exercise-links
**Prompt:** Send links to all 4 workouts for examples on YouTube

**Expected current output shape:**
- Interpret as links for all 4 exercises in the current planned workout
- Group links by exercise
- Use bundled exercise-library links first
- Keep commentary short

## Prompt 5 — weekly-summary
**Prompt:** What’s next for me this week?

**Expected current output shape:**
- Summarize last completed workout correctly
- Identify next scheduled workout correctly
- Mention known preferences and substitutions
- Keep concise
