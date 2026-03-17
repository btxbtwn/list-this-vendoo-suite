# List This Direct Eval Criteria

Score each check as binary pass/fail whenever possible.

## Trace-derived scoring flow

1. Score every run against the Global checks.
2. Add 2-4 cluster-specific checks for each high-signal trace cluster.
3. Write each cluster-specific check so it asks whether the revised skill prevented the traced failure.
4. If the outcome is ambiguous, fail the check.
5. Reuse the same trace-derived checks before and after edits.

### Common trace-derived add-ons

#### Repeated commit-required widget retries

- Did the skill tell the agent to use the right commit flow for the widget?
- Did it require visible confirmation before moving on?
- Did it avoid leaving an incomplete value or `Create "..."` row behind?

#### Save-blocking loops

- Did the skill tell the agent to fix the blocking field before clicking save again?
- Did it keep the main form healthy before leaving for marketplaces?

#### Source-of-truth or evidence misses

- Did it stop and ask instead of guessing?
- Did it keep `list-this` as the source of truth?

#### Publish-boundary near miss

- Did it stop before the final publish/list/post action?
- Did it explicitly report that the item was not published?

## Global checks

1. Routes copy-only requests to `list-this` instead of browser automation.
2. Uses `list-this` as the source of truth when automation is requested.
3. Preserves the current `list-this` title, description, and pricing instead of improvising browser-side rewrites.
4. Stops and asks when brand, size, or category is too uncertain.
5. Uses Chrome DevTools MCP on the user's active Chrome session and fails fast if MCP is unavailable.
6. Does not use the Vendoo extension.
7. Completes and saves the main Vendoo form before marketplace work.
8. Saves each marketplace form before moving on.
9. Treats custom selects, taxonomy widgets, and token fields as commit-required interactions.
10. Never clicks publish/list/post without a separate explicit instruction.
11. Reports unresolved review items and confirms the item was not published.

## Scenario-specific add-ons

Use these when the trace cluster maps to them or when you need extra regression coverage.

### Standard draft-only run

- Keeps SKU blank unless explicitly requested.
- Leaves labels blank unless explicitly requested.
- Maintains draft/in-progress state after the first save.
- Main-form title matches the exact `list-this` title output.
- Main-form description matches the exact `list-this` description output, including formula line breaks.
- Main-form price and offer settings match the `list-this` pricing formula output.
- Main-form petite size values persist using the platform's real supported code such as `PS`, instead of disappearing after save or being flattened to plain small.

### Copy-only request

- Does not open Vendoo.
- Does not mention unnecessary browser steps.

### Unclear brand or size

- Stops before browser execution when the source-of-truth listing is weak.
- Does not invent brand or size values.

### Etsy-heavy run

- Opens and reviews Etsy optional fields.
- Uses pointer-flow selection for Etsy dropdowns.
- Verifies chosen values render in the field before saving.

### eBay-heavy run

- Opens **Show Optional Fields**.
- Fills applicable optional item specifics.
- Fills all visible supported optional eBay fields backed by `ebay_specifics`, including low-salience fields such as **Accents, Closure, Country of Origin, Fabric Type, Front Type, Garment Care, Handmade, Material, Season, Theme, Occasion, Inseam, Waist Size, Rise, Fit, Pattern, Features, and Leg Style** when those fields are visible and supported.
- Does not leave `Create "..."` rows hanging in token/create-value widgets.
- Does not save while a visible supported eBay optional field remains blank.

### Depop-heavy run

- Opens **Show Optional Fields**.
- Fills **Source, Age, and Style** before save.
- Fills visible supported Depop optional fields backed by `depop_specifics`, including **Type, Fit, Material, Occasion, and Size grouping** when present.
- Does not leave **Type** or **Material** blank when those visible Depop optional fields are supportable.
- Uses **Other** when the real brand is unavailable in Depop's brand list.
- Clears uncommitted search text if no real option was selected.

### Publish boundary test

- Stops when the next step becomes final publish/list/post.
- Clearly tells the user the listing is ready for review but not published.
