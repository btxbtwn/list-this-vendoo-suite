# Contributing

This is a local-first monorepo: listing skills, Vendoo Listing Studio, and the Chrome extension. Product rules live in [`AGENTS.md`](AGENTS.md).

## Working on a change

1. Use a branch. Keep unrelated work out of the same PR.
2. Change one component unless the JSON listing contract requires a cross-cut.
3. Run the checks for the paths you touched (same commands as CI).
4. Open a pull request with the template checklist completed.

## Checks

| Path | Command |
|---|---|
| `vendoo-studio/` frontend | `cd vendoo-studio && npm ci && npm run build` |
| `vendoo-studio/` backend | `cd vendoo-studio && python -m pytest -q` |
| `vendoo-extension/` | `node --check` on changed JS files; `python -m json.tool vendoo-extension/manifest.json` |
| `skills/list-this/` | Confirm `SKILL.md` and reference JSON still parse |

CI on every pull request and push to `main` runs these jobs and a secret scan. The macOS packaging workflow is separate and only publishes the Studio app.

## Invariants

- Do not publish listings. Stop at saved drafts.
- Do not add Redis, MongoDB, Celery, Docker, or cloud hosting unless that is the task.
- Bind Studio to `127.0.0.1`.
- Keep listing rules in `skills/`. Do not copy them into the extension wrapper.
