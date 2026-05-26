# Etsy Digital Download Listings

This reference contains the standalone workflow for Etsy digital download products.

Use this when the user wants ONLY an Etsy digital download listing (no cross-platform JSON).

The main `list-this` SKILL.md already covers Etsy digital downloads in these sections:

- **Title Formula** (under Formula Reference): `{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}` for physical items, or the Etsy Digital Download Title Formula for digital items
- **Etsy Digital Download Description Formula**: Use for digital products only
- **Etsy Digital Download Output Format**: Copy-pasteable markdown, not JSON
- **Etsy Digital Download Exception section**: Return text not JSON

## Workflow for Etsy digital downloads specifically

1. **Extractor**: Review artwork preview — subject, medium, palette, mood, room/use case
2. **Digital Details Check**: Confirm it's a digital download. Ask for sizes/file types if missing.
3. **Comp Checker**: web_search for `site:etsy.com {subject} {style} digital download print price`
4. **Synthesis**: Use the Etsy Digital Output Format from main SKILL.md
5. **Local Save**: Write `listing.md` to the resolved folder

## Key differences from physical listings

| Aspect | Physical | Digital Download |
|--------|----------|-----------------|
| Output format | Vendoo-compatible JSON | Copy-pasteable text/markdown |
| Title formula | `{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}` | `{color/style} {subject} {medium} {room/use case} {decor type} {format}` |
| Description template | Physical item template | Digital download template |
| Pricing | `comp × 1.35` rounded to dollar | `comp × 1.35`, often ending in `.99` |
| Local save | `listing.json` | `listing.md` |
| Materials | Not applicable | digital download, JPG, PDF, PNG, etc. |
