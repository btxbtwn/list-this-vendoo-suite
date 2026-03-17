---
name: nba-draftkings-betting
description: Specialist NBA DraftKings wrapper. Use when the user wants an NBA pick, basketball betting breakdown, DraftKings prop, spread, total, line value, or best bet on a game or slate. Route cross-sport bankroll requests to the sportsbook bankroll router.
author: Theo
version: 1.2.0
triggers:
  - "nba pick"
  - "basketball pick"
  - "draftkings bet"
  - "player prop"
  - "spread"
  - "total"
  - "best bet"
  - "line value"
metadata: {"openclaw": {"triggers": ["nba", "basketball", "draftkings", "player prop", "spread", "total", "best bet", "line value"]}}
---

# NBA DraftKings Betting

This is the NBA specialist wrapper.

Use the shared betting core for generic workflow rules and this wrapper for NBA-specific market judgment.

## Read first

Shared core:
- `<workspace>/skills/sportsbook-betting-framework/references/shared/autoresearch-loop.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/pricing-and-grading.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/output-contract.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/post-event-review.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/journal-handoff.md`

NBA pack:
- `<workspace>/skills/sportsbook-betting-framework/references/sports/nba.md`

Repo context:
- `<workspace>/auto-research/README.md`
- `<workspace>/auto-research/program.md`
- `<workspace>/skills/skill-optimizer/references/autoresearch-pattern.md`

## Scope

Use this skill for NBA DraftKings sportsbook requests only.

If the user wants:
- a cross-sport bankroll card -> route to `<workspace>/skills/sportsbook-bankroll-router/SKILL.md`
- a multi-book mismatch or arb check -> route to `<workspace>/skills/sportsbook-discrepancy-scan/SKILL.md`

## NBA-specific research minimums

Cover at least 3 of these buckets before recommending an official bet:
- current DraftKings odds
- injury report, starters, or rotation context
- pace, matchup, usage, or role data
- line movement
- strongest case against the first read

## NBA-specific market rules

Follow the NBA sport pack:
- `<workspace>/skills/sportsbook-betting-framework/references/sports/nba.md`

Practical wrapper rules:
- do not present fragile props as high-confidence plays when minutes or role are unresolved
- prefer team-level markets when the thesis is team-level and the prop adds extra assumptions
- treat lineup uncertainty, foul risk, and blowout risk as first-class inputs
- before backing a road favorite, require a home/away split check plus an honest read on the home team's effort or incentive level
- if the edge depends on unresolved news, downgrade the play or pass until the news resolves

## Workflow

Follow the shared autoresearch loop exactly:
- `<workspace>/skills/sportsbook-betting-framework/references/shared/autoresearch-loop.md`

NBA-specific emphasis:
- compare at least one team-level market against the tempting prop when possible
- challenge whether the bet still works if recent box-score noise is ignored
- verify that the chosen market survives availability and minutes assumptions
- for road favorites, stress-test the thesis against the home team's split strength and motivation before making it official

## Output

Use the shared output contract:
- `<workspace>/skills/sportsbook-betting-framework/references/shared/output-contract.md`

## Journal and optimizer handoff

Use the shared journal handoff:
- `<workspace>/skills/sportsbook-betting-framework/references/shared/journal-handoff.md`

If a reviewed bet lists `source_skill=nba-draftkings-betting`, the journal can trigger an optimizer run that auto-applies a stronger revision for this wrapper and writes score and diff artifacts.

## What good looks like

- exact DraftKings market and price
- fair number and edge tied to the live line
- clear explanation of why this market beats the obvious alternative
- honest willingness to pass when lineup or role uncertainty kills the edge

## Avoid

- box-score narratives without price math
- player props without minutes or role logic
- auto-parlays
- blind recency bias
- memory-only answers without current research
