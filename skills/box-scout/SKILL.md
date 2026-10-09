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
| min_roi | number | No | Minimum estimated profit ÷ purchase cost. Default 1.0 (100%). |
| sell_through | number | No | Seller’s planned share of usable pieces that sell, 0–1. Default 0.5. This is not a measured probability. |
| fees | number | No | Effective marketplace and payment fee allowance, 0–1. Default 0.2; replace with actual effective costs. |
| cost_per_piece | number | No | Operating allowance for each usable piece, including prep, labor, packaging, seller-paid postage, fixed fees and returns. Default $2 is a planning input, not a market fact. |
| ready_in_weeks | integer | No | Weeks for inbound shipping, prep and listing before selling starts, 0–26. Studio default 4. |
| selling_window_weeks | integer | No | Length of the target selling period, 1–26 weeks. Studio default 4 (selling 4–8 weeks after buying). |
| vip | boolean | No | The seller has Raghouse VIP ($64/month). Boxes tagged `VIP_Product`, most of each new Raghouse drop, are members-only; they are left out unless `--vip`. |

## How the stores differ
- **Raghouse** sells unsorted boxes of 20–230 pieces, titled `... 61 pcs`, dated by tag. Its "Recycle" and "Recycle & Good" boxes need TLC and are never scouted. It lands at roughly $1–3 per usable piece; shipping is often more than the box.
- **Thrift Vintage Fashion** sells sorted 10–40 piece packs, variants graded A/B/C, bales by the pound (25–200 lb) and brand mixes sold by weight. Its A/B, B, B/C and C grades carry defects and are never scouted. It costs more per piece and states its own "Estimated Resale Value" in each description; treat that as the seller's claim, not evidence. It ships free on orders over $200.

## Workflow

### 1. Research for the selling window
Set an explicit dated selling window based on shipping, preparation and listing time. Studio defaults to starting four weeks after buying, lasting four weeks; the seller can adjust both. Research seasonal categories and upcoming holidays for that window using current marketplace sources. The inbound shipping ZIP is not the location of nationwide buyers.

When seller sales history is available, compare recorded, dated actual single-item sales from the same calendar windows in the previous three years. Prefer listing facets frozen at first observation of a sale; label current facets as unverified at sale. Require five sales in a category/type group before supplying it as context. Do not substitute asking prices for missing sold amounts, compare raw counts as a demand lift, infer inventory exposure or conversion, or claim the sample represents all seller sales. Historical median prices are context only and cannot replace recent comps.

Search for what secondhand and vintage clothing is relevant on eBay, Poshmark, Depop and Mercari during that window. Turn it into 10–20 short lowercase terms spelled the way lot titles spell them: brands (`carhartt`, `harley`), eras (`y2k`, `90s`, `vintage`), themes (`cartoon`, `sports`, `western`) and garments (`fleece`, `flannel`).

### 2. List the themes to price
```bash
python3 skills/box-scout/scripts/scout.py --trend "carhartt,y2k,cartoon,..." --themes
```
This prints the lot themes that most need a resale price, best demand first. A theme is the resale category one piece of the lot would be searched under: up to two style words, era first, and the garment, from the vocabulary in `scout.py` (`THEME_STYLES`, `THEME_GARMENTS`). Sorter names, bin names, seasons, sizes, pack counts and brand lists are dropped, so `Dirty White Graphic + Vintage + Concert Tees 57 pcs` becomes `vintage band t-shirts` and `Aerie Abercrombie Hollister American Eagle Aeropostale Sweatshirts & Joggers 23 pcs` becomes `brand name pants`. The garment is the last one named (`Crop Blouses` are blouses). Both stores together make about 175 themes instead of one per lot, so research can cover the whole catalog.

### 3. Price each theme
In Studio, the seller's own recorded sales come first: a sold listing counts for a theme when it is the same garment and its title carries every style the theme names (a `Vintage 90s Harley Davidson T-Shirt` counts for `harley davidson t-shirts` and for `vintage harley davidson t-shirts`; a plain `Harley Davidson Tee` counts only for the first). Those sales carry real prices and dates, so they qualify a theme on their own; web research adds to them and is skipped for a day after it came back short.

For each theme, find at least three distinct comparable sold listings within the last 30 days. This is the minimum sample accepted by Studio, not a statistical guarantee. Match garment type, likely brand tier, era and condition to ordinary pieces in the lot; exclude rare premium finds, bundles, new-with-tags condition mismatches and hidden accepted-offer prices. Use actual USD item prices excluding shipping. Keep the item URL, title, reported sale date and quoted sale-price evidence for every example. Active asking prices and supplier resale claims cannot supply a sold price.

Compute the median of retained sales within the last 30 days. Older examples within 90 days can provide context, but cannot qualify a theme or set today’s price. When at least three comparable active listings are available, cap the estimate at their median asking price. Search results are a sample, not the complete market: do not calculate marketplace sell-through, sales velocity or a probability of sale from the count of results. Studio validates supplied data but does not independently verify the source pages, so label dates and sales as AI-reported and let the seller inspect them. Unsupported estimates stay out of recommendations. Research expires after seven days and cached sale dates are rechecked as they age. Studio keeps every box in the snapshot and serves a theme's examples (`GET /api/sourcing/evidence?theme=`) when the seller opens them. When a box joins the buy list between two checks of the same plan, Studio posts a Mac notification.

Outside Studio, write researched prices to a file keyed by the exact theme text:
```json
{"cartoon t-shirts": 14, "vintage graphic t-shirts": 22, "flannel shirts": 12}
```

### 4. Build the buy list
```bash
python3 skills/box-scout/scripts/scout.py --trend "..." --resale resale.json --budget 300
```
For every in-stock lot the script computes:
- **Ship est**: the store's carrier list rate for the lot's weight and zone, plus that carrier's residential surcharge and fuel surcharge, times the store's `ship_factor`. Raghouse is FedEx Ground (zone 6 from Phoenix to 70115). TVF is UPS Ground (zone 5 from Hialeah to 70115). Weights round up to the next pound. TVF lots with no weight are estimated from their piece count. Raghouse's factor is order #83897: FedEx charged $33.95 on a 29 lb box whose list estimate was $65.96. TVF is still list price.
- **Usable pieces**: pieces × the share a grade yields (90% plain, 95% TVF A grade). Bales and brand mixes sold by weight get a piece count from typical garment weights (3 tees, 1 sweatshirt or 0.6 jackets per pound), marked `~`.
- **Demand**: how often lots with the same title words sold out, relative to that store's average. Raghouse counts the last 60 days; TVF restocks the same products, so all of its lots count.
- **Expected profit** = resale per piece × usable pieces × planned sell-through × (1 − effective fees) − operating allowance × usable pieces − landed cost. The seller’s own underperforming box sales can reduce a supplier’s forecasts; stronger past sales never raise them above current researched prices. Wholesale sell-out helps prioritize research; selling-window matches prioritize research and qualifying picks; they never increase planned resale sales.
- **Break-even pieces** = round up ((landed cost + operating allowance × usable pieces) ÷ (resale per piece × (1 − effective fees))).
- **Lower-sales test** = profit if half the planned pieces sell at the lower of the lowest retained sold price and the resale estimate, with the full operating allowance still deducted. A recommended box must not lose money in this scenario. It is a sensitivity test, not a guaranteed floor or probability. Outside Studio, a price-only input uses its researched price for this scenario; it does not carry the sold-price range.
- **ROI** = expected profit ÷ landed cost.

The buy list prefers researched selling-window matches among qualifying boxes, then takes the best incremental return, one lot per theme, at least 100% ROI (`--min-roi`) and a nonnegative lower-sales test, until the budget runs out. The default usable shares remain planning assumptions, not inspected counts. Shipping discounts are applied before checking the budget and return target. When the picks from TVF reach $200 their shipping drops to zero. The script also evaluates two-box combinations that cross that threshold even when neither qualifies alone. This greedy selection does not guarantee the mathematically best combination. Studio also computes Raghouse-only and Thrift Vintage Fashion-only alternatives with the same full budget; choose one plan rather than adding the alternatives together. Each store's cart link (`/cart/<variant>:1,...`) opens that store's cart with the picks in it.

### 5. Report
Give the buy list: per store, the lots with pieces, landed cost, resale per piece, expected profit, operating allowance, break-even sales, lower-sales test and ROI, the store subtotal and shipping, and the cart link. Then the next five candidates. Raghouse shipping is FedEx, scaled to a real checkout. TVF shipping is still a UPS list-price ceiling. The profit rests on the resale prices you found.

## Shipping estimate
`references/shipping.json` holds UPS Ground and FedEx Ground list rates for zones 2–8, 1–150 lb, the zone of each store (from the USPS zone chart; Phoenix 850 to 70115 is FedEx zone 6), each carrier's residential and fuel surcharges, and a `ship_factor` per store. Raghouse ships FedEx. TVF is estimated as UPS. The stores quote discounted rates at checkout, so the real charge is usually lower than list. **When the seller reports a real checkout quote, set that store's `ship_factor` to quote ÷ estimate.** Raghouse is already set from order #83897 ($33.95 ÷ $65.96 FedEx list). Update a carrier's fuel surcharge when it is more than a month old.

## Rules
- Never claim a box or its individual pieces are guaranteed to sell. Sold examples support a price estimate; mixed contents, condition and future demand remain unknown. Never display a confidence percentage that has not been calibrated against observed outcomes.
- Before purchase, review supplier photos, likely brands, sizes and grade notes against the comparable sales, confirm final freight and tax, and keep cash for processing. Inspect and photograph the shipment on arrival. Raghouse purchases are final; TVF asks for problems to be reported with photos within 72 hours.
- Before resale, clean/prepare each item, take actual front/back/label/flaw photos, measure useful dimensions, and disclose condition precisely. Use the canonical `list-this` listing workflow for drafts; sourcing must never publish listings.
- **Never buy.** Do not check out, log in or create an account; a cart link only fills the cart, and the seller pays.
- Do not try to get past Cloudflare challenges, bot checks or rate limits. Raghouse's live shipping quote sits behind one; that is why shipping is estimated. If a catalog stops answering, report it and continue with the other store.
- Crawl once per run, one second between pages.

## Error Conditions

| Error | Cause | Resolution |
|-------|-------|------------|
| HTTP 403/429 or a challenge page | The store is blocking the crawl | Report it and use the other store. Do not retry in a loop. |
| Empty buy list | No priced lot clears the ROI bar within budget | Say so; list the best candidates and what their ROI would be. |
| Lot missing | Sold out, Raghouse Recycle or TVF A/B, B, B/C or C grade, no piece count or weight, under 10 pieces, or over 150 lb | Mention it if the seller asked about it by name. |
| Estimates far from real quotes | Discounted carrier rates or a stale fuel surcharge | Calibrate `ship_factor` and update the fuel surcharge. |

## Research basis (reviewed 2026-10-07)

- [eBay research tools](https://www.ebay.com/sellercenter/growth/ebay-research-tools): research sales trends across time windows to plan inventory ahead of seasonal demand. Studio uses dated planning context, without inventing a seasonal price increase.
- [eBay Product Research](https://www.ebay.com/help/selling/selling-tools/research?id=4853): compare sold prices, condition, attributes, shipping and time windows; complete research data can include accepted-offer prices. Public snippets often cannot expose that actual price, so exclude hidden offers.
- [eBay clothing selling guidance](https://www.ebay.com/sellercenter/selling/what-to-sell/selling-clothes): accurate condition, item specifics, measurements, photos and competitive pricing affect outcomes. A trend alone cannot establish that an unidentified mixed garment will sell.
- [eBay selling fees](https://www.ebay.com/help/selling/fees-credits-invoices/selling-fees?id=4822) and [Depop shop guidance](https://www.depop.com/blog/grow-your-shop/): costs and competition differ by marketplace. Use an effective allowance and actual operating costs rather than asserting one universal fee rate.
- [Raghouse FAQ](https://raghouse.com/pages/faq): Recycle clothing may have tears, stains or missing buttons; purchases are final. That is why Recycle boxes are skipped.
- [TVF FAQ](https://thriftvintagefashion.com/pages/faqs-tvf): grade B can have defects; C suits rework; clothing arrives unlaundered; subjective returns are not accepted. That is why only plain and A-grade lots are scouted. Supplier estimated resale values are claims, not completed-sale evidence.
- [ThredUp 2026 Resale Report](https://www.thredup.com/resale): broad market trends provide research context. Aggregate resale growth does not establish demand for an individual lot, garment or brand.

The sample floor, seven-day cache, $2 operating allowance and half-sales sensitivity test are product safeguards, not marketplace promises. Adjust planning costs to the seller’s actual operation; no public trend report can make wholesale resale certain.
