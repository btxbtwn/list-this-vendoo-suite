---
name: list-this
description: Legacy compatibility wrapper for the older vendoo extension skill path. Use when an older resolver still lands here, but delegate to the top-level bundle list-this and list-this-direct skills instead of treating this copy as its own source of truth.
triggers:
  - "create listing"
  - "make a listing"
  - "list this"
  - "generate listing"
---

# List This (Legacy Compatibility Wrapper)

This directory is an older copy inside `vendoo-extension/`.

Do not treat it as an independent listing-policy source.

## Required references

Read and follow:

- `../../../skills/list-this/SKILL.md`
- `../../../skills/list-this-direct/SKILL.md`

Compatibility-only references:

- `../../../skills/list-this/references/vendoo_listing_template.md` only if the user explicitly needs the legacy extension JSON shape
- `../../../skills/list-this-direct/references/field_memory_delta_template.md` only if the run also returns field-memory updates

## Operating rules

- The current listing-generation source of truth lives in top-level `../../../skills/list-this/SKILL.md`.
- If the user wants browser automation or draft creation, hand off runtime execution to top-level `../../../skills/list-this-direct/SKILL.md`.
- The current direct flow follows the repo-relative runtime guidance in `../../../skills/list-this-direct/SKILL.md`: `python3 scripts/devtools_runtime.py bootstrap`, `python3 scripts/devtools_runtime.py launch-chrome` when needed, and `python3 scripts/devtools_runtime.py mcporter ...` for every Chrome DevTools MCP call.
- The direct flow keeps runtime, config, trace, and field-memory paths repo-relative under `../../../skills/list-this-direct/`; do not assume a home-directory `mcporter` config file or any checkout-specific absolute path.
- If the delegated direct flow cannot reach a controllable Chrome session through `python3 scripts/devtools_runtime.py mcporter`, stop and tell the user what is missing.
- Do not ask for Browser Relay, Chrome Relay, or a managed browser for the current direct flow.
- Do not use the vendoo extension for the current direct draft flow.
- Use the top-level `../../../skills/list-this/references/vendoo_listing_template.md` only as a legacy extension compatibility reference, not as a second policy source.

## Output behavior

- For listing copy or JSON only, behave exactly like top-level `skills/list-this/SKILL.md`.
- For live Vendoo draft creation, behave exactly like top-level `skills/list-this-direct/SKILL.md`, including stop-before-publish, MCP action trace, and `field_memory_delta` behavior.

## Why this file exists

This file stays here only so older paths inside the vendoo-extension project do not drift away from the top-level bundle skills.

If you need to change listing rules or runtime behavior, edit the top-level `skills/` folders instead of duplicating new logic here.
