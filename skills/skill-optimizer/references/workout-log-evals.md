# Workout-Log Eval Pack

This is an optional example pack for users who also keep the separate `workout-log` skill and workout data outside this bundle.

Target skill:
- `skills/workout-log/SKILL.md` in a broader workspace that also includes the optional `workout-log` sibling skill

Source of truth:
- `WORKOUT_LOG.md` from that broader workspace root, if you keep the companion workout data file

## Test prompt 1
User prompt:
- "Can you give me my workout for tonight?"

Checks:
1. Did it use the next scheduled workout from the log/rules?
2. Did it respect no-stretch preference?
3. Did it keep weights conservative?
4. Did it include warm-up and cooldown?
5. Did it include example video links for every exercise?
6. Did it avoid inventing completed stats?

## Test prompt 2
User prompt:
- "Can I do bent over rows instead?"

Checks:
1. Did it evaluate the swap against equipment/practicality?
2. Did it avoid blindly repeating the same movement if a better substitute exists?
3. Did it explain the substitution briefly?
4. Did it stay beginner-friendly?

## Test prompt 3
User prompt:
- "Done with strength workout"

Checks:
1. Did it acknowledge completion first?
2. Did it ask only for missing details if needed?
3. Did it avoid asking for data already available from screenshots or prior messages?
4. Did it move toward logging instead of giving generic praise only?

## Test prompt 4
User prompt:
- "Send links to all 4 workouts for examples on YouTube"

Checks:
1. Did it give links grouped by exercise?
2. Did it provide all exercises, not just some?
3. Did it prefer stable form-demo links?
4. Did it keep commentary short?

## Test prompt 5
User prompt:
- "What’s next for me this week?"

Checks:
1. Did it summarize last completed workout correctly?
2. Did it identify the next scheduled workout correctly?
3. Did it mention known preferences/substitutions?
4. Did it keep the output concise?

## Baseline expectation
A strong `workout-log` skill should pass most checks consistently because:
- the workout schedule is simple
- the preferences are explicit
- the exercise library is already bundled
- the output format is narrow and practical
