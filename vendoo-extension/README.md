# Vendoo Multi-Platform Lister - Chrome Extension MVP

Flow A: Paste JSON → Fill Vendoo first → Sequential fill for eBay/Poshmark/Mercari/Depop/Etsy (draft-only)

## Installation

1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" (toggle in top right)
3. Click "Load unpacked"
4. Select the repo's `vendoo-extension/` folder

## Usage

1. Click the extension icon in your toolbar
2. Paste your listing JSON (see format below)
3. Click "Fill Vendoo First"
4. Extension opens Vendoo's create listing page and fills the form
5. Review and save as draft manually
6. (Future) Continue to other platforms sequentially

## Companion Skills

This bundle keeps the canonical listing skills in the top-level `skills/` directory.

- `skills/list-this/` is the source of truth for listing copy and the JSON payload consumed by this extension.
- `skills/list-this-direct/` is the source of truth for the direct Vendoo draft workflow when you do not want to use the extension.
- `vendoo-extension/skills/list-this/` is only a compatibility wrapper for older extension-local skill paths.

Typical flow:

1. Use `skills/list-this/SKILL.md` to generate a Vendoo-ready listing JSON from product photos
2. Paste the JSON into the `vendoo-extension/` popup
3. Use the extension to fill Vendoo and marketplace sections

Reference material for the canonical skill lives in top-level `skills/list-this/references/vendoo_listing_template.md`.

## JSON Format

```json
{
  "title": "Vintage Denim Jacket",
  "description": "Classic Levi's denim jacket from the 90s. Great condition with minimal wear.",
  "price": 45.00,
  "brand": "Levi's",
  "size": "M",
  "condition": "Good",
  "category": "Clothing > Jackets",
  "color": "Blue",
  "sku": "DENIM-001",
  "originalPrice": 89.00,
  "quantity": 1,
  "tags": ["vintage", "denim", "levis", "90s"],
  "images": ["https://example.com/img1.jpg", "https://example.com/img2.jpg"]
}
```

### Supported Fields

| Field | Type | Description |
|-------|------|-------------|
| title | string | **Required** - Listing title |
| description | string | Item description |
| price | number | Listing price |
| brand | string | Brand name |
| size | string | Size (S/M/L/XL or numeric) |
| condition | string | new, like new, good, fair, poor |
| category | string | Category path |
| color | string | Primary color |
| sku | string | Your SKU/inventory ID |
| originalPrice | number | Original retail price (Poshmark) |
| quantity | number | Available quantity |
| tags | array | Keywords/tags (Etsy) |
| images | array | Image URLs (not yet implemented) |

## Platform Notes

### Vendoo (Primary)
- Fills most fields directly
- Category selection may need manual completion
- Images not yet implemented

### eBay
- Multi-step wizard flow
- Category requires tree navigation
- Rich text description

### Poshmark
- Brand autocomplete - may need manual selection
- Size buttons need clicking
- NWT checkbox for new items

### Mercari
- Modal-based category picker
- Condition dropdown
- Shipping options need manual selection

### Depop
- No separate title field (uses description)
- Color chips need clicking
- UK-focused sizing

### Etsy
- "Who made it" / "When made" dropdowns
- Tags are important for search
- Multiple listing types

## Development

### Selectors
Each content script has placeholder selectors that need updating based on actual site inspection:

```javascript
const SELECTORS = {
  title: 'input[name="title"]', // Update with real selector
  // ...
};
```

To find real selectors:
1. Open the platform's listing page
2. Right-click element → Inspect
3. Note the actual `id`, `name`, `data-testid`, or unique class
4. Update the selector in the content script

### Testing
1. Open browser DevTools console
2. Watch for `[platform]` prefixed logs
3. Check for fill errors
4. Use the popup's **Diagnose Page** button to download the current form structure plus live dropdown options from the page's current state when available
5. The diagnostic download now runs from the background worker, so the popup may close while the page is being inspected and the file should still download

### Icons
Add icon files:
- `icons/icon16.png` (16x16)
- `icons/icon48.png` (48x48)
- `icons/icon128.png` (128x128)

## TODO

- [ ] Update selectors with real values from each platform
- [ ] Implement image upload handling
- [ ] Add "Next Platform" button after Vendoo
- [ ] Auto-detect when user saves draft
- [ ] Category tree navigation
- [ ] Better error recovery
- [ ] Field mapping configuration UI
