# Bankroll Router Eval Criteria

Score each prompt with binary checks.

## Common checks

1. Builds a small ranked card instead of dumping raw markets.
2. Uses current verified prices only for official bets.
3. Is willing to hold cash when the board is weak.

## Router-specific checks

4. Avoids stacking obviously correlated bets by default.
5. Compares supported workflows rather than answering from one sport only.
6. Uses discrepancy scan only when multiple books are actually in scope.
7. Keeps weak or unverified workflow outputs off the official card.
