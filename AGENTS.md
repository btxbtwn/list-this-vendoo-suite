# Repository Guidelines

## Repository Overview

Monorepo combining the `list-this` skill family, the Vendoo Chrome extension, and Vendoo Listing Studio. The skills generate marketplace-ready listings from product photos; the extension fills six platforms from a single JSON payload; Vendoo Studio provides a local interface for listing creation and automation.

**Invariant:** Automation must never publish listings. Generation, category
resolution and draft creation run unattended and stop at a saved draft.
Publishing and delisting happen only when the seller asks for them: the
`vendoo-api/list` and `vendoo-api/delist` routes require the marketplaces to be
named explicitly and the call to carry `confirm`, and nothing in Studio calls
them on its own. No code path may publish everywhere by default, on a queue, on
a retry, or as a side effect of any other action.

## Source of Truth

- **`skills/`** — Canonical source for listing rules, templates, research loops, and optimizer tooling.
- **`VENDOO_STUDIO_SPEC.md`** — Product and architecture specification for Vendoo Listing Studio.
- Do not duplicate listing rules across components.

## Code Search (Semble)

**Cursor / coding agents:** Prefer `semble search` over broad grep+read when locating implementation. The index builds and caches on first use.

```bash
semble search "verified category selection" . --max-snippet-lines 10
semble search "schema probe category fields" . --top-k 10
semble search "category_path marketplace_categories" . --content all
semble find-related vendoo-studio/server/vendoo_studio/services/category_selection.py 10 .
```

Use `--content docs` for specs/skills prose, `--content config` for JSON/YAML/TOML, or `--content all` when categories/schemas may live in code *and* references (e.g. `skills/list-this/references/`, `VENDOO_STUDIO_SPEC.md`). Navigate straight to returned paths/lines; use grep only for exact string sweeps (error messages, renames). If `semble` is missing from `$PATH`, use `uvx --from "semble[mcp]" semble`.

**Studio listing agent:** Uses the in-app catalog index (`vendoo_studio.services.catalog_index`), not Cursor MCP. It materializes SQLite category leaves, observed schemas, skill-reference dropdown options, `skills/list-this` rule chunks, and extension fill helpers into local docs, searches them with Semble, and only accepts hits that verify. `GET /api/catalog/search?kind=category|schema|option|skill|fill|all` exposes the same search. Generation pulls relevant skill chunks; repair enriches gap dropdowns; fill-log reports include related helpers. It does not search listings, photos, or secrets.

## Engineering Principles

- Study how established products solve the problem before designing a solution. Adopt their proven patterns and conventions rather than inventing an approach from scratch.
- Do not preserve backward compatibility in code. Remove obsolete paths instead of adding compatibility layers or fallbacks. This does not extend to the database: Studio runs on more than one machine, and a schema change has to reach a database nobody can afford to delete. Schema changes go through an Alembic revision (see **Database schema** below).
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

## Repository Structure

- **`skills/`** — Agent skills for listing generation (`list-this`).
- **`vendoo-extension/`** — Chrome MV3 extension that consumes listing JSON and fills marketplace forms. Content scripts under `content-scripts/` handle Vendoo, eBay, Poshmark, Mercari, Depop, and Etsy. `background.js` routes messages and loads the worker modules in `background/`; `popup.html`/`popup.js` provide the manual paste-and-fill UI. Node unit tests live in `tests/`.
- **`vendoo-studio/`** — React + TypeScript frontend (`src/`) and FastAPI Python backend (`server/vendoo_studio/`). Frontend API clients live under `src/api/`. Backend routes live under `server/vendoo_studio/routes/`; domain behavior lives in `server/vendoo_studio/services/` and `server/vendoo_studio/repositories/`.

## Development Commands

- **Studio setup:** `./setup.sh` (from the repo root) or `cd vendoo-studio && ./scripts/setup.sh`
- **Studio start:** `./start.sh` or `cd vendoo-studio && ./scripts/dev.sh`
- **Studio doctor:** `cd vendoo-studio && ./scripts/doctor.sh`
- **Studio schema check:** `cd vendoo-studio && ./scripts/check-db-schema.sh [db]`
- **Studio restore:** `cd vendoo-studio && ./scripts/restore-db.sh <snapshot.db>` (quit Studio first)
- **Studio new migration:** `cd vendoo-studio && .venv/bin/alembic revision --autogenerate -m "..."`
- **Studio frontend build:** `cd vendoo-studio && npm run build`
- **Studio frontend lint and tests:** `cd vendoo-studio && npm run lint && npm test`
- **Studio backend lint and tests:** `cd vendoo-studio && ruff check server && python -m pytest -q -n auto` (install with `pip install -e ".[dev]"`)
- **Extension tests:** `node --test 'vendoo-extension/tests/*.test.js'`
- **Extension:** **Connect Chrome** opens everyday Chrome. Load unpacked from `vendoo-extension/` in `chrome://extensions/` with Developer mode enabled.

## Coding Conventions

- Follow the established style within each component. Do not refactor unrelated files.
- Keep skill instructions in canonical `SKILL.md` files; keep browser-specific logic in the corresponding extension content script.
- Keep frontend API calls under `vendoo-studio/src/api/`; keep backend routes thin and place domain behavior in services and repositories.
- Maintain the JSON listing contract across skills, Studio, and the extension. The extension expects the structure documented in `README.md`.

## Database schema

- Studio's SQLite schema is owned by Alembic. Revisions live in `vendoo-studio/server/vendoo_studio/migrations/versions/` and ship inside the Mac app.
- **Every model change needs a revision.** Editing a model without one leaves every existing database short of the change, and the mismatch only surfaces later as a query error. Generate one with `alembic revision --autogenerate` and read what it produced before committing it.
- Revisions are forward-only in practice. Test a new one against a copy of a database made by the previous release, not only against a fresh one.
- `init_db` migrates on startup, snapshots first, and refuses to open a database stamped with a revision this build does not know, which is what stops an older build from writing into a newer database.
- `BACKFILLED_COLUMNS` in `database.py` exists only to carry databases from before migrations were introduced. Do not add to it; write a revision instead.
- Snapshots are written by `services/backups.py` to `<data>/backups/`, before updates and migrations and on a timer. Never copy `vendoo_studio.db` as a file to back it up: use `VACUUM INTO`, or the `-wal` beside it makes the copy inconsistent.

## Verification

CI (`.github/workflows/ci.yml`) runs these on every pull request and push to `main`. Run the same commands locally for the paths you touched.

- **Studio frontend:** `cd vendoo-studio && npm ci && npm run lint && npm test && npm run build`
- **Studio backend:** `cd vendoo-studio && ruff check server && python -m pytest -q -n auto` (install with `pip install -e ".[dev]"`)
- **Extension:** `node --check` on changed JS files, `node --test 'vendoo-extension/tests/*.test.js'`, and `python -m json.tool vendoo-extension/manifest.json`. Then reload the unpacked extension and test affected marketplace flows manually. Use platform-prefixed console logs (`[EBAY]`, `[POSHMARK]`, etc.), the **Diagnose Page** button for live form structure, and the debug overlay (bottom-left) for per-field fill results.
- **Skills:** Confirm `skills/list-this/SKILL.md` exists and `python -m json.tool skills/list-this/references/vendoo-dropdown-options.json` succeeds.
- **Secrets:** Do not track `.env`, key files, photos, or private exports. CI scans the working tree with gitleaks.

**Pull requests:** After creating or updating a PR, always check CI (`gh pr checks`) and fix failures before considering the work done. Do not stop while required checks are pending or red. PRs that change `vendoo-studio/` must bump the Studio patch version once (`cd vendoo-studio && ./scripts/bump-version.sh`) so the status-bar version advances, and add a `CHANGELOG.md` entry for that version — one `## <version> — <YYYY-MM-DD>` heading at the top of the file with a bullet in the seller's words. The app reads that file (Settings → General → About → What's new). CI's **Changelog** job (`vendoo-studio/scripts/check-changelog.py`) fails when the newest entry does not match `VERSION`, when that entry has no notes, or when a PR bumps the version without adding a section for it; run it locally with `python vendoo-studio/scripts/check-changelog.py`.

## Security and Product Invariants

- Never commit API keys, OAuth credentials, listing photos, generated diagnostics, or private exports.
- API keys remain in macOS Keychain and never enter SQLite, logs, frontend responses, or extension messages.
- Bind Studio only to `127.0.0.1`. Optional private Tailscale Serve (Settings → Connections) may proxy Tailnet HTTPS to that loopback port; never Funnel and never bind to `0.0.0.0`.
- Require human approval before sending to Vendoo.
- Allow one automation job at a time. Additional approved Sends may wait in a FIFO queue and start when the current job finishes, fails, or is cancelled.
- Do not introduce Redis, MongoDB, Celery, Docker, cloud hosting, or provider substitutions unless explicitly requested.
