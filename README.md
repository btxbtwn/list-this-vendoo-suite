# List This Vendoo Suite

This bundle keeps the `list-this` skill family and the Vendoo Chrome extension in one reviewable source tree.

## Source of truth

- Top-level `skills/` is the canonical source of truth for listing rules, runtime guidance, templates, research loops, and optimizer tooling.
- `vendoo-extension/` is the browser extension that consumes the listing output from those skills.
- `vendoo-extension/skills/list-this/` remains only as a legacy compatibility wrapper for older extension-local skill paths.

## Included components

- `skills/list-this/` — canonical listing copy and extension JSON guidance
- `skills/list-this-direct/` — canonical direct Vendoo draft workflow without the extension
- `skills/list-this-researcher/` — post-run research and learning support
- `skills/skill-optimizer/` — eval-driven skill tuning tools and example packs
- `vendoo-extension/` — Chrome extension for the manual JSON-paste flow

## Typical flows

1. Use `skills/list-this/SKILL.md` to generate listing copy and the extension JSON payload.
2. Choose one execution path:
   - paste the JSON into `vendoo-extension/` for the extension-assisted flow, or
   - use `skills/list-this-direct/SKILL.md` for direct browser automation without the extension.
3. Use `skills/list-this-researcher/` and `skills/skill-optimizer/` to learn from runs and tighten the bundle over time.
