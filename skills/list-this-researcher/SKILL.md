---
name: list-this-researcher
description: Improve `list-this-direct` with a trace-first eval loop grounded in MCP action traces from live runs. Use when the user wants to turn a `list-this-direct` trace into evals, benchmark candidate prompt edits, or decide which changes to keep.
triggers:
  - "improve list-this-direct"
  - "optimize list-this-direct"
  - "research list-this-direct"
  - "use trace to improve list-this-direct"
  - "autoresearch list-this-direct"
  - "karpathy auto research"
---

# List This Researcher

Use this skill as a thin wrapper around `skill-optimizer` for `list-this-direct`.

## Required references

Read and follow:
- `../list-this-direct/SKILL.md`
- `../list-this/SKILL.md`
- `../skill-optimizer/SKILL.md`
- `references/mcp-action-trace-loop.md`
- `references/eval-prompts.md`
- `references/eval-criteria.md`

## Purpose

Use this skill to improve `list-this-direct` without blindly expanding it.

This wrapper should:
- start from the MCP action trace produced by a recent `list-this-direct` run
- cluster repeated failures, retries, and manual corrections into testable hypotheses
- turn those clusters into binary evals and realistic reproduction prompts
- run a small eval loop against realistic prompts
- propose only the smallest prompt edits needed
- keep changes only if they improve score or keep the same score while making the skill simpler or safer
- when invoked automatically from `list-this-direct`, apply winning minimal edits locally and refresh the portable seed snapshot

## Inputs

- Required: MCP action trace from `list-this-direct`
- Optional: `field_memory_delta` JSON from the same run
- Optional: local bundle JSON from `../list-this-direct/scripts/post_run_learning.py`
- Optional trace-linked notes captured during or immediately after the run
- Optional focus area:
  - main Vendoo form
  - eBay
  - Etsy
  - all marketplaces
- Optional candidate prompt edits

The canonical trace handoff is YAML `mcp_action_trace` or `mcp_action_trace_compact`, using the field names documented in `references/mcp-action-trace-loop.md`.

## Core loop

1. Target only `list-this-direct` for the current pass.
2. Read the current runtime skill, base `list-this`, `skill-optimizer`, and required references.
3. Treat the MCP action trace as the driver:
   - identify the step, field, or marketplace where the run repeated, stalled, or required manual correction
   - separate source-of-truth mistakes from browser-execution mistakes
   - if `field_memory_delta` is present, distinguish prompt gaps from stale field-memory entries or UI drift
   - collapse duplicate retries into a few failure clusters
4. Expect the trace to come from the live run itself, updated during the run when practical or immediately after each major workflow segment while the UI state is still visible.
5. Prioritize 2-5 trace clusters by recurrence, severity, and save/publish risk.
6. Convert each high-signal cluster into:
   - one realistic user prompt that recreates the same decision point
   - 3-6 binary eval questions
   - the smallest plausible prompt edit that would prevent the failure
7. Use `references/eval-prompts.md` as fallback/regression coverage around traced failures, and use `references/eval-criteria.md` for shared global checks.
8. Score the current skill on the trace-derived eval set.
9. Propose 1-3 minimal edits mapped to exact `SKILL.md` sections.
10. Re-run the same evals.
11. Keep changes only if the score improves or stays equal while the skill becomes simpler or safer.
12. When called from the `list-this-direct` post-run loop, default to apply mode: make the accepted minimal edit directly in `../list-this-direct`.
13. `../list-this-direct/scripts/post_run_learning.py` already refreshed the portable seed snapshot. Re-run `python3 ../list-this-direct/scripts/field_memory.py export-seed` only if this pass also changes field-memory data or merges another delta.
14. Return the changed files and whether the repo now contains commit-ready updates.

## Rules

- Keep the wrapper thin and consistent with `skill-optimizer`; add only `list-this-direct`-specific trace handling and eval guidance here.
- MCP trace evidence is required; do not run this skill as a generic brainstorming pass.
- If no trace is available, stop and gather one before proposing prompt edits.
- If supporting notes exist, use them only when they are anchored to specific trace steps or outcomes.
- Do not mix optimization with a live publish flow.
- Prefer adding evals before adding more instructions.
- Preserve the `never publish without a separate instruction` rule.
- Preserve `list-this` as the source of truth for listing copy and pricing.
- Collapse repeated retries into one cluster before proposing edits.
- Do not add a permanent rule for a one-off UI stumble unless it is high-risk or recurs across traces.
- Favor simpler prompt edits over broader prompt edits.
- Keep raw run artifacts local under `../list-this-direct/data/runs/`; make repo-facing updates through skill/reference/seed files instead.
- Do not auto-commit or push; leave accepted edits as local repo changes ready for review.
- Do not rewrite `data/field_memory_seed.json` just because a prompt-only edit landed; only refresh it when the underlying field-memory data changed.

## Suggested failure clusters

Look for trace clusters in these buckets:
- bad activation choice
- skips `list-this`
- source-of-truth uncertainty ignored for brand, size, or category
- main-form save loop or validation blocker
- commit-required widget does not visibly stick
- repeated marketplace-specific retries, especially in eBay or Etsy optional fields
- field-memory drift or stale option cache
- forgets save-after-each-step behavior
- drifts toward publish behavior
- poor final reporting or review handoff

## Output shape

When reporting an optimization pass, include:
- sources used
- trace summary and failure clusters
- prompts run
- eval criteria
- baseline score
- revised score
- exact edits proposed or accepted
- changed files
- whether the portable seed snapshot was refreshed
- keep/discard decision
- remaining uncertainty

## Example use cases

- "Use this `list-this-direct` MCP trace to improve the skill."
- "Benchmark `list-this-direct` on Etsy-specific dropdown handling using this trace."
- "Turn yesterday's trace into evals and a tighter prompt."
- "Tell me which `list-this-direct` edits are actually worth keeping."
