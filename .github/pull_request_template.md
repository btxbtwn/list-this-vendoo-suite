## Summary

-

## Component

- [ ] Vendoo Listing Studio
- [ ] Chrome extension
- [ ] `list-this` skills
- [ ] CI / repo hygiene

## Checks

Match the CI jobs for the paths you touched:

- [ ] Studio frontend: `cd vendoo-studio && npm ci && npm run lint && npm test && npm run build`
- [ ] Studio backend: `cd vendoo-studio && ruff check server && python -m pytest -q -n auto`
- [ ] Extension: `node --check` on changed JS, `node --test 'vendoo-extension/tests/*.test.js'`, plus `python -m json.tool` on `manifest.json`

## Invariants

- [ ] Does not publish listings or skip human approval
- [ ] Does not commit API keys, photos, diagnostics, or private exports
- [ ] Studio still binds to `127.0.0.1`
