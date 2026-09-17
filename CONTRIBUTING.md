# Contributing

This is a local-first monorepo: listing skills, Vendoo Listing Studio, and the Chrome extension. Product rules live in [`AGENTS.md`](AGENTS.md).

## Working on a change

1. Use a branch off `main`. Keep unrelated work out of the same PR.
2. Change one component unless the JSON listing contract requires a cross-cut.
3. Run the checks for the paths you touched (same commands as CI).
4. Open a pull request into `staging` with the template checklist completed.
5. After it merges, CI publishes **List This Studio Staging**. Test it there.
6. When staging looks good, open a pull request from `staging` into `main` to release.

## Staging

`staging` is the pre-release branch. Every push to it runs CI and publishes the staging Mac app to the [`studio-macos-staging`](https://github.com/btxbtwn/list-this-vendoo-suite/releases/tag/studio-macos-staging) pre-release. Pushes to `main` publish the production app to `studio-macos`.

The staging app is a separate app: **List This Studio Staging.app**, bundle ID `local.listthis.studio.staging`, data in `~/Library/Application Support/List This Studio Staging`. It updates itself only from the staging release and runs on port 4319 (production uses 4318), so both apps can be installed and running at the same time. API keys in Keychain are shared.

Each app installs its own copy of the Chrome extension in its data folder and points it at its own port. The staging copy is named **Vendoo Listing Studio Bridge (Staging)**. Load both folders unpacked in `chrome://extensions` once and leave both on: staging extension changes then reach only the staging app, and production keeps the extension it shipped with. Each app's folder path is in Settings → Connections.

Build one locally with `VENDOO_STUDIO_CHANNEL=staging ./scripts/package-macos-app.sh`; `publish-macos-release.sh` reads the channel from `build_info.json`.

If `staging` drifts from `main` (for example after a hotfix straight to `main`), merge `main` into `staging`.

## Checks

| Path | Command |
|---|---|
| `vendoo-studio/` frontend | `cd vendoo-studio && npm ci && npm run lint && npm test && npm run build` |
| `vendoo-studio/` backend | `cd vendoo-studio && ruff check server && python -m pytest -q -n auto` |
| `vendoo-extension/` | `node --check` on changed JS files; `node --test 'vendoo-extension/tests/*.test.js'`; `python -m json.tool vendoo-extension/manifest.json` |
| `skills/list-this/` | Confirm `SKILL.md` and reference JSON still parse |

CI on every pull request and push to `main` or `staging` runs these jobs and a secret scan. The macOS packaging workflow is separate and only publishes the Studio app.

## Invariants

- Do not publish listings. Stop at saved drafts.
- Do not add Redis, MongoDB, Celery, Docker, or cloud hosting unless that is the task.
- Bind Studio to `127.0.0.1`.
- Keep listing rules in `skills/`. Do not copy them into the extension.
