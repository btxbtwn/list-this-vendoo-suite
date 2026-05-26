---
name: list-this-direct
description: Create Vendoo-ready marketplace listings from product photos, then fill the live Vendoo item flow directly without using the Vendoo extension. Use when the user wants browser automation that creates a draft, completes marketplace forms, saves each step, and stops before final publish for human review.
---

# List This Direct

Drive the live Vendoo form directly from product photos and `list-this` output.

## Purpose

Use this skill when the user wants live browser automation. If the user only wants listing copy or JSON, use `list-this` and stop there.

## Required references

Read and follow:
- `../list-this/SKILL.md`
- `../list-this-researcher/SKILL.md`
- `references/vendoo_direct_form_notes.md`
- `references/mcp_action_trace_template.md`
- `references/field_memory_delta_template.md`
- `references/vendoo_extension_location.md` — local extension ID and manifest location for debugging
- `references/chrome-extension-unpack.md` — extracting the Vendoo extension source for inspection or development

Consult `../list-this/references/vendoo_listing_template.md` only as local schema/field-reference support for Vendoo field names, JSON shape, and allowed values. It is not a second listing-policy source.
Consult `references/mcp_action_trace_template.md` only for MCP execution-trace structure and handoff formatting. It does not define listing policy or runtime fallbacks.
Consult `references/field_memory_delta_template.md` only for the post-run field-memory update artifact. It does not override live UI verification.

## GitHub distribution contract

Ship this skill together with these sibling folders:
- `../list-this`
- `../list-this-researcher`
- `../skill-optimizer`

Keep runtime, config, and artifact paths repo-relative. Do not assume a home-directory `mcporter` config file, a Copilot MCP config that already exists, or any checkout-specific absolute path.

## Browser runtime bootstrap

Before the first live run in a fresh clone or download:

1. Run `python3 scripts/devtools_runtime.py bootstrap`.
2. If no controllable Chrome session is detected, run `python3 scripts/devtools_runtime.py launch-chrome`.
3. If the current client already exposes a native `chrome-devtools` MCP server or toolset, use it directly. In GitHub Copilot CLI, prefer native MCP over wrappers.
4. Use the `server_command`, `copilot_mcp_server`, and `detected_browser_url` from `bootstrap` as the source of truth for direct MCP configuration.
5. Only if the current client does not expose native Chrome DevTools MCP tools, fall back to `python3 scripts/devtools_runtime.py mcporter ...`.

The helper downloads `chrome-devtools-mcp` via `npx`, resolves local paths automatically, prefers a reachable local browser debug URL when one exists, and otherwise falls back to `--autoConnect`. It can also maintain a repo-local `mcporter` config as a compatibility fallback for clients that do not expose native MCP tools.

## Operating contract

- `list-this` remains the only source of truth for title, description, pricing, category reasoning, and platform-specific copy rules.
- This skill adds browser execution only: open Vendoo, fill fields directly, verify committed values, save the main form, save each marketplace form, and stop before final publish.
- The required browser automation layer is Chrome DevTools MCP.
- In GitHub Copilot CLI or any client that already exposes native `chrome-devtools` MCP tools, use those tools directly instead of routing through `mcporter`.
- Use `python3 scripts/devtools_runtime.py mcporter` only as a compatibility fallback when the current client does not expose native Chrome DevTools MCP tools.
- If neither the native `chrome-devtools` MCP path nor the `mcporter` fallback can reach a controllable Chrome session, Chrome remote debugging is off or DevTools MCP control is unavailable; stop immediately and tell the user what is missing.
- No alternate browser automation path is allowed.
- Do not ask for Browser Relay, Chrome Relay, or a managed browser for this skill.
- Do not treat opening `http://127.0.0.1:<port>` or `/json/version` in a regular Chrome tab as a real DevTools attachment. Those URLs are diagnostic only; the persistent attachment is the MCP client connection via `browser-url` or WebSocket.
- Start every new listing run by opening a fresh Vendoo tab and new-item context inside the current DevTools-connected Chrome session. Do not reuse an existing Vendoo item tab from another agent unless the user explicitly says to resume that exact draft.
- If page focus drifts to the wrong Chrome tab during a run, use `list_pages` and `select_page` to reselect the saved run-specific Vendoo item tab before any further click, fill, or save action.
- After the fresh tab is open, keep that run-specific Vendoo tab alive for the full run whenever possible.
- Do not use the Vendoo extension.
- Do not publish, list, or post anything at the end.
- Keep SKU blank unless the user explicitly asks to use SKU.
- Leave labels blank unless the user explicitly requests labels.

## Completion truthfulness contract

<HARD-GATE>
Do not treat "I interacted with the field" as equivalent to "the field is complete."

A field is not complete because text was typed, a dropdown opened, a candidate row highlighted, or a save button was clicked.

A section is not complete because a toast appeared, a timestamp changed, or the form looked mostly right from memory.

The only acceptable terminal states for any field, section, marketplace, or full run are:
- `audited_complete`
- `blocked_with_evidence`

Anything else is still in progress and must stay inside the refinement loop.

If a value disappears, decommits, or reverts after blur, tab switch, save, or reopen, its state immediately falls back to incomplete.

Never report "completed", "filled", "saved", "done", or equivalent unless the current UI evidence proves it.
</HARD-GATE>

## Field memory database

Use the persistent field-memory helper for repeated marketplace fields, dropdowns, and known-good interaction patterns:

- script: `scripts/field_memory.py`
- database: `data/field_memory.sqlite3`
- seed: `data/field_memory_seed.json`

Rules:

- initialize it before the first live run in a workspace with `python3 scripts/field_memory.py init`
- use it as an advisory cache only
- consult it before tricky fields or marketplace-specific optional sections
- if the current UI contradicts the cache, trust the live UI and record the mismatch in `field_memory_delta`
- never skip visible verification before save just because the cache had a value
- after each live run, persist learning and export the portable seed snapshot with `python3 scripts/post_run_learning.py --trace /path/to/mcp-action-trace.yaml --delta /path/to/field-memory-delta.json`

## Preconditions

Before doing anything:

1. Confirm the user wants browser automation, not listing copy only.
2. Run `python3 scripts/devtools_runtime.py bootstrap` when the workspace has not been prepared yet. Confirm the current client has a usable Chrome DevTools MCP path:
   - native `chrome-devtools` MCP tools when the client exposes them, especially in Copilot CLI
   - otherwise `python3 scripts/devtools_runtime.py mcporter` as the fallback bridge
   If neither path can reach a controllable Chrome session, use `python3 scripts/devtools_runtime.py launch-chrome` or stop and tell the user what is missing.
3. Confirm the Vendoo session is available, or log in if the user asked.
4. Confirm the user wants a draft/review flow, not final publication.
5. If the user only sent photos, start with `list-this` to generate the listing JSON.
6. If brand or category are still too uncertain after photo review, stop and ask instead of guessing. If no readable size tag exists but measurements are available, use the `list-this` measurement fallback and carry that uncertainty forward.
7. Ensure the field-memory database exists by running `python3 scripts/field_memory.py init` if `data/field_memory.sqlite3` is missing.

## Inputs

- Product photos
- Optional user notes
- Optional measurements
- Optional cost, SKU, labels
- Optional marketplace overrides

## High-level workflow

1. Confirm automation mode, Chrome DevTools MCP availability, and browser/session readiness. Prefer native `chrome-devtools` tools in Copilot; use the `mcporter` wrapper only if native MCP tools are unavailable in the current client.
2. Generate the listing source of truth with `list-this`.
3. Prime the field-memory database and use it as an advisory cache for repeated fields.
4. Open a fresh Vendoo tab and a new Vendoo item.
5. Fill the core Vendoo form directly.
6. Normalize and save the main Vendoo form.
7. Complete each marketplace form and save after each one.
8. Stop before final publish and capture the MCP action trace plus `field_memory_delta`.
9. Run the post-run learning loop, auto-invoke `list-this-researcher`, and leave the resulting repo changes ready for review.

## Live execution refinement loop (required)

Treat the run as a nested verification loop, not a single forward pass:

1. field loop
2. section save loop
3. marketplace audit loop
4. final run-wide completion loop

### State machine

Every meaningful unit of work must move through this state machine:

`not_started -> attempted_unverified -> visibly_committed -> persisted_after_save -> audited_complete`

or

`not_started -> ... -> blocked_with_evidence`

Rules:
- `attempted_unverified` is not success.
- Do not move to the next dependent field while the current one is still `attempted_unverified`.
- If a post-save audit shows drift, clear loss, stray search text, or a reverted value, demote the field or section back to `attempted_unverified` and re-enter the loop.
- Do not report success until the relevant unit is `audited_complete`.

### What counts as proof

Strong evidence:
- the closed field shows the committed value, pill, tag, chip, or category path
- transient search text is gone
- any yellow `Create "..."` row or pending chooser state is gone
- a save succeeds without validation blockers tied to that field
- after save, reopen, refresh, or a fresh snapshot, the value still renders correctly

Weak evidence that does **not** count:
- text visible only inside an active search box
- a highlighted dropdown row that was never clicked/committed
- `.value` or DOM state without matching visible UI state
- a save timestamp by itself
- "the agent already filled that"

### Field-level retry ladder

For every non-trivial field, especially custom selects, token inputs, optional specifics, and marketplace widgets:

1. Attempt the fastest reliable interaction path.
2. Read the live UI from the closed/control-resting state.
3. If the value did not visibly commit, retry with a stricter interaction path:
   - click/type again with slower pacing
   - click the visible option row
   - press **Enter** when the widget requires commit
   - blur and re-read
   - use a lower-level DOM/event update only if the UI still visibly commits afterward
4. If the field still does not commit, clear any stray search text or half-state before the next attempt.
5. If the value appears committed, re-read after blur or focus change.
6. If the field loses the value later, return to this loop immediately.
7. If three materially different attempts fail or the UI contradicts itself, stop and mark the field `blocked_with_evidence` instead of pretending it worked.

Every failed attempt and successful workaround must be logged in the MCP action trace.

### Section save loop

For the main form and each marketplace form:

1. complete the field loop for all required fields
2. complete the field loop for all visible supported optional fields
3. click **Save**
4. verify the save result
5. perform a fresh post-save audit from the rendered UI, reopened section, or fresh snapshot
6. if any required or supported optional value is missing, reverted, wrong, or only present as transient search text, go back to step 1 for that section

A section is complete only when the save succeeded **and** the post-save audit still shows the committed values.

### Final run-wide completion loop

Before reporting completion:

1. re-check the main form outcome
2. re-check each marketplace outcome
3. confirm each marketplace is either `audited_complete` or `blocked_with_evidence`
4. if any marketplace or field is merely "probably done", re-enter the relevant correction loop

Never collapse `attempted_unverified` or `persisted_after_save` into "done" in the final report.

## MCP action trace (required)

For every live DevTools MCP run, record a structured MCP action trace during the session when practical, or immediately after each major step while the live UI state is still visible.

Rules:
- Record only the actual actions taken in DevTools-MCP-connected Chrome, not a generic friction summary or a hypothetical replay.
- Use `references/mcp_action_trace_template.md` for the schema and compact handoff format.
- Preserve action order for the real run.
- If a step was never attempted, mark it as not reached instead of inferring a result.
- If a script-assisted fill fails and a click/type workaround succeeds, record both the failed attempt and the workaround.
- Explicitly log the main-form save attempt and each marketplace save attempt.

Each trace entry should capture at minimum:
- step/goal
- target field, tab, modal, or UI area
- action attempted
- expected result
- actual result
- retries or workarounds
- save outcome
- blockers, validation errors, or stop reason

This trace is the required execution artifact for the companion researcher skill and any optimization loop after the live run.

## Field memory delta (required for live runs)

Alongside the YAML execution trace, maintain a JSON `field_memory_delta` artifact for the persistent field-memory database.

Rules:

- use `references/field_memory_delta_template.md`
- capture only live observations from the current run
- record newly visible options, committed values, failed attempts, and interaction patterns
- if the live UI contradicts cached options or cached interaction patterns, record that drift in `blockers`
- after the run, store the trace and delta, merge the learning into the local database, and export the portable seed snapshot with `python3 scripts/post_run_learning.py --trace /path/to/mcp-action-trace.yaml --delta /path/to/field-memory-delta.json`

The field-memory database is an advisory cache. Save-time verification still decides whether a value is good enough to keep using.

## Step 1: Generate the source of truth

Use `list-this` first.

Minimum data to carry forward:
- title
- description
- price and offer settings
- brand
- category or category path
- condition
- department
- size type and size
- primary and secondary color
- tags
- platform-specific specifics when available

Before opening Vendoo, derive an explicit size normalization map from the verified tag size, or from the measurement-derived fallback size when no readable size tag exists, for:
- Vendoo main form size field
- eBay size plus size type
- Depop size plus size grouping

Rules:
- If the verified size is a petite code such as `PS`, `PM`, or `PL`, do not flatten it to plain `S`, `M`, or `L` unless the live marketplace forces a split-size representation.
- For the main Vendoo form, prefer the actual dropdown-supported petite code such as `PS` over improvised aliases like `SP`.
- For Depop, if the marketplace uses split sizing, map petite sizes as the base size plus `Size grouping = Petite`.
- Record the chosen live mapping in the MCP action trace whenever a marketplace forces a normalization change.
- If no readable size tag exists, use the `list-this` measurement-derived size fallback as the source of truth and preserve that uncertainty in the notes rather than blocking the run.

Rules:
- Materialize a concrete `list-this` result before touching Vendoo. Do not start the browser fill from raw photo impressions or ad-hoc rewritten copy.
- `title`, `description`, `price`, offer settings, category reasoning, and platform-specific copy must come directly from the current `list-this` output.
- Do not invent a second title, description, or pricing formula here.
- Do not paraphrase, shorten, or "clean up" the `list-this` title/description inside the browser layer. If the copy looks wrong, stop and regenerate/fix `list-this` first.
- Follow `list-this` exactly for listing quality and evidence standards.
- Before opening Vendoo, verify the `list-this` output still satisfies the canonical formula rules: title order, description line breaks, and pricing formula.
- If `list-this` cannot resolve brand or category confidently, stop and ask before opening Vendoo. If size was measurement-derived because no readable size tag exists, proceed only after `list-this` has documented that fallback clearly.

## Step 2: Open a fresh Vendoo tab and new item in DevTools-connected Chrome

Required path:
- use the current DevTools-connected Chrome session reached through native `chrome-devtools` MCP tools when the client exposes them
- otherwise use the compatibility runtime exposed by `python3 scripts/devtools_runtime.py mcporter`
- open a fresh Vendoo tab for this run inside that session; do not reuse a pre-existing Vendoo item tab from another agent unless the user explicitly asked to resume it
- if Chrome shows a remote debugging approval dialog, have the user click **Allow** before proceeding
- open Vendoo inventory/app in the fresh tab
- click **New Item** or navigate to the stable new-item route in that fresh tab
- wait for the full item form to load
- if the native `chrome-devtools` MCP connection or the `mcporter` fallback connection drops, stop and tell the user instead of changing browser paths

Keep the fresh run-specific Vendoo tab alive for the full run whenever possible.

## Step 3: Fill the core Vendoo form directly

Use the generated listing JSON as the source of truth while filling the live Vendoo form.

Before commit-required or marketplace-specific tricky fields, consult the field-memory database when the field is likely to recur:

- `python3 scripts/field_memory.py lookup --platform vendoo --field-key condition`
- `python3 scripts/field_memory.py lookup --platform etsy --context-key women-pants --field-key materials`
- `python3 scripts/field_memory.py lookup --platform depop --context-key women-pants --field-key brand`

Allowed approaches:
1. Direct UI interaction: click, type, select field by field
2. Safe DOM injection or script-assisted value setting when faster and reliable
3. Hybrid approach: fill what maps cleanly, then manually complete the rest

As you fill the form, keep the MCP action trace current with the real interaction path used for any non-trivial field, retry, validation loop, or workaround.

Use the field-level retry ladder above for every commit-required or marketplace-specific widget. Do not move on from a field because the typed text looks plausible in an active input; only move on after the field reaches `visibly_committed`.

Fill and verify at minimum:
- photos if the user provided image files
- title
- description
- category
- brand
- condition
- price
- size and size type
- primary color and secondary color when used
- quantity
- cost if provided
- tags
- notes if useful

Copy rules:
- Fill `title`, `description`, `price`, `brand`, `condition`, `size`, `size type`, `colors`, `tags`, and platform specifics from the concrete `list-this` result, not from improvised browser-side rewrites.
- For the main Vendoo form, the browser-entered `title` and `description` must match the current `list-this` output verbatim except for unavoidable UI normalization.
- If the live form content diverges from the `list-this` result, fix the form or regenerate `list-this`; do not freehand a new formula in the browser step.
- If normal `fill` actions do not persist a textarea or controlled input on save, use a lower-level DOM/event update, then verify the visible field value before clicking **Save**.
- If **Update All** or a save action clears a previously corrected field, treat that as a live blocker: re-read the field, restore the intended value, and only then save again.

Use `references/vendoo_direct_form_notes.md` for:
- field IDs that are safe to fill directly
- commit-required select fields
- tokenized field behavior
- category tree behavior
- marketplace-specific widget patterns

Default packaging rule:
- Unless the user says otherwise, use **13 x 10 x 3 in** for package dimensions on Vendoo and downstream marketplace forms.

## Step 4: Normalize and save the main Vendoo form

Before leaving the main Vendoo form:
- run the main-form commit checklist in `references/vendoo_direct_form_notes.md`
- verify the visible `title`, `description`, and `price` still match the current `list-this` output and its formula-compliant structure
- verify petite sizes remain normalized correctly in both the main size field and size-type field after any **Update All** action
- fix validation blockers
- verify that commit-required widgets visibly changed in the UI
- verify that tags are entered one at a time with **Enter**
- verify that the category picker is closed
- save the main form
- confirm the item remains in a healthy draft or in-progress state
- perform a fresh post-save audit of every commit-required main-form field from the resting UI state
- if any commit-required value disappeared, decommitted, or changed after save, return to the main-form loop, fix it, and save again
- record the main-form save outcome in the MCP action trace

Only after the main Vendoo form reaches `audited_complete` may the skill move to marketplace tabs.

## Step 5: Marketplace pass

Process marketplaces in this order unless the user says otherwise:
1. eBay
2. Etsy
3. Poshmark
4. Depop

For each marketplace:
1. Open or select the marketplace form.
2. Allow mapped data to populate if Vendoo carries it over automatically.
3. If a **Show Optional Fields** button is present, click it before reviewing marketplace-specific fields.
4. Inspect all required fields.
5. Query field memory for recurring dropdowns, token inputs, and known-friction widgets before choosing the live interaction path.
6. Fill missing or incorrect fields from the `list-this` source of truth, using field memory as an advisory cache when it matches the live UI.
7. Audit every visible optional field that has evidence-backed support in `list-this`, the photos, the measurements, or the material tag, and fill it before saving.
8. If a visible optional field does not support the exact evidence-backed value, choose the closest real live option only when it is defensible; otherwise leave it blank and record why.
9. Do not count a marketplace as complete while a visible supported optional field is blank, uncommitted, or left as stray search text.
10. Resolve validation blockers.
11. Click **Save**.
12. Confirm the save succeeded before moving on.
13. After save, do a post-save snapshot audit and verify that required and optional committed values still render in the fields instead of only appearing as transient search text.
14. If any supported value disappeared, reverted, or never truly committed, return to the marketplace correction loop and save again before moving on.
15. Record the actual field interactions, retries/workarounds, save outcome, optional-field coverage, and blockers in the MCP action trace before moving on.
16. Record any reusable options, committed values, failed attempts, and drift in `field_memory_delta` before moving on.

Global optional-field completion gate:
- If **Show Optional Fields** is present for a marketplace, you must open it before the first save attempt on that marketplace.
- A marketplace is not complete until all visible supported optional fields have been audited.
- `Supported` means there is direct evidence from `list-this`, readable tags, measurements, or clearly visible item attributes.
- If an optional field is unsupported, unavailable in the live option list, or would require guessing, leave it blank and explicitly record that reason in the trace/output.
- Never leave typed-but-uncommitted search text in an optional field.
- Never claim a marketplace was fully completed if optional fields were skipped.

### eBay

Verify and fill:
- category mapping
- department
- brand
- size and size type
- color
- material
- pattern
- fit
- closure
- accents/features
- country of origin
- fabric type
- front type
- garment care
- handmade
- occasion
- season
- theme
- rise
- inseam
- waist size
- leg style
- condition
- required item specifics

Rules:
- Click **Show Optional Fields** as soon as the eBay form is ready, before any save attempt.
- If the eBay photo strip shows more photos than the shared Step 1 photo count, treat that as a marketplace-local duplication issue and remove the extras before saving.
- Use `list-this` `ebay_specifics` as the source of truth for both required and optional item specifics.
- After optional fields are visible, do a field-by-field audit of every visible eBay optional field that has support in `ebay_specifics` and fill it before saving.
- Do not treat eBay as complete if a visible supported field such as **Accents, Closure, Country of Origin, Fabric Type, Front Type, Garment Care, Handmade, Material, Season, Theme, Occasion, Inseam, Waist Size, Rise, Fit, Pattern, Features, or Leg Style** is still blank.
- For token or create-value widgets, enter values one at a time and press **Enter** after each value.
- For select-only optional fields, do not stop at typing/searching; confirm the chosen value visibly renders in the field.
- If a yellow `Create "..."` row is still visible, treat the field as incomplete.

### Etsy

Verify and fill:
- title format appropriate for Etsy
- taxonomy/category
- who made
- what is it
- when made
- materials
- tags
- color
- other required optional taxonomy fields

Rules:
- Open **Show Optional Fields** before saving when present.
- Use a strict pointer flow for dropdowns: click field, wait for the menu, click the real option row, then verify the chosen value renders in the field.
- Treat Materials and taxonomy widgets as commit-required fields, not plain text fields.
- Do not treat Etsy as complete until all visible supported optional taxonomy/material fields have been audited after expansion.
- If the base listing rules say not to use brand in the Etsy title, preserve that behavior here.

### Poshmark

Verify and fill:
- category
- size
- brand
- color
- original price if available
- style tags if used
- condition

### Depop

Verify and fill:
- category
- size
- source
- age
- style
- brand
- type
- fit
- material
- occasion
- size grouping
- condition/details
- any required fit, material, or style mappings

Rules:
- Click **Show Optional Fields** before saving when present.
- Use `list-this` `depop_specifics` as the source of truth for **Source, Age, Style, Type, Fit, Material, Occasion, Size grouping, shipping, and brand fallback behavior** when those fields are present.
- Fill **Source**, **Age**, and **Style** from `list-this` `depop_specifics` before any Depop save.
- Fill **Type** and **Material** from `list-this` `depop_specifics` before any Depop save when those fields are visible.
- Do not treat Depop as complete if visible supported optional fields such as **Type, Fit, Material, Occasion, or Size grouping** are still blank.
- If the actual brand is unavailable in Depop's brand list, use **Other** as the fallback brand.
- Treat commit-required selects the same way as the main Vendoo form: visible selection first, then save.
- If a typed Depop search yields no real option to commit, clear the pending search text before saving instead of leaving a stray search term in the field.
- Prefer visible option rows or accessibility-snapshot-backed selection over raw internal field IDs for Depop optional specifics; internal field names may not map cleanly to the visible labels.
- After the Depop save, re-open or snapshot the form and verify the committed optional pills/values still render for **Type, Fit, Material, and Occasion**.

## Save rules

After completing each of the following, click **Save** and verify success:
- main Vendoo form
- eBay form
- Etsy form
- Poshmark form
- Depop form

If a save is blocked, stop, fix the blocking fields, then save again.

Do not treat a save timestamp by itself as sufficient proof of completion when optional fields were in play. The post-save UI must still show the committed optional values.

Every save must be followed by a fresh read from the rendered UI state. If the value only existed before save, the section is not complete and must re-enter the correction loop.

## Stop rules

Stop and ask if:
- brand is unclear
- size is unclear
- category is too uncertain
- required marketplace mapping cannot be resolved confidently
- the active Chrome DevTools MCP path cannot reach a controllable Chrome session, or the active Chrome tab is not controllable
- Vendoo UI changed enough that field targeting is unreliable
- the same field still will not reach `visibly_committed` after three materially different attempts
- the next action is a final publish, list, or post button

Never click the final publish/list/post action unless the user explicitly asks for that in a separate step.

## Final completion gate

Before the final response, re-check this full-run gate:
- main Vendoo form is `audited_complete`
- every marketplace is either `audited_complete` or `blocked_with_evidence`
- no visible supported optional field was skipped without an explicit reason
- no stray search text or yellow `Create "..."` state remains in a field being reported as complete
- the draft exists and the listing was not published

If any line above fails, the run is not complete. Re-enter the relevant correction loop first.

## Output behavior

When the run reaches the final completion gate, report:
- whether the Vendoo draft was created successfully
- whether each marketplace form is `audited_complete`, `blocked_with_evidence`, or not reached
- whether optional fields were fully audited on each marketplace that exposed them
- the MCP action trace for the companion researcher skill in the canonical YAML shape from `references/mcp_action_trace_template.md`; if the full trace is too long, return `mcp_action_trace_compact` using the same field names
- the `field_memory_delta` JSON artifact in the shape from `references/field_memory_delta_template.md`
- the stored run bundle from `python3 scripts/post_run_learning.py`, including the repo-relative trace and delta paths
- whether the automatic `list-this-researcher` pass kept any prompt/reference edits
- any fields that required manual correction
- any visible optional fields left blank and the reason they were intentionally left blank
- any remaining review items for the user
- that the listing was **not** published

Do not compress "attempted", "probably saved", or "looked filled" into a completed status line.

## Post-run learning loop (required)

After every live run, before the final response:
- save the trace and `field_memory_delta` locally with `python3 scripts/post_run_learning.py --trace /path/to/mcp-action-trace.yaml --delta /path/to/field-memory-delta.json`
- use the resulting local bundle to auto-invoke `../list-this-researcher/SKILL.md`
- default to apply mode: if the researcher finds a winning minimal edit, make that edit locally before the final response
- keep only winning minimal edits; if nothing wins, keep the local learning export but do not expand the prompt anyway
- the post-run learning script already refreshes `data/field_memory_seed.json`; rerun `python3 scripts/field_memory.py export-seed` only if the researcher also changes field-memory data or merges another delta during the pass
- keep raw run artifacts local in `data/runs/` and keep the repo-facing updates portable and commit-ready

## Optimization handoff

The automatic researcher handoff must stay grounded in the actual MCP action trace:
- use the canonical YAML handoff format from `references/mcp_action_trace_template.md`, not an ad hoc table or prose-only summary
- prefer updating the trace during the run; if that would break flow, update it immediately after each major workflow segment while the live UI is still visible
- include the full trace when short enough, otherwise a compact ordered trace that still preserves every blocker, retry/workaround, and save outcome
- derive any friction summary from the recorded trace instead of replacing the trace
- highlight field-memory cache hits that saved time
- highlight field-memory misses or stale entries that forced live reinspection
- highlight fields that did not visibly commit
- highlight validation errors that repeated
- highlight marketplace-specific optional fields that were unexpectedly hard to fill
- highlight places where `list-this` output needed manual correction
- highlight any UI state that pulled the run toward final publish unexpectedly

## Quick validation mode

Use this sequence for the next real-world validation run:
1. generate listing JSON with `list-this`
2. open a fresh Vendoo tab and new Vendoo item
3. fill the core form directly
4. fully normalize and verify the main Vendoo form
5. save the main form
6. complete and save all four marketplace forms
7. stop before listing
8. run `python3 scripts/post_run_learning.py ...`, auto-invoke `list-this-researcher`, and leave the resulting repo changes ready for review

## Eval harness for repeated optimization

Use the local eval pack when you want to compare prompt revisions against the same browser-heavy stress cases:
- prompts: `assets/list-this-direct-eval-run/test-prompts.json`
- binary rubric: `assets/list-this-direct-eval-run/eval-rubric.json`
- score history: `assets/list-this-direct-eval-run/results.tsv`

Recommended loop:
1. run `python3 scripts/start_eval_run.py [tag]`
2. execute the frozen prompt pack as the baseline pass and save artifacts under `assets/list-this-direct-eval-run/runs/<tag>/baseline/raw/`
3. fill `baseline/judgments.json` with strict true/false scores
4. tighten the skill
5. re-run the same frozen prompt pack for the revised pass and save artifacts under `.../revised/raw/`
6. fill `revised/judgments.json`
7. run `python3 scripts/score_eval_run.py --run-dir assets/list-this-direct-eval-run/runs/<tag>`

Rules:
- keep the prompt pack and rubric frozen within a run
- if a check is ambiguous, fail it
- keep the revised prompt only if it scores better, or if it ties while being meaningfully simpler
