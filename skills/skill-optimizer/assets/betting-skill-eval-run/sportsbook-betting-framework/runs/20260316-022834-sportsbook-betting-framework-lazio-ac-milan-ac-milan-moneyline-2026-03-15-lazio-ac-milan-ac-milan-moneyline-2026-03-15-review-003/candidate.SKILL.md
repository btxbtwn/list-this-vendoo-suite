---
name: sportsbook-betting-framework
description: Shared DraftKings sportsbook betting core for supported sports. Use directly for soccer v1, route UFC and NBA to specialist wrappers, and route cross-sport card requests to the bankroll router.
author: Theo
version: 2.0.0
---

# Sportsbook Betting Framework

This skill is the shared betting core.

Use it directly for soccer v1. Use it as the common rule set that UFC and NBA wrappers inherit for shared pricing discipline, output shape, journal handoff, and autoresearch behavior.

## Read first

Shared refs:
- `<workspace>/skills/sportsbook-betting-framework/references/shared/autoresearch-loop.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/pricing-and-grading.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/output-contract.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/post-event-review.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/journal-handoff.md`

Support refs:
- `<workspace>/skills/sportsbook-betting-framework/references/routing-map.md`
- `<workspace>/skills/sportsbook-betting-framework/references/supported-sports.md`
- `<workspace>/skills/sportsbook-betting-framework/references/sports/soccer-v1.md`

Specialist sport packs:
- `<workspace>/skills/sportsbook-betting-framework/references/sports/ufc.md`
- `<workspace>/skills/sportsbook-betting-framework/references/sports/nba.md`

Repo context:
- `<workspace>/auto-research/README.md`
- `<workspace>/auto-research/program.md`
- `<workspace>/skills/skill-optimizer/references/autoresearch-pattern.md`

## Core rules

- DraftKings sportsbook is the default unless the user explicitly names another book.
- Straight bets only by default.
- Current live odds are mandatory. If the number cannot be verified, mark it `[UNVERIFIED]` and avoid a strong recommendation.
- `Pass` is a valid final answer.
- Separate verified facts from inference:
  - `[INFERENCE]` for model-based matchup logic
  - `[UNVERIFIED]` for stale or unresolved news
- Use current web research before recommending a bet.
- Follow the shared output contract instead of improvising a custom answer shape.

## Direct support and routing

Use the routing map as the source of truth:
- `<workspace>/skills/sportsbook-betting-framework/references/routing-map.md`

In practice:
- soccer v1 -> use this skill directly
- UFC / MMA -> route to `<workspace>/skills/ufc-draftkings-betting/SKILL.md`
- NBA -> route to `<workspace>/skills/nba-draftkings-betting/SKILL.md`
- cross-sport bankroll card -> route to `<workspace>/skills/sportsbook-bankroll-router/SKILL.md`
- cross-book price mismatch / arb -> route to `<workspace>/skills/sportsbook-discrepancy-scan/SKILL.md`
- unsupported sport -> say it is not onboarded yet instead of bluffing

## Shared autoresearch workflow

Use the shared loop in:
- `<workspace>/skills/sportsbook-betting-framework/references/shared/autoresearch-loop.md`

Required behavior:
- lock the request to one matchup, slate, or small market set
- research current odds first
- compare at least 2 plausible markets when available
- estimate a fair number or fair probability
- choose the cleanest market, not the flashiest market
- run a skeptic pass before finalizing
- downgrade to `pass` if the price, evidence, or timing does not support a bet

## Soccer v1 scope

Soccer is the only sport this shared core handles directly today.

Read:
- `<workspace>/skills/sportsbook-betting-framework/references/sports/soccer-v1.md`

Use soccer v1 for:
- 3-way result
- draw no bet
- match total goals

Extra soccer rules:
- address draw risk explicitly on side bets
- do not let generic form or table edge outrank matchup shape; if the home side is likely to sit in a low block or drag the match into a low-event script, treat draw risk as a primary input
- prefer draw no bet when the draw is a central failure path; if the protected price removes the edge, pass instead of forcing the 3-way side
- do not force props or exotics in this shared skill

## Research minimums

A supported official pick should cover at least 3 of these buckets:
- current odds
- lineup, injury, suspension, or availability news
- matchup data appropriate for the sport pack
- line movement
- strongest counterargument or skeptical view

## Journal and optimizer handoff

Read:
- `<workspace>/skills/sportsbook-betting-framework/references/shared/journal-handoff.md`
- `<workspace>/skills/sportsbook-betting-framework/references/shared/post-event-review.md`

If the user places the bet:
- log it through `bet-journal`
- include the exact market, odds, stake, confidence, fair number, and `source_skill`

If the bet is later reviewed:
- settle and review it through `bet-journal`
- a supported `source_skill` review can trigger an autoresearch optimization run
- the optimizer produces a score report and proposed patch, not a silent auto-edit

## Output shape

Always follow:
- `<workspace>/skills/sportsbook-betting-framework/references/shared/output-contract.md`

## What good looks like

- exact number, exact market, and explicit edge
- clear explanation of why this market is cleaner than the obvious alternative
- honest handling of lineup, timing, or verification risk
- explicit routing when the request belongs to a specialist skill
- willingness to say `pass`

## Avoid

- generic winner picks with no price math
- memory-only answers without fresh research
- pretending unsupported sports are onboarded
- forcing action because the matchup is popular
- hiding draw risk on soccer side bets
- treating review-driven optimization as permission to rewrite files without evals
