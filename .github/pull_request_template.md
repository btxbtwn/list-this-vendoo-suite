## Summary

-

## Component

- [ ] Vendoo Listing Studio
- [ ] Chrome extension
- [ ] `list-this` skills
- [ ] Background Studio
- [ ] CI / repo hygiene

## Checks

Match the CI jobs for the paths you touched:

- [ ] Studio frontend: `cd vendoo-studio && npm ci && npm run build`
- [ ] Studio backend: `cd vendoo-studio && python -m pytest -q`
- [ ] Background Studio frontend: `cd background-studio/frontend && npm ci && npm test && npm run build`
- [ ] Background Studio backend: `cd background-studio && pytest -q backend/tests`
- [ ] Extension: `node --check` on changed JS, plus `python -m json.tool` on `manifest.json`

## Invariants

- [ ] Does not publish listings or skip human approval
- [ ] Does not commit API keys, photos, diagnostics, or private exports
- [ ] Studio / Background Studio still bind to `127.0.0.1`
