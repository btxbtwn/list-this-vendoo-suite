---
name: raghouse-box-sourcing
description: Use this skill whenever the user mentions Raghouse, reseller sourcing, clothing boxes or bundles, cost-per-piece, low COG, fast sell-through, trending inventory, Vendoo exports, Vendoo tags/themes, or asks what is selling now and what will sell next for eBay, Poshmark, Etsy, Depop, or Mercari. Use it even for indirect asks like "analyze my latest Vendoo export and tell me what to buy from Raghouse", "what tags are selling for me right now?", or "what should I stock for spring?" If the user wants working Raghouse links, live page confirmation, Chrome/browser automation, or explicitly says to use Chrome DevTools MCP, use this skill and follow its browser-assisted verification path.
---

# Raghouse Box Sourcing

## Overview

Start with the user's own sell-through data, then layer in current market research, then rank Raghouse boxes against that demand picture.

**Core principles:**

- Preserve the skill's original **low-COG / high-volume bias**. Demand fit is important, but it should refine the decision inside an economically strong shortlist rather than replace cost discipline.
- Prefer the user's own **recent Vendoo sell-through data** over generic trend chatter when they conflict.
- Read Vendoo through **categories, brands, tags, and keywords**. Tags/themes are first-class signals, not optional garnish.
- Separate **what is selling now** from **what is likely to strengthen over the next 60-90 days**.
- Call out the **exact Vendoo file path and freshness** so the user can see which export actually drove the recommendation.
- Never promise that a box is "guaranteed to sell." Use language like **best fast-turn candidates** or **best fit for the current store + seasonality signals**.
- Treat `https://raghouse.com/products/{handle}` as a **candidate URL only** until it is browser-verified.

## When to Use

- User wants Raghouse sourcing help
- User wants low / mid / high budget box combos
- User wants a single best combo under a budget cap
- User wants low COG per item
- User wants non-recycled boxes only
- User sells across eBay, Poshmark, Etsy, Depop, and Mercari
- User wants the **latest Vendoo export analyzed before shopping Raghouse**
- User wants to know which **Vendoo tags/themes** are moving, saturated, or worth buying into next
- User asks what is selling now, what is likely to sell next, or what to stock for the upcoming season

Do **not** use this skill for other wholesalers unless the user explicitly wants Raghouse-style logic adapted elsewhere.

If the user gives only one budget target instead of low / mid / high tiers, still use this skill. Return the best combo within that budget and optionally include a cheaper and richer alternative if helpful.

If no Vendoo export can be found locally and the user asked for export-aware sourcing, say so plainly and continue with a research-first version of the flow instead of pretending a Vendoo analysis happened. If the freshest local export is obviously stale, say that too instead of presenting it like fresh evidence.

## Source order

| Step | Rule |
|---|---|
| **Vendoo** | Analyze the freshest local Vendoo export first when available or requested, and report the exact path + modified time used |
| **Research** | Determine what is selling now and what looks strongest over the next 60-90 days |
| **Raghouse** | Discover all published collection handles from `https://raghouse.com/collections.json?limit=250` first, then page through `https://raghouse.com/products.json?limit=250&page=N` or `https://raghouse.com/collections/all/products.json?limit=250&page=N` so recommendations come from the full catalog, not just `get-this-box` |
| **Browser** | When links must be verified, bootstrap `scripts/devtools_runtime.py` and verify shortlisted products in live Chrome |
| **Extract** | `title`, `handle`, `price`, `available`, `product_type`, `tags`, `body_html`, `published_at` |
| **Pieces** | Parse from title, usually `NN pcs`; for ranges, use the lower bound |
| **Reject** | unavailable, recycled, kidswear, bras, intimates, lingerie |
| **Rank** | economics frontier first, then demand-fit scoring, then pieces / fewer boxes |
| **Access** | Treat `https://raghouse.com/products/{handle}` as a candidate URL until browser-verified |
| **Tone** | "best fast-turn candidates," not "guaranteed sellers" |

## Vendoo-first bootstrap

### 1. Resolve the most recent Vendoo export

Prefer the user's explicit file first. If they did not name a file, search these candidate locations and use the **newest modified export** among them:

1. an attached Vendoo CSV the user provided for this run
2. a named path from the user
3. `~/.openclaw/workspace/vendoo-analytics/public/data/vendoo.csv`
4. the newest `vendoo-full-*.csv` under `~/.openclaw/workspace/`
5. the newest `vendoo-full-*.csv` under `~/Downloads/`

The deployed `vendoo.csv` is a candidate, not an automatic winner. If a newer export exists elsewhere, use the newer file and say so.

Use the helper script when possible:

```bash
python3 scripts/analyze_vendoo_export.py --latest --output data/runtime/latest-vendoo-analysis.json
```

If the user gave a specific file:

```bash
python3 scripts/analyze_vendoo_export.py --input /path/to/vendoo.csv --output data/runtime/latest-vendoo-analysis.json
```

The helper returns:

- source file path and modified time
- total rows, sold rows, active rows
- recent sold platforms
- hot categories / brands / tags / keywords
- overstock or slow-moving categories / brands / tags
- platform-specific tag winners
- next 60-90 day tag and keyword signals based on recent acceleration and seasonality

If a Vendoo analysis JSON is already attached or available locally, use it instead of reparsing the CSV so the math stays reproducible.

### 2. Build the store-specific demand brief

From the Vendoo analysis, capture:

- **recent winners:** categories, brands, tags, and keywords selling in the last 30 and 90 days
- **active saturation:** categories, brands, or tags with lots of active inventory and weak recent sell-through
- **platform skew:** where the recent sales and tags/themes are clustering, especially if eBay / Depop / Etsy behavior differs
- **near-term lift:** tags and keywords that are accelerating into the next 60-90 days

Treat the user's own data as the primary signal. Generic research is there to sharpen the read, not to override strong local evidence.

### 3. Research what is selling now and what is likely to sell next

Use the environment's available web research tools to gather **3-6 current signals** from credible reseller or marketplace sources.

Your research should answer two separate questions:

1. What looks strongest **right now** for resale?
2. What looks likely to strengthen in the **next 60-90 days** based on the calendar and current trend direction?

Favor signals that:

- repeat across multiple sources
- align with the user's recent Vendoo winners
- make sense for the user's marketplaces
- match the current season in the user's region when known

Default to US / northern hemisphere seasonality if location is unknown.

Do not let broad fashion-blog hype outweigh clear local overstock problems from the user's own inventory.

If web research is unavailable, say so and continue with Vendoo + Raghouse data only.

## Browser runtime bootstrap

Only use the browser-assisted path when the user:

- asks for working or verified Raghouse links
- asks for live page confirmation
- asks for add-to-cart help
- explicitly says to use Chrome, DevTools, or Chrome DevTools MCP

Before the first browser-assisted run in a fresh checkout:

1. Run `python3 scripts/devtools_runtime.py bootstrap`.
2. If no controllable Chrome session is detected, run `python3 scripts/devtools_runtime.py launch-chrome`.
3. For every Chrome DevTools MCP tool listing, auth, or call in this skill, use `python3 scripts/devtools_runtime.py mcporter ...`.

The helper writes a repo-local `mcporter` config under `data/runtime/` and starts the `mcporter` daemon if needed, so the Chrome DevTools MCP tools can be called reliably from the skill directory.

If the user only wants ranking math, keep the flow data-first and skip browser control.

If the user explicitly asked for browser-verified links and DevTools control is unavailable, stop and say what is missing instead of pretending a constructed URL was confirmed.

## Implementation

### 1. Analyze the Vendoo export first

Use the most recent available Vendoo export before looking at Raghouse.

Record:

- file path used
- file recency or staleness if obvious
- total sold / active sample size
- strongest sold categories
- strongest sold brands
- strongest sold tags / themes
- strongest sold keywords
- obvious overstock or slow-moving categories / tags

If the recent sample is thin, say so plainly instead of overconfidently reading noise as signal.

### 2. Build a "now" and "next" demand brief

Create a short internal brief with:

- **Now:** the strongest categories, aesthetics, brands, tags, and keywords for immediate sell-through
- **Next 60-90 days:** the categories, tags, aesthetics, and seasonal cues most likely to strengthen next
- **Avoid / deprioritize:** categories, brands, or tags where the user already looks saturated or slow-moving

This brief is what you should map against Raghouse titles.

### 3. Pull full Raghouse catalog coverage

Start with collection discovery, not product guessing.

1. Fetch `https://raghouse.com/collections.json?limit=250` so you know which published collections exist on the site right now.
2. Build the actual candidate inventory from the full public product feed with `https://raghouse.com/products.json?limit=250&page=N` or `https://raghouse.com/collections/all/products.json?limit=250&page=N`.
3. Only rely on a single collection endpoint like `https://raghouse.com/collections/get-this-box/products.json?...` when:
   - the user explicitly asked for that collection
   - the attached/local snapshot is partial and you need to fill a blind spot
   - you need to confirm a specific collection lane after the full-catalog pass

Do **not** let the recommendation set come only from `get-this-box` unless the user explicitly narrowed the task to that collection.

Use the helper script when possible:

```bash
python3 scripts/fetch_raghouse_catalog.py --output data/runtime/raghouse-catalog.json
```

The helper captures the public collection index plus the paged public product feed so you can rank across the broader Raghouse catalog without hand-building requests.

If a current Raghouse catalog JSON snapshot is already attached or available locally, use that instead of refetching so the math stays reproducible, but inspect its coverage honestly first.

If most or all products in the snapshot carry `gtb`, `VIP_Product`, or another obviously narrow tag, treat it as a partial collection slice rather than the full Raghouse catalog. Say that plainly instead of presenting it like site-wide coverage.

Prefer structured JSON data over scraping card HTML.

Build candidate product URLs as:

```text
https://raghouse.com/products/{handle}
```

These URLs are **candidate URLs only**. They are useful for lookup, but they are not confirmed working links until the browser-assisted path validates them against the live site.

### 4. Normalize each product

For each product, capture:

- title
- handle
- candidate_url
- availability
- price
- estimated pieces from title
- estimated COG per item = `price / pieces`
- category / keyword hints
- collection or catalog-scope hints when available
- Vendoo signal matches
- current-market research matches
- next-60-90-day matches
- overstock penalties
- condition-risk flags

If the title contains a piece-count range like `~78 to 88 pcs`, use the **lower bound** for conservative math and optionally mention the full range in prose.

If piece count cannot be parsed reliably, exclude it from combo math or clearly mark it as unknown instead of guessing.

Do not infer condition from aesthetic wording alone. Titles like `Dirty White`, `faded`, or `distressed` may describe style or wash. Only treat condition as risky when the listing explicitly signals it through terms like `DIY`, `damaged`, `stained`, `salvage`, or `unsorted`.

Do not infer page-access behavior from `VIP_Product`. It does not tell you whether a direct product URL will work in the current browsing session.

Use **whole-word matching** for excluded-category terms so words like `Brand` do not false-match `bra`.

### 5. Hard filters

Reject any product that is:

- unavailable
- labeled `recycle`, `recycled`, `ready recycle`, or similar in title, type, tags, or body text
- kidswear
- bras, lingerie, intimates

Treat `Recycle & Good ...` items as recycled. Exclude them.

Seasonal or holiday inventory is allowed **if** the economics are strong and the next-window demand brief supports it. Do not auto-reject a seasonal lot just because it is seasonal.

Treat explicit condition-risk lots like `DIY`, `salvage`, `damaged`, or `unsorted` as soft negatives unless the user explicitly wants repair / project inventory. Do not silently elevate them just because the COG is low.

### 6. Ranking logic

Keep the skill's original economics-first behavior, but make the tie-breaks smarter.

Use this order:

1. **Valid only:** filtered pool after exclusions
2. **Combo search by tier:** find combinations that land inside each budget band
3. **Discard dominated combos:** if another combo has both lower or equal blended COG and higher or equal total pieces, drop the worse combo
4. **Build an economics shortlist:** from the frontier, keep combos within roughly 10% of the best blended COG for that tier
5. **Score demand fit inside that shortlist**
6. **Choose the primary winner:** highest demand-fit score among the economics shortlist
7. **Tie-breaker 1:** more pieces
8. **Tie-breaker 2:** lower blended COG
9. **Tie-breaker 3:** fewer boxes

Use this demand-fit scoring heuristic:

- `+3` for strong matches to recent Vendoo winners (categories, brands, tags, keywords)
- `+2` for strong current-market research matches
- `+2` for strong next-60-90-day matches
- `-3` for overstock / slow-moving matches from the user's active inventory, including saturated tags/themes
- `-2` for explicit condition-risk lots

Do not let one repeated keyword inflate the score unrealistically. Collapse obvious duplicates when a single theme is expressed multiple times in the same title.

If no Vendoo export was available, drop the Vendoo parts of the score and say the ranking is based on external research + Raghouse economics only.

Fast-turn signals often include keywords like:

- graphic
- statement
- destination
- sports
- vintage
- y2k
- variety mix
- baby tee
- crop
- mesh / sheer
- festival / boho
- summer / beach / cover-up
- recognizable mall / athletic / vintage-friendly brand cues

Use those signals to improve selection **inside** the economics shortlist, not as the first ranking rule.

For the **high** tier, do not overspend just because the band is open-ended. Aim for the cheapest combo that gets just over `$300` while still maximizing pieces and matching the demand brief.

If the user asks for a single budget instead of tiers, apply the same ranking logic inside that budget cap.

### 7. Browser-assisted verification path

When the user asks for working links, live confirmation, or explicitly says to use Chrome DevTools MCP:

1. Run `python3 scripts/devtools_runtime.py bootstrap`.
2. If needed, run `python3 scripts/devtools_runtime.py launch-chrome`.
3. Use `python3 scripts/devtools_runtime.py mcporter list` first so you can see the live Chrome DevTools MCP tool surface available in this environment.
4. Use the available page-selection, navigation, snapshot, and evaluation tools exposed by that runtime to control the live Raghouse session.
5. Open Raghouse in the controllable tab and search the shortlisted exact titles first.
6. For each shortlisted product, confirm that the visible live title matches the catalog title before trusting the page.
7. Only record a direct URL when the live browser session actually resolved to the intended product page.
8. If the exact product cannot be verified in browser, keep the product in the sourcing recommendation but present it as `title + handle` with no working link claim.

Do not classify a page as broken or VIP-gated from a single cue like one H1, banner, or partial body snapshot. Confirm failure with stronger evidence such as repeated direct navigation plus absence of the intended product title or purchase UI. If a link works for the user but not in your current session, report the behavior as session-dependent rather than universally broken.

If browser verification finds that a candidate URL redirects, lands on the wrong product, or otherwise fails to confirm the intended box, do not keep presenting that URL as if it works.

### 8. Output format

Return:

#### Data used
- Vendoo export analyzed, or `No local Vendoo export found`
- exact Vendoo file path used and modified time when available
- brief note on file freshness or sample strength if relevant
- brief note on external research coverage
- Raghouse catalog coverage note, including whether the data came from the full catalog, a multi-collection sample, or a partial `get-this-box` / VIP-heavy slice

#### Store signals
- recent winners from Vendoo, including categories / brands / tags / keywords
- overstock / deprioritize areas, including saturated tags when relevant
- platform-specific tag/theme skews when the export supports them
- strongest next-60-90-day opportunities

#### Low tier
- selected boxes
- total spend
- total pieces
- blended estimated COG
- exact titles
- handles
- browser-verified URLs only if they were confirmed in the live browser session
- why this combo wins economically
- why it fits the user's store data and upcoming demand

#### Mid tier
- selected boxes
- total spend
- total pieces
- blended estimated COG
- exact titles
- handles
- browser-verified URLs only if they were confirmed in the live browser session
- why this combo wins economically
- why it fits the user's store data and upcoming demand

#### High tier
- selected boxes
- total spend
- total pieces
- blended estimated COG
- exact titles
- handles
- browser-verified URLs only if they were confirmed in the live browser session
- why this combo wins economically
- why it fits the user's store data and upcoming demand

Then add:

- **Fast-turn leaders:** 3-5 individual boxes most likely to move quickly
- **Not chosen:** briefly note any tempting recycled or excluded boxes you intentionally skipped

If the user only asked for one budget, return the best combo under that cap and optionally include a cheaper and richer alternative.

If you include any direct Raghouse product URLs, add a short verification note such as:

`Direct Raghouse product URLs below were browser-verified in the current Chrome session. Any box shown without a URL was not verified in-browser, so use the exact title + handle to find it manually.`

If your catalog coverage is partial, say so plainly:

`Based on the visible live Raghouse catalog sample I could fetch right now.`

If the attached or fetched Raghouse data is obviously skewed toward one collection, say that too:

`This Raghouse input appears heavily skewed toward get-this-box / VIP inventory, so I treated it as a partial sample rather than the full collections catalog.`

## Common Mistakes

- **Skipping Vendoo analysis when the user explicitly asked for it**  
  If a local export exists, use it first. If one cannot be found, say that clearly.

- **Using a stale or non-fresh export without saying so**  
  Mention the exact file and freshness. The user asked for the latest export, not vibes.

- **Treating generic trend research as more important than the user's own sales data**  
  Vendoo should anchor the read. Research sharpens it.

- **Ignoring tags/themes even when Vendoo has them**  
  Categories alone are not enough. Surface the tags and aesthetics that are actually moving or saturated.

- **Letting the recommendation pool come only from `get-this-box`**  
  Unless the user explicitly asked for that collection, sweep the broader Raghouse catalog first. Use collection discovery plus the full product feed so non-`gtb` inventory can compete fairly.

- **Treating a `gtb` / `VIP_Product`-heavy snapshot like full site coverage**  
  That is a partial slice, not the whole Raghouse catalog. Call out the bias instead of hiding it.

- **Failing to distinguish "selling now" from "likely to strengthen next"**  
  Those are separate signals and should be presented separately.

- **Picking recycled because it is cheap**  
  Cheap is irrelevant if the user said no recycled. Exclude first.

- **Calling boxes "guaranteed to sell"**  
  You can rank fast-turn proxies. You cannot promise outcomes.

- **Chasing vibe over math**  
  Do not choose a "cooler" combo if another valid combo has materially better pieces and COG, unless the better-demand combo is still inside the economics shortlist.

- **Using the optimistic end of a ranged piece count**  
  Use the lower bound for combo math. Be conservative.

- **Treating fashion descriptors as damage signals**  
  `Dirty White` is not the same as `damaged` or `DIY`. Do not invent condition problems from style wording alone.

- **Using substring filters for excluded categories**  
  `Brand Sports Shorts` is not lingerie. Use whole-word matching for terms like `bra`.

- **Assuming `VIP_Product` means the page is definitely gated**  
  Treat that tag as metadata only. Validate actual page behavior in the live browser if links matter.

- **Ignoring unavailable products**  
  Never recommend out-of-stock boxes.

- **Using excluded categories because the COG looks amazing**  
  High-piece bras, intimates, or kidswear still fail the request.

- **Giving unverified direct links**  
  Do not paste `/products/{handle}` links as if they are confirmed working product pages. Verify them with Chrome DevTools MCP first, or fall back to title + handle only.

- **Skipping browser verification after the user explicitly asked for it**  
  If the user asked for Chrome/DevTools/browser verification, do not silently fall back to guessed links. Either verify them or say what blocked verification.

- **Calling a link blocked too aggressively**  
  A single VIP banner, H1, or partial snapshot is not enough to declare a Raghouse URL unusable for everyone. Use stronger confirmation, and if the user reports the link works, treat access as session-dependent.

- **Ignoring overstock in the user's active inventory**  
  A box can look trendy and still be a bad buy if the user is already sitting on too much adjacent inventory.

- **Spending too far above the tier floor**  
  Especially for the high tier, stay efficient instead of padding the basket.

## Example decision rule

If Combo A and Combo B are both inside the economics shortlist, and Combo B has materially stronger Vendoo + market fit, Combo B can beat Combo A. But if Combo B is far worse on blended COG, it should not leapfrog the cheaper combo just because it sounds trendier.
