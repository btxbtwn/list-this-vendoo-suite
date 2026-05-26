# Vendoo Direct Form Notes

Supporting interaction notes for `list-this-direct`.

## Core principles

- Bootstrap the portable browser runtime with `python3 scripts/devtools_runtime.py bootstrap` before the first live run in a fresh clone or download.
- The required live automation layer is Chrome DevTools MCP.
- In GitHub Copilot CLI or any client that already exposes native `chrome-devtools` MCP tools, use those tools directly.
- Use `python3 scripts/devtools_runtime.py mcporter` only as a compatibility fallback when the current client does not expose native Chrome DevTools MCP tools.
- If neither the native `chrome-devtools` path nor the `mcporter` fallback can reach that Chrome session, Chrome DevTools MCP is unavailable; stop and tell the user instead of changing browser paths.
- Do not pivot to Browser Relay, Chrome Relay, or a managed browser for this skill.
- Opening `http://127.0.0.1:<port>` or `/json/version` in a normal Chrome tab is only a diagnostic check. It does not create or preserve the real DevTools MCP attachment.
- Start each listing run by opening a fresh Vendoo tab and new-item context in the current DevTools-connected Chrome session. Do not reuse another agent's existing Vendoo item tab unless the user explicitly asked to resume it.
- Fully complete the main Vendoo form before opening any marketplace tab.
- Do not trust `.value` alone for custom widgets. Verify that the UI visibly committed the value.
- Save the main Vendoo form before touching marketplace forms.
- Save after each marketplace form so work is not lost.
- Once the fresh tab is open, keep the run isolated to that tab for the full listing flow whenever possible.
- Never click final `List`, `Publish`, or equivalent actions unless the user explicitly asks.

## Execution state machine

Treat the live run as a state machine, not a one-pass form fill.

Each field or section should move through:

`not_started -> attempted_unverified -> visibly_committed -> persisted_after_save -> audited_complete`

or end as:

`blocked_with_evidence`

Rules:
- `attempted_unverified` is still incomplete.
- If a value disappears after blur, save, tab switch, or reopen, the state drops back to incomplete immediately.
- Never report a field or marketplace complete unless it reached `audited_complete`.

## Evidence rules

Strong evidence:
- the closed field visibly shows the chosen value, chip, pill, or category path
- pending search text is gone
- yellow `Create "..."` rows are gone
- save succeeded without a blocker tied to that field
- a fresh snapshot or reopened section still shows the value after save

Weak evidence that does **not** count:
- text only visible inside the active search input
- a highlighted option row that was not actually committed
- raw `.value` or DOM state without matching rendered UI state
- a save timestamp alone

## Retry and escalation ladder

For any field that is even slightly finicky:

1. use the fastest likely-good interaction
2. read the closed/resting field state
3. if it did not visibly commit, retry with a stricter pattern:
   - slower click/type
   - explicit visible option-row click
   - **Enter**
   - blur and re-read
   - DOM/event update only if the rendered UI still commits afterward
4. clear any stray search text before the next attempt
5. if the value appears committed, re-read after blur/focus change
6. if three materially different attempts fail, stop and surface a blocker instead of pretending it worked

Log each failed attempt plus the final successful workaround in the MCP action trace.

## Section save-and-reopen loop

For the main form and every marketplace form:

1. fill required fields
2. fill all visible supported optional fields
3. save
4. read the post-save rendered state
5. reopen or fresh-snapshot the section when needed
6. if any required or supported value disappeared, reverted, or exists only as transient search text, go back and fix it before moving on

A section is not done until the saved UI still shows the committed values.

## MCP trace capture reminders

- Keep a structured MCP action trace during the live session when practical, or immediately after each major step while the UI state is still visible.
- Use `references/mcp_action_trace_template.md` for the trace shape only; it does not change listing policy from `../list-this/SKILL.md`.
- Log only actions actually performed in DevTools-MCP-connected Chrome.
- For every meaningful action, record the step/goal, target UI area, action attempted, expected result, actual result, retries/workarounds, save outcome, and blockers.
- Explicitly record the main-form save plus each marketplace save attempt and any validation messages tied to them.
- If a field looked filled but did not visibly commit, record both the failed attempt and the successful workaround.

## Advisory field memory

- Initialize the persistent field-memory database with `python3 scripts/field_memory.py init` when needed.
- Use `python3 scripts/field_memory.py lookup ...` before repeated dropdowns, commit-required widgets, and marketplace optional fields that recur across runs.
- Treat the database as an advisory cache only. Live render and save validation always win.
- If cached options are missing from the current UI or a cached interaction pattern fails, continue safely with live inspection and record the mismatch in `field_memory_delta`.
- After the run, store the trace and delta locally and export the learned portable seed with `python3 scripts/post_run_learning.py --trace /path/to/mcp-action-trace.yaml --delta /path/to/field-memory-delta.json`.

## Known-safe interaction patterns

### Plain inputs / textareas

These generally work well with direct value set plus input/change events, but still require visual verification afterward:
- `generalDetails.title`
- `generalDetails.description`
- `generalDetails.brand`
- `generalDetails.zipCode`
- `generalDetails.quantity`
- `generalDetails.price`
- `generalDetails.cost`
- `generalDetails.notes`
- `generalDetails.weight.pounds`
- `generalDetails.weight.ounces`
- `generalDetails.dimensions.length`
- `generalDetails.dimensions.width`
- `generalDetails.dimensions.height`

### Commit-required fields

These must be treated as commit-required fields. Do not trust raw injection alone.

- `generalDetails.condition`
- `generalDetails.primaryColor`
- `generalDetails.secondaryColor`
- `generalDetails.size.option.value`
- `generalDetails.size.scale.value`

Expected pattern:
1. set or type the candidate value
2. wait for the visible options to appear
3. click the matching visible option
4. verify the field itself visibly changed
5. blur or change focus and verify again

### Category tree field

This is hierarchical and must be committed by UI interaction, not raw value injection:
- `#categoryV2`

Expected pattern:
1. open the category picker
2. click through the visible hierarchy
3. verify the category path is shown in the field
4. ensure the picker is closed before saving
5. after save, confirm the same category path still renders

### Tokenized fields

These require token-by-token entry:
- `generalDetails.tags`
- `labels`

Expected pattern:
1. focus the field
2. type one token
3. press **Enter**
4. repeat
5. verify the committed token/pill is visible before adding the next one

Rules:
- tags must be entered one at a time with **Enter** after each
- leave labels blank unless the user explicitly requested labels
- do not use SKU unless the user explicitly asked for SKU usage
- do not count raw comma-separated text as committed tags

## Marketplace-specific friction

### eBay optional fields

Use this pattern:
1. click **Show Optional Fields**
2. wait until the button/state changes to **Hide Optional Fields**
3. scroll through the revealed optional section
4. fill every applicable optional field from the source data
5. for token/create-value fields, type one value at a time and press **Enter**
6. if a yellow `Create "..."` row is still visible, the field is not fully committed yet
7. for select widgets, verify the field itself shows the chosen value before saving
8. after save, verify the same optional values still render

### Etsy optional fields

Treat Etsy optional taxonomy fields as custom widgets.

Use this pointer flow:
1. click the dropdown field
2. wait for the option list to open
3. click the actual option row inside the opened list
4. verify the chosen value renders in the field
5. blur or re-open snapshot and verify the selection persisted

Rules:
- do not treat opening the dropdown as progress by itself
- some fields may still require **Enter** or a blur/recheck after the option click
- if the chosen value is obviously wrong, do not treat the field as complete
- verify each optional dropdown after selection; stale or hidden nodes are common

### Depop optional fields

Use this pattern:
1. click **Show Optional Fields** if present
2. wait until the optional area is actually expanded
3. fill every applicable optional field before saving
4. for commit-required selects, verify visible selection before moving on
5. after save, verify the committed pills/values still render

## Marketplace optional-field completion gate

Do not treat optional fields as nice-to-have.

For every marketplace that exposes optional fields:
1. click **Show Optional Fields** before the first save attempt
2. wait until the section is visibly expanded or the control changes to **Hide Optional Fields**
3. audit every visible optional field against the source evidence
4. fill every supported optional field
5. if the exact evidence-backed value is unavailable, choose the closest defensible live option only when it is clearly appropriate
6. otherwise leave the field blank and record why it was intentionally left blank
7. save the marketplace form
8. verify after save that the optional values still visibly render in the form

Rules:
- do not leave typed search text sitting in a field if no real option was committed
- do not count a marketplace as complete just because the save timestamp updated
- do not claim completion if optional fields were skipped
- when a marketplace has token/pill style optional fields, verify the committed pills are visible after save
- when a marketplace has select-only optional fields, verify the field label/value render, not just the search text during entry
- if a post-save audit fails, re-enter the marketplace loop immediately instead of reporting partial success

## Live learnings from prior runs

### What worked

- Chrome DevTools MCP control of the active Chrome session worked for opening and driving Vendoo. Native `chrome-devtools` tools are preferred when the current client exposes them; `python3 scripts/devtools_runtime.py mcporter` remains the compatibility fallback path.
- Opening a new item in a fresh Vendoo tab worked.
- Uploading photos through the native file input `#imageInput` worked.
- Direct field fill by element ID worked reliably for many plain inputs and textareas.
- Category selection worked by opening `#categoryV2` and clicking through the visible hierarchy.
- Saving the main Vendoo form worked and created a stable Vendoo item ID.
- Tokenized tags worked when entered one at a time and confirmed with **Enter** after each tag.
- Leaving labels blank is valid.

### What needs extra verification

- Writing values into dropdown-style fields by setting `.value` alone was not enough to fully commit them.
- Vendoo custom select/token widgets may show a value but still behave as uncommitted until a visible option is clicked.
- Condition on the Vendoo form is one of the fields that does not reliably commit from raw value injection alone.
- Marketplace category-specific fields on eBay are especially finicky and require option-click confirmation.
- Bulk-inserting comma-separated tags is not reliable for Vendoo token fields.
- Moving to marketplace tabs before the general Vendoo form is fully normalized causes avoidable failures.

## Main-form commit checklist

Before leaving the main Vendoo form, verify each of these visually in the UI:

- photos are uploaded and visible
- title is present
- description is present
- brand is present
- SKU is blank unless the user explicitly asked for one
- condition is visibly committed
- primary color is visibly committed
- secondary color is visibly committed if used
- category path is visibly committed
- category picker/modal is closed
- size is visibly committed
- size type is visibly committed
- price is present
- cost is present or intentionally blank/zero per user intent
- quantity is correct
- zip code is present
- tags are tokenized one by one with **Enter**
- labels are blank unless the user requested them
- weight and dimensions are present if required
- package dimensions are set to **13 x 10 x 3 in** unless the user explicitly overrides them
- save succeeds and the listing remains in draft or in-progress state
- a fresh post-save read still shows every commit-required field as committed

If any item above is incomplete, stay on Vendoo, fix it, and save again.

## Final run gate

Before reporting the run as complete:

- main form is `audited_complete`
- each marketplace is `audited_complete` or `blocked_with_evidence`
- no supported optional field is being silently skipped
- no field being reported as complete still contains transient search text or a pending create row

If any of those checks fail, the run is still in progress.

## Quick test mode

For the next live test, prefer a single-item run:
1. generate JSON with `list-this`
2. open a fresh Vendoo tab and new item
3. fill the core form directly
4. fully normalize and verify the main Vendoo form
5. save
6. complete and save all four marketplace forms
7. stop before listing
8. document every friction point for future skill refinement
