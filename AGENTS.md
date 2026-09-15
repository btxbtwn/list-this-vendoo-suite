# Repository Guidelines

## Repository Overview

Monorepo combining the `list-this` skill family, the Vendoo Chrome extension, and Vendoo Listing Studio. The skills generate marketplace-ready listings from product photos; the extension fills six platforms from a single JSON payload; Vendoo Studio provides a local interface for listing creation and automation.

**Invariant:** Automation must never publish listings. Stop at saved drafts and require human approval before sending.

## Source of Truth

- **`skills/`** — Canonical source for listing rules, templates, research loops, and optimizer tooling.
- **`vendoo-extension/skills/list-this/`** — Legacy compatibility wrapper only. Do not use as the source for listing rules.
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
- Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

## Repository Structure

- **`skills/`** — Agent skills for listing generation (`list-this`).
- **`vendoo-extension/`** — Chrome MV3 extension that consumes listing JSON and fills marketplace forms. Content scripts under `content-scripts/` handle Vendoo, eBay, Poshmark, Mercari, Depop, and Etsy. `background.js` routes messages; `popup.html`/`popup.js` provide the manual paste-and-fill UI.
- **`vendoo-studio/`** — React + TypeScript frontend (`src/`) and FastAPI Python backend (`server/vendoo_studio/`). Frontend API clients live under `src/api/`. Backend routes live under `server/vendoo_studio/routes/`; domain behavior lives in `server/vendoo_studio/services/` and `server/vendoo_studio/repositories/`.
- **`background-studio/`** — Standalone local photo background-removal app. Keep it separate from `vendoo-studio/`.

## Development Commands

- **Studio setup:** `./setup.sh` (from the repo root) or `cd vendoo-studio && ./scripts/setup.sh`
- **Studio start:** `./start.sh` or `cd vendoo-studio && ./scripts/dev.sh`
- **Studio doctor:** `cd vendoo-studio && ./scripts/doctor.sh`
- **Studio frontend build:** `cd vendoo-studio && npm run build`
- **Studio backend tests:** `cd vendoo-studio && python -m pytest -q` (install with `pip install -e ".[dev]"`)
- **Background Studio setup:** `cd background-studio && ./scripts/setup.sh`
- **Background Studio start:** `cd background-studio && ./scripts/dev.sh`
- **Extension:** **Connect Chrome** opens everyday Chrome. Load unpacked from `vendoo-extension/` in `chrome://extensions/` with Developer mode enabled.

## Coding Conventions

- Follow the established style within each component. Do not refactor unrelated files.
- Keep skill instructions in canonical `SKILL.md` files; keep browser-specific logic in the corresponding extension content script.
- Keep frontend API calls under `vendoo-studio/src/api/`; keep backend routes thin and place domain behavior in services and repositories.
- Maintain the JSON listing contract across skills, Studio, and the extension. The extension expects the structure documented in `README.md`.

## Verification

CI (`.github/workflows/ci.yml`) runs these on every pull request and push to `main`. Run the same commands locally for the paths you touched.

- **Studio frontend:** `cd vendoo-studio && npm ci && npm run build`
- **Studio backend:** `cd vendoo-studio && python -m pytest -q` (install with `pip install -e ".[dev]"`)
- **Extension:** `node --check` on changed JS files and `python -m json.tool vendoo-extension/manifest.json`. Then reload the unpacked extension and test affected marketplace flows manually. Use platform-prefixed console logs (`[EBAY]`, `[POSHMARK]`, etc.), the **Diagnose Page** button for live form structure, and the debug overlay (bottom-left) for per-field fill results.
- **Skills:** Confirm `skills/list-this/SKILL.md` exists and `python -m json.tool skills/list-this/references/vendoo-dropdown-options.json` succeeds.
- **Secrets:** Do not track `.env`, key files, photos, or private exports. CI scans the working tree with gitleaks.

## Security and Product Invariants

- Never commit API keys, OAuth credentials, listing photos, generated diagnostics, or private exports.
- API keys remain in macOS Keychain and never enter SQLite, logs, frontend responses, or extension messages.
- Bind Studio only to `127.0.0.1`. Optional private Tailscale Serve (Settings → Connections) may proxy Tailnet HTTPS to that loopback port; never Funnel and never bind to `0.0.0.0`.
- Require human approval before sending to Vendoo.
- Allow one automation job at a time. Additional approved Sends may wait in a FIFO queue and start when the current job finishes, fails, or is cancelled.
- Do not introduce Redis, MongoDB, Celery, Docker, cloud hosting, or provider substitutions unless explicitly requested.
