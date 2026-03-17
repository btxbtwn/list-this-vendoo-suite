# Shared Framework Eval Criteria

Score each prompt with binary checks.

## Common checks

1. States or demands an exact current sportsbook number.
2. Uses fair-price logic instead of generic pick language.
3. Includes a skeptic pass and uses `pass` when the evidence is weak.

## Framework-specific checks

4. Handles soccer directly and addresses draw risk on side bets.
5. Routes UFC requests to `ufc-draftkings-betting`.
6. Routes NBA requests to `nba-draftkings-betting`.
7. Routes cross-sport bankroll requests to `sportsbook-bankroll-router`.
8. Declines unsupported sports instead of bluffing.
