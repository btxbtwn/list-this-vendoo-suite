# Field Memory Delta Template

Companion learning artifact for `list-this-direct`.

## Ownership and scope

- `mcp_action_trace` remains the canonical execution trace for what happened during the run.
- `field_memory_delta` is a separate JSON artifact used to update the persistent field-memory database after the run.
- Keep these artifacts separate:
  - trace = replay and optimization evidence
  - delta = structured field-memory updates
- The field-memory database is an advisory cache, not a replacement for live verification.

## When to capture

- Prefer capturing `field_memory_delta` during the live run for tricky fields.
- If that would slow the run too much, write it immediately after each major workflow segment while the UI is still visible.
- At minimum, record:
  - newly observed dropdown options
  - committed values that worked
  - cached values that no longer matched the live UI
  - interaction patterns that succeeded or failed

## Top-level shape

Use JSON:

```json
{
  "run_id": "vendoo-direct-2026-03-14-item-001",
  "observed_at": "2026-03-14T20:00:00Z",
  "source": "list-this-direct",
  "notes": "Optional summary for the run",
  "field_memory_delta": []
}
```

## Required per-entry fields

| Field | What to capture |
| --- | --- |
| `platform` | `vendoo`, `ebay`, `etsy`, `poshmark`, `mercari`, or `depop` |
| `context_key` | Best available category/context scope, such as `global`, `women-pants`, or `etsy-tops` |
| `field_key` | Stable key when known, such as `shippingMethod` or `what_is` |
| `field_label` | Visible label when the stable key is missing or unclear |
| `widget_type` | `select`, `token_input`, `button`, `text`, `textarea`, or `unknown` |
| `visible_options` | Array of visible choices that were actually present in the live UI |
| `attempted_value` | What the run tried to set |
| `committed_value` | What visibly committed in the UI, or `null` if nothing committed |
| `interaction_pattern` | The actual interaction that was used and verified |
| `save_outcome` | `n/a` for non-save steps, or the exact save result |
| `blockers` | Validation error, mismatch, drift note, or `None` |
| `confidence` | `low`, `medium`, or `high` based on how certain the observation is |

## Optional but useful fields

- `trace_step_goal`
- `target_ui`
- `preferred_values`
- `fallback_values`
- `avoid_values`

Use the optional value arrays only when the run learned something durable enough to reuse, such as:

- a default shipping label that repeatedly works
- a fallback value for a missing marketplace brand
- a value the run should avoid because it repeatedly fails

## Example JSON

```json
{
  "run_id": "vendoo-direct-2026-03-14-item-001",
  "observed_at": "2026-03-14T20:00:00Z",
  "source": "list-this-direct",
  "field_memory_delta": [
    {
      "platform": "mercari",
      "context_key": "global",
      "field_key": "shippingMethod",
      "field_label": "Shipping Method",
      "widget_type": "select",
      "trace_step_goal": "Mercari > shipping label",
      "target_ui": "Shipping Label dropdown",
      "visible_options": [
        "USPS Ground Advantage",
        "UPS SurePost",
        "FedEx Ground Economy"
      ],
      "attempted_value": "USPS Ground Advantage",
      "committed_value": "USPS Ground Advantage",
      "interaction_pattern": "Opened dropdown, clicked visible option row, confirmed rendered value before save",
      "save_outcome": "saved",
      "blockers": "None",
      "confidence": "high",
      "preferred_values": ["USPS Ground Advantage"]
    },
    {
      "platform": "depop",
      "context_key": "women-pants",
      "field_key": "brand",
      "field_label": "Brand",
      "widget_type": "select",
      "trace_step_goal": "Depop > brand fallback",
      "target_ui": "Brand search field",
      "visible_options": ["Other"],
      "attempted_value": "Jules & Leopold",
      "committed_value": "Other",
      "interaction_pattern": "Typed brand, found no real option, cleared search text, selected Other",
      "save_outcome": "saved after retry",
      "blockers": "Actual brand was unavailable in the live Depop list",
      "confidence": "high",
      "fallback_values": ["Other"],
      "avoid_values": ["Leaving unresolved search text in the field"]
    }
  ]
}
```

## Post-run learning command

After the run, store the trace and delta locally, merge the delta into the persistent field-memory database, and export the portable seed snapshot:

```bash
python3 scripts/post_run_learning.py --trace /path/to/mcp-action-trace.yaml --delta /path/to/field-memory-delta.json
```

If you only need a direct database merge without storing the run bundle, this lower-level command is still available:

```bash
python3 scripts/field_memory.py merge-delta --input /path/to/field-memory-delta.json
```

## Rules

- Record only values and options actually seen in the live UI.
- Do not promote a failed attempt into a preferred value.
- If a cached option was missing from the live UI, record that mismatch in `blockers`.
- If the UI contradicted the cache, trust the live UI, finish safely, and record the drift in this delta.
