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
| measurements | string | No | User-provided measurements in accepted format |
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
| Brand unclear | Tag unreadable in photos | Ask user for brand name |
| Size conflict | Extractor and Verifier disagree | Ask user to confirm size |
| Size tag missing | No readable size tag in photos | Fall back to measurement-derived approximate size and flag uncertainty |
| No comps found | Search returned no sold listings | Use estimated baseline; note uncertainty in description |
| Missing required photos | No tag/label photo | Request additional photos |
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
If unresolved conflict → Ask user.

If no readable size tag exists in the photos, skip strict size-tag agreement and derive an approximate size from the provided or visible measurements instead.

Measurement fallback rules:
- prefer the clearest waist-based sizing signal for bottoms and the clearest pit-to-pit or chest-based sizing signal for tops
- use the nearest standard marketplace size only when the measurements support a reasonable estimate
- if a standard size estimate would be too speculative, use the measurement size itself in the listing copy, such as `30 in waist` or `30x29`
- always state in the description that the size is approximate and derived from measurements because no readable size tag was visible

### Step 4: Comp Checker
Use `web_search` with query pattern: `"{brand} {item type} sold comps"`
Apply pricing formula from MEMORY.md.

### Step 5: Synthesis (You)
- Enforce title formula EXACTLY
- Enforce the applicable description formula EXACTLY
- Populate platform-specific fields
- For Etsy digital downloads, output a copy-pasteable text block instead of JSON
- Flag uncertainties in the description

### Step 6: Local Save (MANDATORY when path is provided)
- Resolve the save folder from the user's local path.
- If the path is a directory, use that directory.
- If the path is a file, use its parent directory.
- Write the final standard listing output to `<resolved folder>/listing.json`.
- Write the final Etsy digital download output to `<resolved folder>/listing.md`.
- Overwrite any existing file for that item so the folder keeps the latest source-of-truth draft.
- Verify the file exists and matches the output you returned before ending the task.
- If no local path was provided, return JSON for standard listings or copy-pasteable text for Etsy digital download listings in chat only.

**Petite Size Normalization (MANDATORY):**
- Keep the raw verified tag size in the listing copy when it is a petite code such as `PS`, `PM`, `PL`, or `PXL`.
- For Vendoo/general size mapping, prefer the actual petite code used by the platform dropdown, such as `PS` for petite small, instead of improvising `SP` or free-typing a custom alias.
- For marketplaces that split the size into a base size plus a grouping, map petite sizes as base size plus petite grouping. Example: tag `PS` maps to Depop `Size = S` and `Size grouping = Petite`, while eBay should keep `Size Type = Petites` and use the closest supported petite size code when available.
- When the exact petite mapping is unclear from the live platform options, stop and verify the options instead of flattening the size to plain `S`/`Small`.

**Measurement-Derived Size Fallback (MANDATORY when no size tag is visible):**
- When no readable size tag exists in the photos, derive size from measurements instead of blocking the listing.
- Use the most defensible size expression for the item type. For pants, prefer waist-first sizing such as `30` or `30x29` when supported by the measurements.
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
- **Size grouping** when the item is petite, tall, maternity, or otherwise not plain regular sizing

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
| **Pattern** | Solid, Striped, Floral, Tie-Dye, etc. |
| **Style** | Casual, Graphic Tee, etc. |
| **Accents** | Visible features: Graphic Print, Logo, Embroidered, Distressed, etc. |
| **Features** | Graphic Print, Preshrunk, Tagless, Pocket, etc. |
| **Neckline** | Crew Neck, V-Neck, Scoop Neck, Henley, etc. |
| **Closure** | Pullover, Button, Zip, Snap, etc. |
| **Country of Origin** | From tag: China, Haiti, Bangladesh, etc. |
| **Fabric Type** | Cotton, Denim, Polyester, Knit, etc. |
| **Garment Care** | Machine Washable (default) |
| **Handmade** | "No" (always) |
| **Personalize** | "No" (always) |
| **Vintage** | "No" (unless actually vintage) |
| **Occasion** | Casual, Workwear, Formal, etc. |
| **Season** | Spring, Summer, Fall, Winter, All Seasons |
| **Theme** | Space, Music, Sports, etc. when supportable |
| **Unit Quantity** | "1" (always for single items) |
| **Unit Type** | "Unit" (always) |
| **Rise** | If provided in measurements |
| **Inseam** | If provided in measurements |
| **Waist** | If provided in measurements |

**Pitfall: Skipping any of these fields causes the Vendoo eBay form to show them blank. Fill every row, even if the value is generic like "Crew Neck" or "All Seasons". The five most commonly skipped fields are Features, Neckline, Season, Unit Quantity, and Unit Type — always verify they are present in `ebay_specifics` before outputting.**

**Pitfall: JSON key names must exactly match the extension's `fieldNameMap` keys** (e.g., `unitQuantity` not `unit_quantity` or `qty`). See `references/vendoo-extension-architecture.md` for the full mapping and extension architecture.

## Formula Reference (NON-NEGOTIABLE)

### TITLE Formula
```
{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}
```
- EXACT order
- Max 80 characters
- Example: `Levi's 33 Y2K 511 Slim Shorts Black Denim`

### DESCRIPTION Formula (Line breaks MANDATORY)
```
{vibe sentence with period}

{fit/fabric sentence with period}

Size: {size}

Condition: {status}; Flaws: {none or specific}. See photos for details.

Measurements: {See photos OR specific measurements}

OFFERS WELCOME! Ships in 1-2 business days.

15% off bundles of 2+ items.
```

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
Auto-accept   = Listing Price - $2
Minimum       = Listing Price - $4
```

## Rules (VIOLATION = INCORRECT LISTING)

1. **NEVER invent brand names** — if unclear, ask user
2. **Verifier confirmation REQUIRED for brand** and for size when a readable size tag exists
3. **Cross-check is MANDATORY** — extractor and verifier must agree when a readable size tag exists; otherwise use the measurement fallback rules
4. **If unresolved disagreement remains after measurement fallback, ASK USER** — do not guess
5. **📌 TITLE MUST MATCH FORMULA EXACTLY** — Brand Size Vibe Item Color Fit order
6. **📌 DESCRIPTION MUST MATCH THE APPLICABLE FORMULA EXACTLY** — use the physical-item template by default, or the Etsy Digital Download Description Formula for Etsy digital products
7. **Pricing MUST follow formula** (comp × 1.35, whole dollars only)
8. **Flag uncertainties in the description** — be explicit about what you couldn't verify
9. **Reference vendoo_listing_template.md BEFORE generating** — structure/order priority
10. **For Etsy digital downloads, use the Etsy Digital Download Description Formula** — do not use the physical-item description template
11. **For Etsy digital downloads, return the Etsy Digital Download Output Format** — do not output JSON
12. **Weight and packaging MUST be included** — default to `weight_lb: 0`, `weight_oz: 8`, `package_dimensions_in: "13x10x3"` unless the user specifies otherwise

## Pre-Output Verification (MANDATORY)

Before outputting ANY listing, verify:

- [ ] **Reference:** `references/vendoo_listing_template.md` consulted
- [ ] **Brand confirmed:** From visible tag/label
- [ ] **Size confirmed:** From visible tag/label or defensibly derived from measurements when no readable size tag exists
- [ ] **Cross-check passed:** Extractor and verifier agree, or measurement fallback applied and documented
- [ ] **Comps checked:** web_search used or baseline estimated
- [ ] **Title formula:** `{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}` followed EXACTLY
- [ ] **Title length:** 80 characters or less
- [ ] **Physical-item description lines:** if the item is physical, use the standard description formula and preserve its required line structure
- [ ] **Etsy digital description override:** if the item is a digital Etsy product, use the Etsy Digital Download Description Formula instead of the physical-item template
- [ ] **Etsy digital line 1:** descriptive vibe sentence with period
- [ ] **Etsy digital line 3:** decor/style sentence with period
- [ ] **Etsy digital line 5:** `Size: {included sizes and file types}`
- [ ] **Etsy digital line 7:** `Instant download after purchase. No physical item will be shipped.`
- [ ] **Etsy digital output format:** if the item is a digital Etsy product, return the Etsy Digital Download Output Format as copy-pasteable text or markdown, not JSON
- [ ] **Pricing:** Listing = comp×1.35, Auto-accept = -$2, Minimum = -$4
- [ ] **Uncertainties documented:** Pricing sources and any uncertainties noted in description
- [ ] **Local save completed:** If a local path was provided, `listing.json` was written for standard listings or `listing.md` was written for Etsy digital download listings and verified
- [ ] **Main fields populated:** title, description, price, brand, condition, size, color, quantity, weight_lb, weight_oz, package_dimensions_in
- [ ] **eBay specifics populated (ALL required):** type, department, sizeType, size, brand, fit, material, pattern, style, accents, features, neckline, closure, countryOfOrigin, fabricType, garmentCare, handmade, personalize, vintage, occasion, season, theme, unitQuantity, unitType
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
- Up to 13 tags, up to 10 materials
- Vintage items (20+ years) need "When Made" set

**Poshmark:**
- Original price helps buyers see discount
- 3 Style Tags maximum
- NWT toggle for new items

**Depop:**
- NO title field (uses description)
- Exactly 3 Style tags required
- Source and Age help with search
- Parcel size affects shipping cost

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

**Action:** Ask user: "I can't read the brand on the tag. What brand is this?"

### Example 3: Size conflict
**Extractor says:** "Size 32"
**Verifier says:** "Tag shows 33"

**Action:** Ask user: "I see conflicting size info. The tag appears to say 33. Can you confirm?"

## Resources

- **Mandatory reference:** `references/vendoo_listing_template.md`
- **Script:** `scripts/` (if any helper scripts exist)

## Notes

- Use OpenClaw-native `web_search` for comps
- Standard listing JSON output must be copy/paste friendly with a `json` code block
- Etsy digital download output must be copy-pasteable plain text or markdown, not JSON
- When the user provides a local path, save the final standard listing as `listing.json` or the Etsy digital download listing as `listing.md` in the resolved photo folder
- Resolve file paths to their parent folder before saving so a single image path still leaves the final output with the product photos
- Measurements format: "Waist: 17" / "Rise: 9" / "Inseam: 7"
