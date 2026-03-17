---
name: list-this
description: Create Vendoo-ready marketplace listings from product photos. Use ONLY when user sends photos AND asks for a listing. Follows exact title/description formulas and pricing rules from MEMORY.md.
triggers:
  - "create listing"
  - "make a listing"
  - "list this"
  - "generate listing"
---

# List This - Product Listing Workflow

## Purpose
Generate accurate, formula-compliant marketplace listings from product photos for Vendoo platform. Extracts visual details, applies strict formatting rules, and outputs Vendoo-compatible JSON.

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| photos | array | Yes | Product images (minimum: front, tag/label, any flaws) |
| measurements | string | No | User-provided measurements in accepted format |

## Input Requirements

**Required photos:**
- Front view of item
- Close-up of brand tag/label
- Any visible flaws or damage

**Optional photos:**
- Additional angles
- Detail shots
- Size tag close-up

## Returns

Returns a Vendoo-compatible JSON object containing:
- `title`: Formatted per `{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}` formula
- `description`: Multi-line string with exact line break structure
- `price`: Calculated per `comp × 1.35` formula
- `ebay_specifics`, `depop_specifics`, `etsy_specifics`: Platform-specific fields
- `internal_notes`: Uncertainties and pricing sources

### Sample Output Structure

**For the COMPLETE JSON template with all 100+ fields, see:**
`references/vendoo_listing_template.md` → Section "2. Extension JSON Structure"

**Quick Reference - Required Fields:**
```json
{
  "title": "Levi's 33 Y2K 511 Slim Shorts Black Denim",
  "description": "Y2K Levi's 511 shorts with raw hem in black denim wash.\n\nSlim fit in stretch denim, styled for spring and summer.\n\nSize: 33x32\n\nCondition: Good pre-owned; Flaws: no major flaws visible. See photos for details.\n\nMeasurements: See photos for measurements.\n\nOFFERS WELCOME! Ships in 1-2 business days.\n\n15% off bundles of 2+ items.",
  "price": 27,
  "cost": 8.00,
  "quantity": 1,
  "sku": "LEVIS-511-001",
  "brand": "Levi's",
  "condition": "Good",
  "primaryColor": "Black",
  "secondaryColor": "Blue",
  "department": "Men",
  "sizeType": "Regular",
  "size": "33",
  "size_us": "33",
  "tags": ["vintage", "levis", "511", "shorts", "denim"],
  "labels": ["To List"],
  "weight_lb": 0,
  "weight_oz": 12,
  "package_dimensions_in": "13x10x3",
  "internal_notes": "Sourced from Goodwill for $8. No major flaws.",
  "category_path": "Clothing, Shoes & Accessories > Men > Men's Clothing > Shorts",
  "zipCode": "70125",
  
  "ebay_specifics": {
    "type": "Shorts",
    "department": "Men",
    "sizeType": "Regular",
    "size": "33",
    "brand": "Levi's",
    "color": "Black",
    "material": "Denim",
    "fit": "Slim",
    "pattern": "Solid",
    "style": "511",
    "features": "Raw Hem",
    "sleeveType": "Set-In",
    "strapType": "N/A",
    "occasion": "Casual",
    "season": "Spring",
    "vintage": "No"
  },
  
  "etsy_specifics": {
    "who_made": "Another company or person",
    "what_is": "A finished product",
    "when_made": "2000-2009",
    "materials": ["Cotton", "Denim"],
    "tags": ["vintage", "levis", "shorts", "denim", "slim"],
    "category_specifics": {
      "sleeveLength": "Short Sleeve",
      "neckline": "Scoop Neck",
      "clothingStyle": "Casual",
      "fabric": "Denim",
      "pattern": "Solid"
    }
  },
  
  "poshmark_specifics": {
    "originalPrice": 68.00
  },
  
  "mercari_specifics": {
    "shippingMethod": "USPS Ground Advantage"
  },
  
  "depop_specifics": {
    "source": "Preloved",
    "age": "Modern",
    "style": ["Streetwear", "Vintage", "Y2K"],
    "type": ["Chino"],
    "fit": ["Slim"],
    "material": ["Cotton"],
    "occasion": ["Casual"],
    "size_grouping": ["Regular"]
  }
}
```

**Note:** The extension can fill 100+ fields across all platforms. Always reference the complete template in `references/vendoo_listing_template.md` for the full field list and allowed values.

## Side Effects

- **External network calls**: `web_search` used for comp research
- **Read-only operations**: Analyzes images, does not modify them
- **No persistent storage**: JSON output provided to user; not auto-saved
- **Stateless**: Each listing generation is independent

## Error Conditions

| Error | Cause | Resolution |
|-------|-------|------------|
| Brand unclear | Tag unreadable in photos | Ask user for brand name |
| Size conflict | Extractor and Verifier disagree | Ask user to confirm size |
| Size tag missing | No readable size tag in photos | Fall back to measurement-derived approximate size and flag uncertainty |
| No comps found | Search returned no sold listings | Use estimated baseline; note in internal_notes |
| Missing required photos | No tag/label photo | Request additional photos |
| Formula violation detected | Output doesn't match required format | Re-run synthesis step before outputting |

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
- always state in `internal_notes` that the size is approximate and derived from measurements because no readable size tag was visible
- never claim the size was tag-verified when it was measurement-derived

### Step 4: Comp Checker
Use `web_search` with query pattern: `"{brand} {item type} sold comps"`
Apply pricing formula from MEMORY.md.

### Step 5: Synthesis (You)
- Enforce title formula EXACTLY
- Enforce description formula EXACTLY
- Populate platform-specific fields
- Flag uncertainties in `internal_notes`

**Petite Size Normalization (MANDATORY):**
- Keep the raw verified tag size in the listing copy when it is a petite code such as `PS`, `PM`, `PL`, or `PXL`.
- For Vendoo/general size mapping, prefer the actual petite code used by the platform dropdown, such as `PS` for petite small, instead of improvising `SP` or free-typing a custom alias.
- For marketplaces that split the size into a base size plus a grouping, map petite sizes as base size plus petite grouping. Example: tag `PS` maps to Depop `Size = S` and `Size grouping = Petite`, while eBay should keep `Size Type = Petites` and use the closest supported petite size code when available.
- When the exact petite mapping is unclear from the live platform options, stop and verify the options instead of flattening the size to plain `S`/`Small`.

**Measurement-Derived Size Fallback (MANDATORY when no size tag is visible):**
- When no readable size tag exists in the photos, derive size from measurements instead of blocking the listing.
- Use the most defensible size expression for the item type. For pants, prefer waist-first sizing such as `30` or `30x29` when supported by the measurements.
- Use `sizeType = Regular` unless the measurements or garment styling clearly indicate Petite, Tall, Plus, or Maternity.
- Record the fallback clearly in `internal_notes` and in the description measurements line when helpful.
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

**eBay Fields (ALWAYS include these):**
- **Accents:** visible features like "Frayed", "Distressed", "Embroidered"
- **Closure:** Button, Zip, Snap, Elastic, etc.
- **Country of Origin:** from tag (China, Bangladesh, Vietnam, etc.)
- **Fabric Type:** Denim, Cotton, Polyester, etc.
- **Fit:** Slim, Regular, Relaxed, Wide Leg, etc.
- **Garment Care:** Machine Washable
- **Handmade:** "No" (always)
- **Pattern:** Solid, Striped, Floral, etc.
- **Front Type:** Flat Front, Pleated, etc. when supportable
- **Personalize:** "No" (always)
- **Occasion:** Casual, Workwear, Formal, etc. when supportable
- **Season:** Summer, Winter, Spring, Fall, All Seasons
- **Theme:** Classic, Preppy, etc. when supportable
- **Type:** Shorts, Jeans, etc.
- **Unit Type:** "Unit" (always)
- **Vintage:** "No" (always)
- **Rise:** if provided in measurements (e.g., "12 in")
- **Inseam:** if provided in measurements (e.g., "10 in")
- **Waist:** if provided in measurements (e.g., "34 in")

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
6. **📌 DESCRIPTION MUST MATCH FORMULA EXACTLY** — line breaks must be identical to template
7. **Pricing MUST follow formula** (comp × 1.35, whole dollars only)
8. **Flag uncertainties in internal_notes** — be explicit about what you couldn't verify
9. **Reference vendoo_listing_template.md BEFORE generating** — structure/order priority

## Pre-Output Verification (MANDATORY)

Before outputting ANY listing, verify:

- [ ] **Reference:** `references/vendoo_listing_template.md` consulted
- [ ] **Brand confirmed:** From visible tag/label
- [ ] **Size confirmed:** From visible tag/label or defensibly derived from measurements when no readable size tag exists
- [ ] **Cross-check passed:** Extractor and verifier agree, or measurement fallback applied and documented
- [ ] **Comps checked:** web_search used or baseline estimated
- [ ] **Title formula:** `{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}` followed EXACTLY
- [ ] **Title length:** 80 characters or less
- [ ] **Description line 1:** Vibe sentence with period
- [ ] **Description line 3:** Fit/fabric sentence with period
- [ ] **Description line 5:** `Size: {size}`
- [ ] **Description line 7:** `Condition: ...; Flaws: ...`
- [ ] **Description line 9:** `Measurements: ...`
- [ ] **Description line 11:** `OFFERS WELCOME! Ships in 1-2 business days.`
- [ ] **Description line 13:** `15% off bundles of 2+ items.`
- [ ] **Pricing:** Listing = comp×1.35, Auto-accept = -$2, Minimum = -$4
- [ ] **internal_notes:** Uncertainties and pricing sources documented
- [ ] **Main fields populated:** title, description, price, brand, condition, size, color, quantity
- [ ] **eBay specifics populated:** type, department, sizeType, size, fit, material, pattern, style, features, season, vintage
- [ ] **Petite size normalized:** petite codes such as `PS` are mapped using exact platform-supported values instead of being flattened to plain small
- [ ] **Depop specifics populated:** source, age, style, type, fit, material, occasion, and size_grouping when supportable
- [ ] **Etsy specifics populated:** who_made, what_is, when_made, materials, tags
- [ ] **Poshmark specifics populated:** originalPrice (if known)
- [ ] **Mercari specifics populated:** shippingMethod
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

**Mercari:**
- Shipping method selection required
- Smart pricing optional
- Offer to Likers feature available

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
- JSON output must be copy/paste friendly with `json` code block
- Save JSON as `listing.json` in photo folder when working locally
- Measurements format: "Waist: 17" / "Rise: 9" / "Inseam: 7"
- If the user wants live browser automation that creates and saves the Vendoo draft, hand the runtime flow to `../list-this-direct/SKILL.md` after generating the source-of-truth listing output.
