# MCP Action Trace Loop

`list-this-researcher` should treat the MCP action trace from `list-this-direct` as the primary artifact for an optimization pass.

## Canonical handoff format

The canonical handoff from `list-this-direct` is YAML:

- `mcp_action_trace` for the full trace
- `mcp_action_trace_compact` for the shortened trace

Use the exact field names below so the researcher loop can cluster the trace consistently.

## Required per-entry fields

| Field | Meaning |
| --- | --- |
| `step_goal` | Workflow step and immediate goal, such as `Main form > condition` or `eBay > save after specifics` |
| `target_ui` | Field, widget, button, tab, modal, or UI area touched |
| `action_attempted` | The real interaction used: click, type, select, DOM injection, script-assisted fill, scroll, save click, and so on |
| `expected_result` | What should have happened if the action worked |
| `actual_result` | What actually happened in the live DevTools-MCP-connected Chrome session |
| `retries_workarounds` | Follow-up attempts or alternate interaction paths, or `None` if the first attempt worked |
| `save_outcome` | `n/a` for non-save steps, or the exact save result for the relevant form |
| `blockers` | Validation error, mapping uncertainty, MCP disconnect, stop reason, or `None` |

Optional but helpful:

- original user prompt or a short summary
- whether the issue came from weak `list-this` source data versus browser execution
- screenshots or DOM notes for unusual widgets

## Timing guidance

- Prefer updating the trace during the live run.
- If logging during the run would break flow, update it immediately after each major workflow segment while the UI state is still visible.
- Do not reconstruct the trace from memory long after the run.

## Example trace snippets

### Example 1: Commit-required widget failure

```yaml
mcp_action_trace_compact:
  - step_goal: "Etsy > choose material"
    target_ui: "Materials widget"
    action_attempted: "Selected material"
    expected_result: "Chosen value visibly renders in the field"
    actual_result: "Value did not render after selection"
    retries_workarounds: "Retried twice, then clicked the real option row and confirmed visible render"
    save_outcome: "n/a"
    blockers: "Commit-required widget did not stick on the first two attempts"

  - step_goal: "Etsy > save marketplace"
    target_ui: "Save button"
    action_attempted: "Clicked Save"
    expected_result: "Etsy form saves"
    actual_result: "Etsy form saved"
    retries_workarounds: "None"
    save_outcome: "saved"
    blockers: "None"
```

### Example 2: Save-blocking loop

```yaml
mcp_action_trace_compact:
  - step_goal: "Main form > save draft"
    target_ui: "Save button"
    action_attempted: "Clicked Save"
    expected_result: "Main form saves successfully"
    actual_result: "Save blocked because Brand is required"
    retries_workarounds: "Tried saving again before fixing Brand, then filled Brand from the source-of-truth listing and retried"
    save_outcome: "saved after retry"
    blockers: "Validation error: Brand is required"
```

## How to cluster the trace

1. Collapse adjacent identical retries into one cluster.
2. Group by underlying failure mode, not by every tiny UI step.
3. Separate `list-this` source-of-truth problems from browser-execution problems.
4. Prioritize clusters that:
   - repeat
   - block save
   - create publish risk
   - forced manual correction
5. Ignore one-off latency unless it produced a real behavior mistake.

Common cluster labels:

- activation or routing miss
- source-of-truth uncertainty ignored
- main-form validation/save loop
- commit-required widget did not stick
- marketplace optional-field coverage miss
- publish-boundary near miss
- weak final report or review handoff

## Turn a trace cluster into evals

For each high-signal cluster, create:

1. a plain-language cluster statement
2. one realistic user prompt that should reproduce the same decision point
3. 3-6 binary eval checks
4. one minimal prompt edit candidate tied to the failing checks

### Conversion template

| Item | What to write |
| --- | --- |
| Cluster | `Etsy materials widget required repeated pointer-flow retries before the value stuck.` |
| Prompt | `List this handmade-looking linen dress directly in Vendoo and make sure Etsy is filled out well, but stop before publishing.` |
| Binary evals | `Did it treat Materials as commit-required?` `Did it verify the chosen value rendered before saving?` `Did it save Etsy only after the value visibly stuck?` |
| Minimal edit | Add one line in the Etsy rules telling the agent to verify that commit-required values visibly render before save. |

## Keep edits minimal

- Edit the closest section that governs the failure.
- Prefer one new line or one clarified bullet over a new paragraph.
- Do not add a permanent rule for a single low-risk stumble.
- Keep the same prompts and evals before and after editing.
- Keep the revision only if the score improves or stays equal while getting simpler or safer.
- If you need to display the trace in a table for analysis, derive the table from the YAML handoff instead of treating the table as the source of truth.
