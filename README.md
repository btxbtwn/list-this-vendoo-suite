# List This Vendoo Suite

Monorepo combining the `list-this` skill family, Vendoo Listing Studio, and the Vendoo Chrome extension. The skills generate marketplace-ready listings from product photos; Vendoo Studio provides a local web interface for chat-driven listing creation and extension automation; the extension fills six platforms (Vendoo, eBay, Poshmark, Mercari, Depop, Etsy) from a single JSON payload.

## Source of truth

- **`skills/`** — Canonical source of truth for listing rules, templates, research loops, and optimizer tooling.
- **`vendoo-extension/`** — Chrome extension that consumes listing JSON and fills marketplace forms.
- **`vendoo-studio/`** — Local web app (FastAPI + React) for MiMo-powered listing generation with automated Vendoo draft creation.
- **`VENDOO_STUDIO_SPEC.md`** — Product and architecture specification for Vendoo Listing Studio.
- `vendoo-extension/skills/list-this/` is a legacy compatibility wrapper only.

Anteroom, the photo background-removal app, is maintained in a separate sibling repository.

---

## Components

### Vendoo Listing Studio

Local web application at `http://127.0.0.1:4318` that provides:

- Product photo upload and drag-and-drop
- Chat interface with Xiaomi MiMo V2.5
- AI-powered listing generation and revisions
- Structured listing editor with marketplace-specific tabs
- Raw JSON editor with validation
- One-click **Send to Vendoo** automation
- Live progress tracking: photo upload, form filling, saving, and auditing
- Automatic draft creation — stops before publishing

See `vendoo-studio/README.md` for setup and `VENDOO_STUDIO_SPEC.md` for full specification.

### Skills

| Skill | Purpose |
|---|---|
| **`list-this`** | Generate a marketplace listing JSON from product photos. Produces title, description, pricing, and 100+ platform-specific fields (eBay category specifics, Etsy attributes, Depop style tags, Poshmark details). The output JSON is pasted into the extension. |


### Extension (`vendoo-extension/`)

Chrome MV3 extension. Two fill paths:

1. **Vendoo web form** (primary) — Injects `vendoo.js` into the Vendoo create-listing page and fills all marketplace sections sequentially from a single JSON paste.
2. **Direct platform pages** — Each platform has a content script (`ebay.js`, `poshmark.js`, `mercari.js`, `depop.js`, `etsy.js`) for direct form filling on the native listing page.

**Key features:**
- 100+ fields across 6 platforms filled from one JSON
- eBay category specifics: Features, Neckline, Season, Unit Quantity, Unit Type, and 25+ more
- Label-based field matching with ID-pattern fallback for multi-word form fields
- Multi-value comma-separated field support (e.g., "Cotton, Polyester, Spandex")
- Debug overlay showing fill success/failure per field
- Diagnostic page inspector for live form structure analysis

---

## Installation

1. Open Chrome → `chrome://extensions/`
2. Enable "Developer mode"
3. Click "Load unpacked"
4. Select the `vendoo-extension/` folder

---

## Usage

### Standard flow

1. Use `skills/list-this/SKILL.md` with an AI agent to generate listing JSON from product photos.
2. Open the extension popup, paste the JSON.
3. Click "Fill Vendoo First" — the extension opens Vendoo and fills every marketplace section.
4. Review and save as draft manually.



---

## JSON Format

The extension expects this structure. All `ebay_specifics` keys must use the exact names below so the extension's field matcher finds the corresponding form inputs.

```json
{
  "title": "Vintage Levi's Denim Jacket 90s",
  "description": "Classic Levi's denim jacket...",
  "price": 45.00,
  "brand": "Levi's",
  "size": "M",
  "condition": "Good",
  "category": "Clothing > Jackets",
  "color": "Blue",
  "sku": "DENIM-001",
  "quantity": 1,
  "weight_lb": 0,
  "weight_oz": 8,
  "package_dimensions_in": "13x10x3",
  "images": ["..."],
  "ebay_specifics": {
    "type": "T-Shirt",
    "department": "Men",
    "sizeType": "Regular",
    "size": "M",
    "brand": "Levi's",
    "fit": "Regular",
    "material": "Cotton",
    "pattern": "Solid",
    "style": "Basic",
    "accents": "",
    "features": "Comfortable",
    "neckline": "Crew Neck",
    "closure": "Pullover",
    "countryOfOrigin": "United States",
    "fabricType": "Jersey",
    "garmentCare": "Machine Wash",
    "handmade": "No",
    "personalize": "No",
    "vintage": "No",
    "occasion": "Casual",
    "season": "All Seasons",
    "theme": "",
    "unitQuantity": "1",
    "unitType": "Unit"
  },
  "depop_specifics": { ... },
  "etsy_specifics": { ... },
  "poshmark_specifics": { ... }
}
```

### Critical fields

These 5 are commonly skipped and must be present in every listing:

- **Features** — At least one descriptor (e.g., "Comfortable, Lightweight")
- **Neckline** — "Crew Neck", "V-Neck", etc.
- **Season** — "All Seasons", "Spring", "Summer", "Fall", "Winter"
- **Unit Quantity** — Almost always "1"
- **Unit Type** — Almost always "Unit"

---

## Platform notes

### Vendoo (primary)
- Fills general fields plus all marketplace-specific sections
- eBay category specifics: 30+ fields via label + ID pattern matching
- Multi-value fields (Features, Material) handled with comma-split + sequential selection

### eBay (direct)
- Full category specifics filling via `ebay.js` content script
- Multi-step wizard with lazy-loaded fields
- Condition via radio or dropdown

### Poshmark
- Brand autocomplete
- Size buttons
- NWT checkbox

### Mercari
- Modal-based category picker
- Condition dropdown

### Depop
- Color chips
- UK-focused sizing
- Style tags (3 required)

### Etsy
- "Who made it" / "When made" dropdowns
- 13 tags for search
- Materials section

---

## Development

### Extension architecture

```
popup.html → background.js (service worker)
                ↓
          vendoo.js (injected on vendoo.co)
                ↓
    fillGeneral → fillEbayForm → fillPoshmarkForm → ...
```

Each platform has a standalone content script for direct page fills:
- `content-scripts/vendoo.js` — main orchestrator (Vendoo web form)
- `content-scripts/ebay.js` — eBay native form
- `content-scripts/poshmark.js` — Poshmark native form
- `content-scripts/mercari.js` — Mercari native form
- `content-scripts/depop.js` — Depop native form
- `content-scripts/etsy.js` — Etsy native form

### Field matching

The extension uses a three-strategy field matcher to find form inputs:

1. **Exact match** on the ID's last segment (e.g., `color` → `color`)
2. **Underscore-prefix match** for category-prefixed IDs (`15687_features` → `Features`)
3. **Regex fallback** with whitespace-tolerant matching for multi-word fields (`15687_Unit Quantity` or `15687_Unit_Quantity`)

When ID matching fails, label-based matching scans the DOM for associated `<label>` elements.

### Adding a new field

1. Add the JSON key → form label mapping to `fieldNameMap` in `vendoo.js`
2. Add label search patterns to `fieldLabelPatterns` (for fallback matching)
3. If the field supports multiple values, ensure `fillDropdownField` receives `isMulti=true`

### Testing

1. Open DevTools console
2. Watch for `[EBAY]`, `[POSHMARK]`, etc. prefixed logs
3. Use the extension's **Diagnose Page** button to download live form structure
4. Check the debug overlay (bottom-left) for per-field fill results
