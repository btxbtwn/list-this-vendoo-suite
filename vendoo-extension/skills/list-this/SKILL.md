---
name: list-this
description: Legacy compatibility wrapper for the older vendoo extension skill path. Use when an older resolver still lands here, but delegate to the top-level bundle list-this skill instead of treating this copy as its own source of truth.
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

Compatibility-only reference:

- `../../../skills/list-this/references/vendoo_listing_template.md` only if the user explicitly needs the legacy extension JSON shape

## Operating rules

- The current listing-generation source of truth lives in top-level `../../../skills/list-this/SKILL.md`.
- Use the top-level `../../../skills/list-this/references/vendoo_listing_template.md` only as a legacy extension compatibility reference, not as a second policy source.

## Output behavior

- For listing copy or JSON only, behave exactly like top-level `skills/list-this/SKILL.md`.

## Why this file exists

This file stays here only so older paths inside the vendoo-extension project do not drift away from the top-level bundle skills.

If you need to change listing rules or runtime behavior, edit the top-level `skills/` folders instead of duplicating new logic here.
