---
name: box-scout
description: Use when the user wants to know which wholesale clothing boxes, lots or bales to buy on raghouse.com or thriftvintagefashion.com: trending themes, a decent piece count and cost per piece, expected profit, with shipping estimated to New Orleans, LA 70115.
triggers:
  - "raghouse"
  - "thrift vintage fashion"
  - "what boxes should i buy"
  - "find boxes to buy"
  - "wholesale lots"
---

# Box Scout

## Purpose
Decide which wholesale clothing lots to buy. Crawl Raghouse (Phoenix, AZ 85043) and Thrift Vintage Fashion (Hialeah, FL 33016), estimate what each lot costs landed in New Orleans (70115), price what its pieces resell for, and return a buy list within a budget with a cart link per store.

Studio's **Sourcing** page runs this same script on a timer and keeps the buy list ready. Use this skill when working outside Studio or when the seller asks in chat.

Both stores are Shopify shops, so their public `/products.json` feeds list every lot with its price, stock and shipping weight without logging in.

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| budget | number | No | Most to spend this round. Default $300. |
| vip | boolean | No | The seller has Raghouse VIP ($64/month). Boxes tagged `VIP_Product`, most of each new Raghouse drop, are members-only; they are left out unless `--vip`. |

## How the stores differ
- **Raghouse** sells unsorted boxes of 20–230 pieces, titled `... 61 pcs`, dated by tag, graded "Recycle" (needs TLC), "Recycle & Good" or plain. It lands at roughly $1–3 per usable piece; shipping is often more than the box.
- **Thrift Vintage Fashion** sells sorted 10–40 piece packs, variants graded A/B/C, and bales by the pound (25–200 lb). It costs more per piece and states its own "Estimated Resale Value" in each description; treat that as the seller's claim, not evidence. It ships free on orders over $200.

## Workflow

### 1. Research what is selling now
Search for what secondhand and vintage clothing sells fastest on eBay, Poshmark, Depop and Mercari this month. Turn it into 10–20 short lowercase terms spelled the way lot titles spell them: brands (`carhartt`, `harley`), eras (`y2k`, `90s`, `vintage`), themes (`cartoon`, `sports`, `western`) and garments (`fleece`, `flannel`).

### 2. List the themes to price
```bash
python3 skills/box-scout/scripts/scout.py --trend "carhartt,y2k,cartoon,..." --themes
```
This prints the lot themes that most need a resale price, best demand first. A theme is a lot's title without counts, grades and store filler: `Abbie Recycle Tees & Tops 87 pcs` becomes `abbie tees & tops`.

### 3. Price each theme
For each theme, search sold listings from the last 90 days and estimate what one typical piece from a mixed lot sells for: the median piece, not the best find. Write the results to a file keyed by the exact theme text:
```json
{"cartoon t-shirts": 14, "vintage graphic t-shirts": 22, "men's flannel shirts": 12}
```

### 4. Build the buy list
```bash
python3 skills/box-scout/scripts/scout.py --trend "..." --resale resale.json --budget 300
```
For every in-stock lot the script computes:
- **Ship est**: the store's carrier list rate for the lot's weight and zone, plus that carrier's residential surcharge and fuel surcharge, times the store's `ship_factor`. Raghouse is FedEx Ground (zone 6 from Phoenix to 70115). TVF is UPS Ground (zone 5 from Hialeah to 70115). Weights round up to the next pound. TVF lots with no weight are estimated from their piece count. Raghouse's factor is order #83897: FedEx charged $33.95 on a 29 lb box whose list estimate was $65.96. TVF is still list price.
- **Usable pieces**: pieces × the share a grade yields (90% plain, 75% Recycle & Good, 60% Recycle or B grade, down to 50% for C grade). Bales sold by the pound get a piece count from typical garment weights (3 tees, 1 sweatshirt or 0.6 jackets per pound), marked `~`.
- **Demand**: how often lots with the same title words sold out, relative to that store's average. Raghouse counts the last 60 days; TVF restocks the same products, so all of its lots count.
- **Expected profit** = resale per piece × usable pieces × sell-through × (1 − 20% fees) − landed cost. Sell-through is 50% at average demand, scaled by demand between 25% and 80%.
- **ROI** = expected profit ÷ landed cost.

The buy list takes the best ROI first, one lot per theme, at least 100% ROI (`--min-roi`), until the budget runs out. Shipping discounts are applied before checking the budget and return target. When the picks from TVF reach $200 their shipping drops to zero. Studio also computes Raghouse-only and Thrift Vintage Fashion-only alternatives with the same full budget; choose one plan rather than adding the alternatives together. Each store's cart link (`/cart/<variant>:1,...`) opens that store's cart with the picks in it.

### 5. Report
Give the buy list: per store, the lots with pieces, landed cost, resale per piece, expected profit and ROI, the store subtotal and shipping, and the cart link. Then the next five candidates. Raghouse shipping is FedEx, scaled to a real checkout. TVF shipping is still a UPS list-price ceiling. The profit rests on the resale prices you found.

## Shipping estimate
`references/shipping.json` holds UPS Ground and FedEx Ground list rates for zones 2–8, 1–150 lb, the zone of each store (from the USPS zone chart; Phoenix 850 to 70115 is FedEx zone 6), each carrier's residential and fuel surcharges, and a `ship_factor` per store. Raghouse ships FedEx. TVF is estimated as UPS. The stores quote discounted rates at checkout, so the real charge is usually lower than list. **When the seller reports a real checkout quote, set that store's `ship_factor` to quote ÷ estimate.** Raghouse is already set from order #83897 ($33.95 ÷ $65.96 FedEx list). Update a carrier's fuel surcharge when it is more than a month old.

## Rules
- **Never buy.** Do not check out, log in or create an account; a cart link only fills the cart, and the seller pays.
- Do not try to get past Cloudflare challenges, bot checks or rate limits. Raghouse's live shipping quote sits behind one; that is why shipping is estimated. If a catalog stops answering, report it and continue with the other store.
- Crawl once per run, one second between pages.

## Error Conditions

| Error | Cause | Resolution |
|-------|-------|------------|
| HTTP 403/429 or a challenge page | The store is blocking the crawl | Report it and use the other store. Do not retry in a loop. |
| Empty buy list | No priced lot clears the ROI bar within budget | Say so; list the best candidates and what their ROI would be. |
| Lot missing | Sold out, no piece count, under 10 pieces, or over 150 lb | Mention it if the seller asked about it by name. |
| Estimates far from real quotes | Discounted carrier rates or a stale fuel surcharge | Calibrate `ship_factor` and update the fuel surcharge. |
