# Vendoo Extension Architecture & Field Matching

## Extension Location
`~/.hermes/vendoo-extension/` — Manifest V3, v0.1.0

## Architecture

```
popup.html → popup.js (user pastes JSON)
    → chrome.runtime.sendMessage({ type: 'START_EBAY', data })
    → background.js (service worker, routes messages)
    → content-scripts/vendoo.js (injected on Vendoo web tab)
    → fillEbayForm(data, 'EBAY')
    → fillDepopForm(data), fillMercariForm(data), etc.
```

**Key insight:** `background.js` line 190 forces `scriptFile = 'content-scripts/vendoo.js'` for ALL fills. The Vendoo web form is always used, even for eBay listings. The separate `ebay.js` content script only runs when navigating directly to `ebay.com/sl/` pages — it's for direct eBay fills, not Vendoo-mediated ones.

## Vendoo.js Field Matching (lines ~770-900)

The `fillEbayForm` function iterates `data.ebay_specifics` and matches JSON keys to form inputs via:

1. **fieldNameMap** — Maps JSON keys to eBay form field labels (e.g., `'unitQuantity' → 'Unit Quantity'`)
2. **fieldLabelPatterns** — Maps JSON keys to lowercase label search terms for fallback matching
3. **3 ID-matching patterns** (in order):
   - Pattern 1: Exact `afterLastDot` match (e.g., `"color"` → `"color"`)
   - Pattern 2: `categoryId_FieldName` suffix match (e.g., `"15687_unit quantity"` ends with `"_unit quantity"`)
   - Pattern 3: Full ID ends with `_fieldName` or `.fieldName`, regex with flexible whitespace
4. **Label-based fallback** — If no ID match, `findInputByLabelPatterns()` and `findInputByContext()` search by label/aria text

### Why multi-word fields were broken

eBay category-specific field IDs follow `listings.ebay.categorySpecifics.{categoryId}_{FieldName}` where FieldName can contain spaces (e.g., `15687_Unit Quantity`). The original code used `afterLastDot === fieldNameLower` which compared `"15687_unit quantity"` against `"unit quantity"` — a mismatch. The fix adds Pattern 2 (underscore suffix) and Pattern 3 (flexible regex) to handle these cases.

## Full fieldNameMap (33 entries)

```javascript
'type': 'Type', 'department': 'Department', 'size': 'Size',
'sizeType': 'Size Type', 'style': 'Style', 'brand': 'Brand',
'color': 'Color', 'material': 'Material', 'pattern': 'Pattern',
'fit': 'Fit', 'sleeveLength': 'Sleeve Length', 'sleeveType': 'Sleeve Type',
'neckline': 'Neckline', 'closure': 'Closure', 'accents': 'Accents',
'features': 'Features', 'theme': 'Theme', 'season': 'Season',
'occasion': 'Occasion', 'strapType': 'Strap Type',
'countryOfOrigin': 'Country of Origin', 'fabricType': 'Fabric Type',
'vintage': 'Vintage', 'handmade': 'Handmade', 'personalize': 'Personalize',
'garmentCare': 'Garment Care', 'unitQuantity': 'Unit Quantity',
'unitType': 'Unit Type', 'mpn': 'MPN', 'upc': 'UPC',
'character': 'Character', 'characterFamily': 'Character Family',
'performanceActivity': 'Performance Activity', 'yearManufactured': 'Year Manufactured',
'collarStyle': 'Collar Style', 'rise': 'Rise', 'inseam': 'Inseam',
'waist': 'Waist'
```

## ebay.js (Direct eBay Page Filler)

Located at `content-scripts/ebay.js`. Runs on `ebay.com/sl/*` pages. Has its own `fillCategorySpecifics()` function that uses the same `fieldNameMap` and `fieldLabelPatterns`, finding fields via:
1. **aria-label** matching
2. **Label element** text matching (for/input, sibling, parent traversal)
3. **ID pattern** matching (`categoryspecifics` + `_fieldName` with space/underscore dual-match)

Has its own `fillDropdownField(el, value, fieldName, isStrict, isMulti)` which mirrors vendoo.js's version. Multi-value fields pass `isMulti=true` to keep the dropdown open between selections.

## Pitfalls

- **UPC case**: `upc` must map to `'UPC'` (uppercase), not `'upc'`. The original had `'upc'` which would fail case-sensitive matches.
- **Space-in-name fields**: Any eBay field with a space in its name (Unit Quantity, Unit Type, Garment Care, Country of Origin, etc.) requires the underscore-suffix pattern. The old regex `[._]${fieldNameLower}$` doesn't match because the space is inside the field name, not a separator.
- **Space-vs-underscore in DOM IDs**: HTML IDs cannot contain spaces. The Vendoo form uses `listings.ebay.categorySpecifics.15687_Unit_Quantity` (underscore), but the `fieldNameMap` maps `unitQuantity` → `'Unit Quantity'` (with space). Pattern 2 matching now normalizes spaces to underscores as a fallback: `afterLastDot.endsWith('_' + fieldNameLower.replace(/\s+/g, '_'))`. ebay.js Strategy 3 uses the same dual-match approach.
- **Multi-value fields (isMulti)**: Fields like Features accept comma-separated values. The `fillDropdownField()` function keeps the dropdown open between selections when `isMulti=true`, preventing the second value from overwriting the first. Without this, only the last value in a comma-separated list survives.
- **Vendoo form vs eBay native**: The extension always fills via Vendoo's web form, never directly on eBay. If Vendoo changes their form IDs, the selector patterns need updating.
- **Chrome extension reload**: After editing extension files, reload at `chrome://extensions` → click reload button on the extension card.