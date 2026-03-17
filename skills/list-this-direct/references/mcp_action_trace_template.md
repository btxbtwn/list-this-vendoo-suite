# MCP Action Trace Template

Supporting execution-log schema for `list-this-direct`.

## Ownership and scope

- `../list-this/SKILL.md` and the current `list-this` output remain the only source of truth for copy, pricing, comps, category reasoning, and marketplace policy.
- This file only defines how to capture the execution trace from a live DevTools MCP listing run.
- Record only actions actually attempted in DevTools-MCP-connected Chrome. Do not backfill guesses, alternate browser paths, or hypothetical steps after the fact.
- If you are also updating the persistent field-memory database, keep that learning artifact separate as JSON `field_memory_delta` using `references/field_memory_delta_template.md`.

## When to capture

- Prefer updating the trace during the run.
- If logging during the run would break flow, update the trace immediately after each major workflow segment while the live UI state is still visible.
- At minimum, log the main-form save attempt and each marketplace save attempt.

## Required per-entry fields

| Field | What to capture |
| --- | --- |
| `step_goal` | Workflow step and immediate goal, such as `Main form > condition` or `eBay > save after specifics`. |
| `target_ui` | Field ID, label, tab, modal, or UI area touched. |
| `action_attempted` | The real interaction used: click, type, select, DOM injection, script-assisted fill, scroll, save click, etc. |
| `expected_result` | What should have happened if the action worked. |
| `actual_result` | What actually happened in the live MCP-connected Chrome session. |
| `retries_workarounds` | Follow-up attempts, alternate interaction path, or `None` if the first attempt worked. |
| `save_outcome` | `n/a` for non-save steps, or the exact save result for the relevant form. |
| `blockers` | Validation error, mapping uncertainty, MCP disconnect, stop reason, or `None`. |

## Full trace template

```yaml
mcp_action_trace:
  - step_goal: "Main form > category"
    target_ui: "#categoryV2"
    action_attempted: "Opened picker and clicked through visible hierarchy"
    expected_result: "Category path visibly commits in the field and picker closes"
    actual_result: "Category path committed after selecting the final node"
    retries_workarounds: "None"
    save_outcome: "n/a"
    blockers: "None"

  - step_goal: "Main form > condition"
    target_ui: "generalDetails.condition"
    action_attempted: "Typed Good into the dropdown"
    expected_result: "Condition visibly commits to Good"
    actual_result: "Typed value appeared but did not visibly commit"
    retries_workarounds: "Clicked the visible Good option row to commit the field"
    save_outcome: "n/a"
    blockers: "Initial typed value did not commit"

  - step_goal: "eBay > save after specifics"
    target_ui: "eBay Save button"
    action_attempted: "Clicked Save after filling required and optional fields"
    expected_result: "eBay marketplace form saves successfully"
    actual_result: "First save was blocked by missing Material"
    retries_workarounds: "Filled Material, rechecked optional fields, clicked Save again"
    save_outcome: "Succeeded on second attempt"
    blockers: "Validation error: Material required"
```

## Compact handoff format

If the trace is too long to return in full, compress only low-risk success paths. Do not omit:
- failed attempts
- retries or workarounds
- save outcomes
- blockers or stop reasons

Compact example:

```yaml
mcp_action_trace_compact:
  - step_goal: "Main form > core text fields"
    target_ui: "title, description, brand, price"
    action_attempted: "Filled by direct input"
    expected_result: "Fields visibly populate"
    actual_result: "Succeeded on first attempt"
    retries_workarounds: "None"
    save_outcome: "n/a"
    blockers: "None"

  - step_goal: "Etsy > taxonomy and save"
    target_ui: "taxonomy dropdowns, materials, Save button"
    action_attempted: "Pointer-selected dropdown rows, entered materials, clicked Save"
    expected_result: "Selections commit and Etsy form saves"
    actual_result: "Taxonomy fields committed only after pointer selection; save then succeeded"
    retries_workarounds: "Retried dropdowns with strict pointer flow"
    save_outcome: "Succeeded after retry"
    blockers: "Initial dropdown open did not count as a committed selection"
```
