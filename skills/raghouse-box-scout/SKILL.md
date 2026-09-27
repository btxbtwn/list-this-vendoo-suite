---
name: raghouse-box-scout
description: Use when the user wants to find the best clothing boxes (lots) to buy on raghouse.com — trending themes, a decent piece count, a decent cost per piece, with shipping estimated to New Orleans, LA 70115.
triggers:
  - "raghouse"
  - "find boxes to buy"
  - "best raghouse deals"
  - "scout raghouse"
---

# Raghouse Box Scout

## Purpose
Crawl the raghouse.com catalog, estimate what each box costs landed in New Orleans (70115), and recommend the boxes worth buying: ones whose contents are trending on resale apps, with enough pieces to be worth a shipment and a landed cost per usable piece that leaves room for profit.

Raghouse is a Shopify store in Phoenix, AZ (85043). Every box title carries its piece count (`... 61 pcs`), and every variant carries its full shipping weight in grams. That makes the whole catalog readable from the public `/products.json` feed without logging in.

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| budget | number | No | Maximum box price. Passed as `--max-price`. |
| focus | string | No | Categories or brands the seller wants (e.g. "jackets", "Carhartt"). Added to the trend terms. |
| vip | boolean | No | Whether the seller has a Raghouse VIP membership. Without one, pass `--no-vip`. Boxes tagged `VIP_Product` sit in the members-only VIP store ($64/month); on 2026-09-27 that was nearly all of the newest drop. |

## Workflow

### 1. Research what is trending now
Search the web for what is selling on resale marketplaces this month and season (eBay, Poshmark, Depop and Mercari trend reports, and "what's selling" reseller posts from the last 30 days). Turn the findings into 8–15 short terms in the words Raghouse uses in its titles: brands (`carhartt`, `harley`, `columbia`, `ralph`), eras (`y2k`, `90s`, `vintage`), themes (`cartoon`, `sports`, `western`, `band`) and garments (`fleece`, `crops`, `corduroy`). Terms match whole words, so `band` will not match "bandanas".

### 2. Run the scout
```bash
python3 skills/raghouse-box-scout/scripts/scout.py --trend "carhartt,y2k,cartoon,..." --top 25
```
Add `--no-vip` unless the seller is a VIP member, and `--max-price` for a budget. Pass `--json` to get every ranked box with all its fields.

The script crawls the catalog once (7–8 pages, one second apart), keeps in-stock boxes of clothes, and for each box computes:

- **Ship est**: UPS Ground list rate for the box's weight to zone 6, plus the $6.50 residential surcharge and the current fuel surcharge (see *Shipping estimate*).
- **Landed** = box price + ship est.
- **$/usable pc** = landed ÷ (pieces × usable share). The usable share is 90% for plain boxes, 75% for "Recycle & Good" and 60% for "Recycle" boxes, which Raghouse sells as needing TLC.
- **Demand**: how often boxes whose titles share this box's words sold out on Raghouse in the last 60 days, relative to the store-wide rate. 1.5x means lots like this one sell out 50% more often than average. It measures what resellers buying from Raghouse are competing for right now.
- **Trend**: which of your trend terms appear in the title. Each hit (up to two) adds 25% to the score.
- **Score** = demand × trend boost, discounted only when $/usable pc is above `--target-cog` (default $2.00). Boxes above `--max-cog` (default $4.00) and below `--min-pcs` (default 20) are dropped.

### 3. Run a second pass for higher-value categories
Jackets, fleece, sweaters and branded workwear cost more per piece and resell for more, so the default caps hide them. Run again for those:
```bash
python3 skills/raghouse-box-scout/scripts/scout.py --trend "..." --target-cog 4 --max-cog 8 --min-pcs 12 --top 25
```

### 4. Price the shortlist
For the 8–12 strongest candidates across both passes, estimate the average sold price per piece for what that box holds (use recent sold comps for the theme, such as "vintage cartoon t-shirt sold" or "Carhartt fleece jacket sold"; a mixed box should use a conservative blend). Then compute:

- **Resale value** = average sold price × pieces × usable share
- **Net after fees** ≈ resale value × 0.80 (marketplace fees and payment processing)
- **ROI** = net after fees ÷ landed

Open each finalist's product page to check the description and video notes for sizes, condition and anything the title does not say.

### 5. Report
Return a markdown table of the top 5–10 boxes: link, pieces, grade, price, ship est, landed, $/usable pc, demand, the trend terms it hit, estimated resale per piece and ROI. Put first the boxes you would buy and say why in one line each. Then note:
- that shipping is an estimate and which assumptions it rests on;
- which boxes are VIP-only;
- any box whose shipping is more than its price, because shipping is usually the largest cost.

## Shipping estimate
`references/shipping-70115.json` holds the UPS Ground zone 6 daily rates for 1–150 lb (UPS 2026 Daily Rates, updated September 7, 2026). The USPS zone chart puts origin 850 to 700–701 in zone 6, which matches UPS's distance bands for this lane. The file also holds the residential surcharge, the fuel surcharge and its date, and a `ship_factor`.

The estimate is a ceiling. Raghouse quotes discounted UPS and Amazon Shipping rates live at checkout, so the real charge is usually lower. Its live-rate endpoint sits behind a Cloudflare challenge, so the skill cannot quote it directly. **When the seller reports a real checkout quote for a box, set `ship_factor` to quote ÷ this skill's estimate for that box** (with the factor at 1.0), and every later estimate follows. The UPS fuel surcharge changes weekly: update `fuel_surcharge_pct` and `fuel_surcharge_as_of` when they are more than a month old, or pass `--fuel`.

Dimensional weight is not modelled: the listed weight is what the estimate uses. `ship_factor` absorbs the difference once calibrated.

## Rules
- **Read-only.** Never add to cart, check out, log in or create an account. The seller buys.
- Do not try to get past Cloudflare challenges, bot checks or rate limits. If `/products.json` stops answering, say so and stop.
- Crawl once per run; do not poll.
- Piece counts come from the title. A title with `~` (for example `~230 pcs`) is Raghouse's estimate; say so when such a box is a finalist.

## Error Conditions

| Error | Cause | Resolution |
|-------|-------|------------|
| HTTP 403/429 or a challenge page | Raghouse or Cloudflare is blocking the crawl | Stop and tell the seller. Do not retry in a loop. |
| No boxes returned | Filters too tight | Loosen `--min-pcs`, `--max-cog` or `--max-price` and say which you changed. |
| Box missing from results | Weight is 0 or over 150 lb, or the title has no piece count | Mention it if the seller asked about it by name. |
| Estimates far from real quotes | Discounted carrier rates or stale fuel surcharge | Calibrate `ship_factor` and update the fuel surcharge as described above. |
