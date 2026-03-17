# UFC Betting Eval Criteria

Score each prompt with binary checks.

Prefer failing a doubtful check over giving partial credit.

## Common checks

1. States or demands an exact current DraftKings market and price.
2. Uses fair line or fair probability logic instead of vibes-only analysis.
3. Includes a skeptic check or strongest counterargument.
4. Prefers the cleaner market over the more exciting market when that is the right betting decision.
5. Uses `pass` when the line is stale, weak, or not verifiable.

## UFC-specific checks

6. Handles weigh-in, short-notice, injury, or style-matchup risk appropriately.
7. Does not force a prop when a cleaner moneyline or total better expresses the thesis.
8. Routes cross-sport bankroll questions to the bankroll router.
