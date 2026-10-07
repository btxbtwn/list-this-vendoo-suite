---
name: list-this
description: Use when the user wants a marketplace listing from attached product images or a local photo path, including standard resale listings and Etsy digital download listings.
triggers:
  - "create listing"
  - "make a listing"
  - "list this"
  - "generate listing"
---

# List This - Product Listing Workflow

## Purpose
Generate accurate, formula-compliant marketplace listings from product photos. Extract visual details, apply strict formatting rules, output Vendoo-compatible JSON for standard listings, output copy-pasteable text for Etsy digital downloads, and persist the final result beside the source photos whenever the user provides a local path.

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| photos | array | Yes* | Product images (minimum: front, tag/label, any flaws). If `path` is provided, load the images from there. |
| measurements | string | No | User-provided measurements. The Studio passes the measurements for the seller's selected garment type (inches): tops as `- Measurements (top): Pit to pit: 22.5"; Length: 27"; Sleeve: 9"`, pants and shorts (both under pants) as `- Measurements (pants): Waist: 16"; Rise: 11"; Inseam: 30"; Leg opening: 8"`. Use these exact values in the description; do not modify or estimate them. |
| path | string | No | Local file or folder path for the product photos. If it is a folder, save `listing.json` for standard listings or `listing.md` for Etsy digital downloads there. If it is a file, save the output in that file's parent folder. |

## Input Requirements

**Required photos:**
- Front view of item
- Close-up of brand tag/label
- Any visible flaws or damage

**Path-based input:**
- A local folder path can be used instead of separately attached photos when it clearly points to the photo set for the item.
- If a single local image path is provided, treat its parent folder as the item folder for both analysis and saving.

**Optional photos:**
- Additional angles
- Detail shots
- Size tag close-up

## Returns

Returns one of the following:
- Standard and physical listings: a Vendoo-compatible JSON object containing `title`, `description`, `price`, and marketplace-specific fields
- Etsy digital download listings: a copy-pasteable plain-text or markdown block containing the final `title`, `description`, `price`, `materials`, `tags`, and Etsy-specific fields
- `listing.json` written to the resolved local photo folder for standard listings when the user provides a local path
- `listing.md` written to the resolved local photo folder for Etsy digital download listings when the user provides a local path

### Sample Output Structure

**For the COMPLETE JSON template with all 100+ fields, see:**
`references/vendoo_listing_template.md` → Section "2. Extension JSON Structure"

**Etsy digital download output:**
```markdown
Title: {etsy title}

Description:
{etsy digital description}

Price: {price}

Materials: {comma-separated materials}

Tags: {comma-separated tags}

Who made: {who_made}
What is it: {what_is}
When made: {when_made}
```

**Note:** The extension can fill 100+ fields across all platforms. Always reference the complete template in `references/vendoo_listing_template.md` for the full field list and allowed values.

**Etsy digital download exception:** Do not return JSON for Etsy digital products. Return a copy-pasteable text block using the Etsy Digital Download Output Format.

## Side Effects

- **External network calls**: `web_search` used for comp research
- **Read-only operations**: Analyzes images, does not modify them
- **Local file write when path is available**: Save the final result as `listing.json` for standard listings or `listing.md` for Etsy digital download listings in the resolved photo folder
- **Stateless listing logic**: Each listing generation is independent apart from the optional local file save

## Error Conditions

| Error | Cause | Resolution |
|-------|-------|------------|
| Brand unclear | Tag unreadable in photos | Infer from logos, hardware, and seller notes when supportable; otherwise leave brand empty — never ask |
| Size conflict | Extractor and Verifier disagree | Prefer the clearer tag reading; if still ambiguous use measurement fallback — never ask |
| Size tag missing | No readable size tag in photos | Fall back to a clean measurement-derived marketplace size; do not mention the missing tag in the description |
| No comps found | Search returned no sold listings | Use estimated baseline; never mention it in the description |
| Missing required photos | No tag/label photo | Infer from the photos provided — never ask for more photos |
| Invalid local path | Provided path does not resolve to an item photo folder | Tell user the path could not be used and return JSON or copy-paste text in chat only |
| Unwritable local folder | Folder exists but the output file cannot be written | Surface the write failure explicitly and do not claim the save succeeded |
| Vision tool returns "no image attached" | vision_analyze fails on local file paths | Switch immediately to mcp_minimax_token_plan_understand_image as fallback — do not retry the failing tool |

## Image Analysis Tools (Critical)

When analyzing product photos, `vision_analyze` (built-in) may fail on local file paths with "I don't have access to the image / no image attached." If this occurs, use `mcp_minimax_token_plan_understand_image` as the reliable fallback:

```
mcp_minimax_token_plan_understand_image(
  image_source: "<local_absolute_path>",
  prompt: "Describe this garment in detail for resale listing: brand, size tag text, color, style, material, neckline, any holes/damage, and other visible details."
)
```

This pattern has been verified across macOS session image caches. Use it immediately on first vision failure — do not retry the failing tool.

## Workflow (MANDATORY)

### Step 1: Extractor (image analysis)
Review all photos and extract:
- Brand, size, color, material, style
- Fit, closures, pockets
- Measurements shown in photos
- Condition, visible flaws

Mark any field as uncertain if unclear.

### Step 2: Verifier (tag confirmation)
Find clearest tag/label photo.
Confirm **brand + size** from visible text only.

If the size tag is missing, cropped out, or unreadable but the garment measurements are available, confirm the brand from the visible label and mark size as `measurement-derived` for fallback handling in the next steps.

### Step 3: Cross-check (MANDATORY)
Extractor and Verifier must agree on brand/size.
If they disagree, prefer the clearer tag/logo evidence; if still unresolved, use measurement fallback for size and leave unsupported brand empty. Never ask the seller clarifying questions.

If no readable size tag exists in the photos, skip strict size-tag agreement and derive an approximate size from the provided or visible measurements instead.

Measurement fallback rules:
- prefer the clearest waist-based sizing signal for bottoms and the clearest pit-to-pit or chest-based sizing signal for tops
- use the nearest standard marketplace size only when the measurements support a reasonable estimate
- if a standard size estimate would be too speculative, use the measurement size itself in the listing copy, such as `30 in waist` or `30x29`
- `size` and marketplace size fields must be a clean dropdown value only (`10`, `M`, `30x29`) — never prefix with `approx`, `approximately`, `about`, `around`, `est`, or `~`

### Step 4: Comp Checker
Follow [Comp research](references/comp-research.md) for sold and active listing searches.
Use `web_search` with query pattern: `"{brand} {item type} sold comps"`, and search active listings separately.
Apply pricing formula from MEMORY.md.

### Step 5: Synthesis (You)
- Enforce title formula EXACTLY
- Enforce the applicable description formula EXACTLY
- Populate platform-specific fields
- For Etsy digital downloads, output a copy-pasteable text block instead of JSON
- Keep uncertainties out of the description (see rule 8)

### Step 6: Local Save (MANDATORY when path is provided)
- Resolve the save folder from the user's local path.
- If the path is a directory, use that directory.
- If the path is a file, use its parent directory.
- Write the final standard listing output to `<resolved folder>/listing.json`.
- Write the final Etsy digital download output to `<resolved folder>/listing.md`.
- Overwrite any existing file for that item so the folder keeps the latest source-of-truth draft.
- Verify the file exists and matches the output you returned before ending the task.
- If no local path was provided, return JSON for standard listings or copy-pasteable text for Etsy digital download listings in chat only.

**Men's Bottoms Sizing (MANDATORY):**
- Men's pants, jeans, shorts, and other bottoms use the waist alone — `34`, never `34x34` or `34x32`.
- Vendoo and marketplace size dropdowns are waist or letter sizes. A waist x inseam value does not match, so the size field stays blank.
- Put that waist in `size`, in every marketplace size field, and in the title.
- When a real inseam is known and it is not a copy of the waist, put it on the eBay Inseam field and in Measurements. Never invent an inseam by repeating the waist.
- Women's bottoms keep their own sizing (`8`, `M`, `30`).

**Petite Size Normalization (MANDATORY):**
- Keep the raw verified tag size in the listing copy when it is a petite code such as `PS`, `PM`, `PL`, or `PXL`.
- For Vendoo/general size mapping, prefer the actual petite code used by the platform dropdown, such as `PS` for petite small, instead of improvising `SP` or free-typing a custom alias.
- For marketplaces that split the size into a base size plus a grouping, map petite sizes as base size plus petite grouping. Example: tag `PS` maps to Depop `Size = S` and `Size grouping = Petite`, while eBay should keep `Size Type = Petites` and use the closest supported petite size code when available.
- When the exact petite mapping is unclear from the live platform options, stop and verify the options instead of flattening the size to plain `S`/`Small`.

**Measurement-Derived Size Fallback (MANDATORY when no size tag is visible):**
- When no readable size tag exists in the photos, derive size from measurements instead of blocking the listing.
- Use the most defensible size expression for the item type. For men's pants, use the waist alone (`34`). Do not write waist x inseam in `size`.
- Put that clean value in `size` / marketplace size fields — never `approx 10` or similar; approximate language belongs only in the description.
- Use `sizeType = Regular` unless the measurements or garment styling clearly indicate Petite, Tall, Plus, or Maternity.
- Record the fallback clearly in the description measurements line when helpful.
- If later browser automation requires a forced dropdown choice that does not support the exact measurement expression, choose the closest reasonable marketplace value and preserve the measurement truth in the description and notes.

**Valid Depop Values (MUST use only these):**
- **Style:** Casual, Streetwear, Vintage, Y2K, Minimalist, Sporty, Bohemian, Grunge, Preppy, Athleisure, Retro
- **Occasion:** Casual, Streetwear, Formal, Sporty, Vintage, Y2K, Bohemian, Minimalist, Retro, Summer, Workwear
- **Material:** Cotton, Cotton - Organic, Cotton - Recycled, Polyester, Denim, Leather, Wool, Silk, Linen, Fleece, Velvet, Satin
- **Fit:** Skinny, Slim, Straight, Bootcut, Relaxed, Oversized, Loose, Regular, High Rise, Mid Rise, Low Rise
- **Source:** Preloved, Deadstock, Vintage, New with tags, New without tags
- **Age:** Modern, Vintage, Y2K

**Depop Specifics (ALWAYS include when supportable):**
- **Source**
- **Age**
- **Style**
- **Type**
- **Fit**
- **Material**
- **Occasion**
- **Size grouping** only when the item is petite, tall, maternity, or plus — use exactly `Maternity`, `Petite`, `Plus size`, or `Tall`. Omit this field entirely for regular sizing; never use values like `US` or `Regular`

**eBay Fields — ALWAYS include ALL of these in `ebay_specifics`. Do not skip any.**

Every eBay listing MUST populate these fields. Leaving them blank causes downgraded search visibility and incomplete Vendoo drafts.

| Field | Value guidance |
|-------|---------------|
| **Type** | T-Shirt, Shorts, Jeans, etc. |
| **Department** | Men, Women, etc. |
| **Size Type** | Regular, Petite, Plus, etc. |
| **Size** | Match tag or measurement-derived |
| **Fit** | Slim, Regular, Relaxed, etc. |
| **Material** | Cotton, Polyester, etc. |
| **Outer Shell Material** | Required for jackets/coats; follow the best-guess rule in Formula Reference when shell composition is unverified. |
| **Pattern** | Solid, Striped, Floral, Tie-Dye, etc. |
| **Style** | Casual, Graphic Tee, etc. |
| **Accents** | Visible features: Graphic Print, Logo, Embroidered, Distressed, etc. |
| **Features** | Graphic Print, Preshrunk, Tagless, Pocket, All Seasons, etc. |
| **Neckline** | Crew Neck, V-Neck, Scoop Neck, Henley, etc. |
| **Closure** | Pullover, Button, Zip, Snap, etc. |
| **Country of Origin** | From tag: China, Haiti, Bangladesh, etc. |
| **Fabric Type** | Cotton, Denim, Polyester, Knit, etc. |
| **Garment Care** | Machine Washable (default) |
| **Handmade** | "No" (always) |
| **Personalize** | "No" (always) |
| **Vintage** | "No" (unless actually vintage) |
| **Occasion** | Casual, Workwear, Formal, etc. |
| **Season** | Exactly one of Spring, Summer, Fall, or Winter — inferred from the item (never blank, never Does Not Apply, never "All Seasons" as Season). |
| **Theme** | Space, Music, Sports, etc. when supportable |
| **Unit Quantity** | "1" (always for single items) |
| **Unit Type** | "Unit" (always) |
| **Rise** | If provided in measurements |
| **Inseam** | If provided in measurements |
| **Waist** | If provided in measurements |

**Pitfall: Skipping any of these fields causes the Vendoo eBay form to show them blank. After "Show Optional Fields", fill every applicable row — non-negotiable unless the attribute literally does not apply (then use Does Not Apply only for MPN, UPC, Character, Theme, Strap Type, Accents, Country of Origin, Sleeve Type). Fabric Weight: leave blank unless a numeric oz/gsm value is evidenced on the tag or seller notes — never Does Not Apply and never the word Lightweight (eBay rejects non-numeric values; do not invent a number). Never leave Features, Neckline, Season, Fit, Pattern, Occasion, Closure, Unit Quantity, or Unit Type blank. Season must be Spring/Summer/Fall/Winter. Verify they are present in `ebay_specifics` before outputting.**

**Pitfall: Etsy Show Optional Fields are also non-negotiable.** Fill Clothing style, Sleeve length, Neckline, Closure, and Fabric pattern with exact Etsy dropdown values. Use Does Not Apply only for Graphic, Collar style, Holiday, Occasion, and Sustainability when they literally do not apply — never leave those rows blank.

**Pitfall: Depop Show Optional Fields are also non-negotiable.** Fill Source, Age, Style (exactly 3), Occasion (exactly 3), and Parcel Size. Omit Size Grouping for Regular sizing (it does not apply). Fill Material only from tag evidence. Never leave applicable optional rows blank.

**Does Not Apply stays in the listing, never on the form.** Keep writing it wherever the rules above call for it — Studio shows the row as answered so it is not chased again. Studio and the extension push a blank to the marketplace form instead of the phrase, because eBay renders "Does Not Apply" verbatim as an item specific.

**Pitfall: eBay Season has no "All Seasons" option.** Choose exactly one of Spring, Summer, Fall, or Winter from the garment (fabric, sleeve, type, title cues). For year-round items, put `"All Seasons"` under **Features** and still set Season to the primary wear season.

**Pitfall: JSON key names must exactly match the extension's `fieldNameMap` keys** (e.g., `unitQuantity` not `unit_quantity` or `qty`). See `references/vendoo-extension-architecture.md` for the full mapping and extension architecture.

## Formula Reference (NON-NEGOTIABLE)

### TITLE Formula
```
{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}
```
- EXACT order
- Max 80 characters
- `{SIZE}` is the `size` field verbatim — the title and the size field must never disagree
- Example: `Levi's 33 Y2K 511 Slim Shorts Black Denim`
- Men's bottoms example: `Levi's 34 Y2K 501 Straight Jeans Blue Denim`

### DESCRIPTION Formula (Line breaks MANDATORY)
```
{trendy vibe/style keyword sentence with period}

Flaws: {specific flaws}. See photos for details.

Measurements: {See photos OR specific measurements}
```
- Include the Flaws line only when the item has flaws. When there are none, leave the line out entirely — never write "none noted" or any other no-flaws filler.
- Keep the first line short and keyword-driven (vibe, decade/trend, fit, fabric) — not two separate sentences.
- Do not add Size, a full condition write-up, shipping speed, or bundle/discount lines — those are covered by marketplace fields and marketplace-level promos already.
- Do not count lint or wrinkles as flaws or mention them in the description. If those are the only visible issues, write `Flaws: none noted. See photos for details.` Continue to disclose actual damage such as stains, holes, or tears.
- NEVER include pricing details in the description: no prices, dollar amounts, comps, sold-listing counts, market or resale value, MSRP, discounts, offers, or notes about pricing confidence. Pricing belongs in the price field only.

### eBay Jackets and Coats: Required Outer Shell Material
Fill `ebay_specifics.category_specifics["Outer Shell Material"]` for jackets/coats (use the live schema key if supplied). Prefer readable shell composition or seller notes; otherwise make the best guess from photos, texture, construction, and reliable exact-model research. Choose a supported eBay value; never blank or Does Not Apply. Estimate the shell, not lining/down fill; never invent percentages or claim leather over faux leather without evidence. Material/fabricType does not replace this field. Flag estimates in the description: "Outer shell estimated as polyester; tag not visible." Preserve description structure; do not copy estimates into Depop's tag-only Material. Never ask the seller.

### Etsy Digital Download Description Formula
Use this override only when the Etsy listing is a digital product.

```
{adjective/color/style} {subject} {medium} printable with a {mood/theme} feel.

{style/type} wall art for {room/use case} and {palette/interior style} interiors.

Size: {included sizes and file types} will be included.

Instant download after purchase. No physical item will be shipped.
```
- Use this formula only for Etsy digital download listings.
- Replace the standard physical-item description block when the product is digital.
- Keep the size line focused on included file sizes and file types, such as `5x7 and 8x10 JPGs`.

### Etsy Digital Download Output Format
Use this final output structure only when the Etsy listing is a digital product.

```markdown
Title: {etsy title}

Description:
{etsy digital description}

Price: {price}

Materials: {comma-separated materials}

Tags: {comma-separated tags}

Who made: {who_made}
What is it: {what_is}
When made: {when_made}
```
- Return this as copy-pasteable plain text or markdown.
- Do not wrap Etsy digital download outputs in JSON.
- Keep the field order exactly as shown.

### PRICING Formula
```
Listing Price = Market comp × 1.35 (round to nearest dollar)
Ceiling       = median asking price of 3+ similar live listings; price at or
                below it unless the item is clearly better (NWT, condition, size)
Auto-accept   = Listing Price - $2
Minimum       = Listing Price - $4
```

### Seller History During Generation
- Use recent recorded sales from the seller's own inventory alongside current outside sold comps when Studio supplies seller history. Candidate matches share brand, full general category and condition when known; check item type, model, era, size and visible details before treating them as comparable. A category such as women's Tops can contain both tees and blouses.
- With at least five genuinely comparable recorded sales, use the seller's sold-price median to inform the market-comp baseline. The supplied medians summarize only the shown examples: use them only when those examples are comparable, never assume unseen matching records prove an exact-model price. Cross-check recent outside comps; do not blindly average conflicting cohorts or let old sales override current market evidence. With fewer than five, treat personal sales as examples only. Without three outside sold comps or five comparable personal sales, keep the conservative estimated baseline.
- Apply the PRICING Formula to the chosen baseline, preserve the current live asking ceiling, and always keep a price explicitly set by the seller. Cost and fees describe profitability; they do not prove that a buyer will pay more.
- Similar unsold inventory is a weak caution about demand and overpricing, not evidence of completed sales, a historical sell-through rate, or a reason to copy its asking prices.
- Historical titles can supply relevant vocabulary only when supported by this item's photos and seller notes. Never copy another item's brand, size, material, flaws, measurements, manufacturing date, or vintage claim. A sale does not prove its wording caused the sale. Keep sales evidence, cost, profit, and pricing reasoning out of the buyer-facing description.

### Seller Corrections and Observed Outcomes
- Studio supplies deliberate form edits captured before automatic normalization. Current-item corrections are seller evidence, including deliberate clears; honor them when consistent with the latest seller instructions and photos. Newer instructions and explicitly chosen prices take precedence. Related title/description edits are examples of editing choices only. Never transfer another item's facts, flaws, measurements or unsupported keywords, or infer a permanent preference from a single correction. Canonical and seller-customized formulas remain authoritative.
- A sale snapshot labeled `vendoo_first_observed_sold` freezes the remote listing when Studio first observes the dated sale. That may be after the actual sale: its timestamp does not verify the exact text at sale or prove that wording caused a sale. Legacy `current_listing_not_verified_at_sale` text is weaker evidence. Neither justifies a claim about winning keywords or conversion.
- `seller_measured` shipping contains an explicitly recorded packed weight and optional packed dimensions/postage. Use this item's measurement over estimates; similar items provide estimated shipping guidance only after checking item type, size and packaging. Never label a similar item's weight as measured for the new item. Postage depends on destination, service and date and is not a current shipping quote.
- `seller_reported` engagement counts belong to the supplied marketplace and dated reporting window. Empty counts mean unknown; zero is observed zero. Windows can overlap: never add them, infer lifetime totals, or invent conversion rates without a matching sales denominator. Sparse impressions/views/offers are weak context, not proof of demand, bad keywords or a pricing cause. Return reasons can prompt clearer evidence-based fit, measurements or flaw disclosure; never copy a returned item's flaws to the new item.
- Keep all correction examples, shipment economics, buyer-response counts and return history out of buyer-facing listing copy.

## Rules (VIOLATION = INCORRECT LISTING)

1. **NEVER invent brand names** — use brand only when readable from tags/logos or stated in seller notes; if unsupported, leave brand empty. Never ask the seller.
2. **Verifier confirmation REQUIRED for brand** and for size when a readable size tag exists
3. **Cross-check is MANDATORY** — extractor and verifier must agree when a readable size tag exists; otherwise use the measurement fallback rules
4. **If unresolved disagreement remains after measurement fallback, INFER from photos and initial seller notes** — prefer the stronger evidence and never ask clarifying questions
5. **📌 TITLE MUST MATCH FORMULA EXACTLY** — Brand Size Vibe Item Color Fit order
6. **📌 DESCRIPTION MUST MATCH THE APPLICABLE FORMULA EXACTLY** — use the physical-item template by default, or the Etsy Digital Download Description Formula for Etsy digital products
7. **Pricing MUST follow formula** (comp × 1.35, whole dollars only)
8. **NEVER put uncertainties in the description** — the description is buyer-facing. No hedges about what you couldn't verify or read, no "approximate", "estimated", "photo estimates", "uncertain" or "unclear" notes, no missing-tag or color doubts. Leave unsupported fields empty and mention open questions only in your reply to the seller
9. **Reference vendoo_listing_template.md BEFORE generating** — structure/order priority
10. **For Etsy digital downloads, use the Etsy Digital Download Description Formula** — do not use the physical-item description template
11. **For Etsy digital downloads, return the Etsy Digital Download Output Format** — do not output JSON
12. **Infer packaged shipping weight on every listing; do not ask the seller for it** — always populate both `weight_lb` and `weight_oz` with a reasonable packaged-shipping estimate supported by the item type, size, material, photos, seller notes, and research evidence (include typical packaging). Pounds may be `0`, but the combined weight must be greater than zero. Examples: light tee/tank ~6–10 oz; heavy graphic tee ~10–14 oz; hoodie/sweatshirt ~1 lb 0–8 oz; jeans/pants ~1–1.5 lb; light jacket ~1–2 lb. Prefer seller-provided scale weight when given. Studio supplies `package_dimensions_in` from the seller's saved package-dimensions default (initially `13x10x3`); do not ask the seller to confirm routine apparel shipping weight or package size. Infer unread tag size/material, department, when-made era, and other product facts from photos and initial seller notes when supportable; leave unsupported facts empty — never ask.
13. **Never ask clarifying questions** — generate from the photos and notes provided up front. The seller reviews the draft; do not pause to interview them.

## Pre-Output Verification (MANDATORY)

Before outputting ANY listing, verify:

- [ ] **Reference:** `references/vendoo_listing_template.md` consulted
- [ ] **Brand confirmed:** From visible tag/label
- [ ] **Size confirmed:** From visible tag/label or defensibly derived from measurements when no readable size tag exists
- [ ] **Cross-check passed:** Extractor and verifier agree, or measurement fallback applied and documented
- [ ] **Comps checked:** web_search used or baseline estimated
- [ ] **Title formula:** `{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}` followed EXACTLY
- [ ] **Title size matches the size field:** the same value, character for character (men's bottoms: `34`, not `34x34`)
- [ ] **Condition is a Vendoo general value and is not blank** (`Pre-Owned - Good`, `New With Tags/Box`, and the other values in `references/vendoo-dropdown-options.md`)
- [ ] **Title length:** 80 characters or less
- [ ] **Physical-item description lines:** if the item is physical, use the standard description formula and preserve its required line structure
- [ ] **Etsy digital description override:** if the item is a digital Etsy product, use the Etsy Digital Download Description Formula instead of the physical-item template
- [ ] **Etsy digital line 1:** descriptive vibe sentence with period
- [ ] **Etsy digital line 3:** decor/style sentence with period
- [ ] **Etsy digital line 5:** `Size: {included sizes and file types}`
- [ ] **Etsy digital line 7:** `Instant download after purchase. No physical item will be shipped.`
- [ ] **Etsy digital output format:** if the item is a digital Etsy product, return the Etsy Digital Download Output Format as copy-pasteable text or markdown, not JSON
- [ ] **Pricing:** Listing = comp×1.35, Auto-accept = -$2, Minimum = -$4
- [ ] **No uncertainties in description:** no hedges, estimates, or unverified-detail notes in buyer-facing copy; open questions go in the reply to the seller only
- [ ] **Local save completed:** If a local path was provided, `listing.json` was written for standard listings or `listing.md` was written for Etsy digital download listings and verified
- [ ] **Main fields populated:** title, description, price, brand, condition, size, primaryColor, secondaryColor (if visible), quantity, weight_lb, weight_oz, package_dimensions_in
- [ ] **Vendoo category is terminal:** use Vendoo General taxonomy (`Women > Women's Clothing > Tops` for women's shirts/T-shirts; `Men > Men's Clothing > Shirts > T-Shirts` for men's T-shirts), not marketplace-only aliases such as `Shirts & Blouses`
- [ ] **eBay specifics populated (ALL required):** type, department, sizeType, size, brand, fit, material, pattern, style, accents, features, neckline, closure, countryOfOrigin, fabricType, garmentCare, handmade, personalize, vintage, occasion, season, theme, unitQuantity, unitType
- [ ] **eBay jackets/coats:** Outer Shell Material populated separately from material/fabricType, with the best estimate when unverified; shell uncertainty documented in the description
- [ ] **eBay specifics key names match extension fieldNameMap:** JSON keys like `features`, `neckline`, `season`, `unitQuantity`, `unitType` must use exactly these names (not aliases like `feature` or `qty`) so the Vendoo extension can find and fill the corresponding form fields
- [ ] **Petite size normalized:** petite codes such as `PS` are mapped using exact platform-supported values instead of being flattened to plain small
- [ ] **Depop specifics populated:** source, age, style, type, fit, material, occasion, and size_grouping when supportable
- [ ] **Etsy specifics populated:** who_made, what_is, when_made, materials, tags
- [ ] **Poshmark specifics populated:** originalPrice (if known)
- [ ] **Depop specifics populated:** source, age, style (3 items)
- [ ] **All marketplace fields:** Reference `vendoo_listing_template.md` for complete field list

**⚠️ IF ANY BOX IS NOT CHECKED, DO NOT OUTPUT THE LISTING. FIX IT FIRST.**

### Marketplace-Specific Reminders

**eBay (Most Important):**
- Fill ALL Item Specifics for better search visibility
- Type, Department, Size, Size Type, Brand are required
- Features, Style, Theme boost discoverability

**Etsy (Required for listing):**
- who_made, what_is, when_made are MANDATORY
- `when_made` must be an exact current Etsy dropdown value from `vendoo-dropdown-options.json` (for example `2010 - 2019 (Recently)`), not `2010s` or `2010-2019`
- primaryColor must be present; secondaryColor when a second color is visible
- sku only when the seller gives one; never make one up
- Up to 13 tags, up to 10 materials
- Tags: letters, numbers, spaces, hyphens, and apostrophes only (no `#`, `/`, `&`, `%`, or other punctuation). Apostrophes and hyphens cannot start a tag.
- Vintage items (20+ years) need "When Made" set

**Poshmark:**
- Original price helps buyers see discount
- 3 Style Tags maximum
- NWT toggle for new items

**Depop:**
- NO title field (uses description)
- Exactly 3 Style tags required
- Source and Age are required
- Brand must be a Depop list brand (not a free-text Vendoo brand)
- Maximum 5 tags
- Parcel size must be an exact current Depop dropdown value: Extra extra small, Extra small, Small, Medium, Large, Extra large
- Parcel size must match the packaged weight you estimated: under 4oz Extra extra small, under 8oz Extra small, under 12oz Small, under 1lb Medium, under 2lb Large, otherwise Extra large

**Mercari:**
- Condition is required and uses Mercari labels (see `vendoo-dropdown-options.md`)
- shippingLabel must be `USPS Ground Advantage`

## Examples

### Example 1: Standard listing
**User sends:** Photos of Levi's shorts (front, tag, detail)

**Process:**
1. Extractor identifies: Levi's brand, 33x32 size, black denim, slim fit
2. Verifier confirms: Tag reads "Levi's 33W 32L"
3. Cross-check: Both agree ✓
4. Comp checker finds: Similar Levi's shorts sold $18-25
5. Pricing: $22 × 1.35 = $29.70 → $30 listing, $28 auto, $26 min
6. Synthesis generates JSON with exact formulas

**Output:** Vendoo-compatible JSON ready to copy/paste

### Example 2: Unclear brand
**User sends:** Photos but tag is blurry

**Action:** Infer from any readable logo, hardware, or seller notes. If still unsupported, leave brand empty, keep other fields, and note the unclear brand in the description. Do not ask.

### Example 3: Size conflict
**Extractor says:** "Size 32"
**Verifier says:** "Tag shows 33"

**Action:** Prefer the clearer tag reading (33), flag the conflict briefly in the description if helpful, and finish the listing. Do not ask.

## Etsy When Made Estimation

- Always populate Etsy `when_made` with an exact current dropdown option. An exact production date is not required to choose a date range.
- Prefer a known date from the seller, a tag, or research. Otherwise make an educated estimate using the brand, label design, construction, materials, graphics, and overall style. If those clues are inconclusive, choose the most plausible modern range from the offered options; never leave this required field blank merely because the date is unknown.
- Do not infer vintage status from retro styling, wear, or the word Y2K alone. Select a vintage range only when the available clues support that age. Never use Made To Order for an already-made resale item.
- Treat this as an exception to the rule against unsupported age claims: save the estimated dropdown range, explain briefly in the seller-facing reply that it is an estimate, and keep that uncertainty out of the buyer-facing description. Do not invent a precise production year or ask the seller to supply one.

## Resources

- **Mandatory reference:** `references/vendoo_listing_template.md`
- **Marketplace dropdowns (live scrape):** `references/vendoo-dropdown-options.md` — use exact condition/color/source strings per marketplace
- **Script:** `scripts/` (if any helper scripts exist)

## Notes

- Use web search for comps. Studio uses the web search of the model that writes the listing (ChatGPT, Cursor or MiMo), and falls back to Brave Search when that search fails, times out, or returns fewer than three sold or active listings and a key is saved.
- Standard listing JSON output must be copy/paste friendly with a `json` code block
- Etsy digital download output must be copy-pasteable plain text or markdown, not JSON
- When the user provides a local path, save the final standard listing as `listing.json` or the Etsy digital download listing as `listing.md` in the resolved photo folder
- Resolve file paths to their parent folder before saving so a single image path still leaves the final output with the product photos
- Measurements format: "Waist: 17" / "Rise: 9" / "Inseam: 7"
