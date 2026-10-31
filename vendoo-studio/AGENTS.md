# Anteroom: notes for agents

The root `AGENTS.md` has the rules and the working loop. This file covers how to
diagnose, reproduce and verify inside `vendoo-studio/`.

## Where to look when something is wrong

The data folder is `$VENDOO_STUDIO_DATA_DIR`. Without it, the folder is
`vendoo-studio/data/` in development or `~/Library/Application Support/Anteroom`
in the Mac app. The sandbox prints its own data folder.

| Symptom | Look at |
|---|---|
| Server error, failed request, crash | `GET /api/settings/error-logs` (recent warnings and errors), `GET /api/settings/app-logs?level=&since=&grep=` (server and extension log, survives restarts; file `<data>/logs/anteroom.jsonl`), or `anteroom logs --grep ...` |
| Mac app will not start | `<data>/logs/Anteroom.log` (stdout and stderr of the packaged app) |
| A Send, fill or marketplace job went wrong | `GET /api/jobs/{id}` (status and blocker fields), `/api/jobs/{id}/events`, `/api/jobs/{id}/fill-log` (field by field), `/api/jobs/{id}/logs` (both); files in `<data>/fill-logs/<job_id>.md` |
| Job slow or stuck | `/api/jobs/{id}/timing`, `/api/jobs/queue`; `services/job_watchdog.py` fails jobs that go silent |
| Generation slow | `GET /api/analytics/generation-timings` (seconds per stage) |
| Vendoo API call failed | `GET /api/settings/vendoo-api-logs` (the extension's Vendoo calls, headers and bodies redacted) |
| Setup state: provider, extension, data folder, sandbox | `GET /api/status` |

The `anteroom` CLI (`server/vendoo_studio/cli/`) wraps every route:
`anteroom commands` lists them, and `--base-url` picks the app (4319 for the
sandbox, 4318 for the real one). `anteroom mcp serve` exposes the same commands
as MCP tools. Commands that change a live listing need `--confirm`. Only use
those on the real app when the seller asked.

Read the seller's real app only to diagnose, and change nothing there. Reproduce
in the sandbox.

## Reproducing

- **Backend:** `server/tests/`, pytest with xdist. `conftest.py` gives every
  test an in-memory keyring and turns off the sourcing timer and category
  fills. To fake a model, install a provider like `FakeProvider` in
  `tests/test_listing_generate.py`, or set `ANTEROOM_SANDBOX=1` to get
  `SandboxProvider`. Hosted-mode tests mint Supabase sessions themselves (see
  `tests/test_seller_sessions.py`) and need Postgres (`ANTEROOM_TEST_DATABASE_URL`).
- **Frontend logic:** Vitest, files next to the code (`src/**/*.test.ts(x)`).
  Components render with `renderToStaticMarkup`; there is no DOM in Vitest.
  Anything needing a real browser belongs in Playwright.
- **The running app:** Playwright in `e2e/*.e2e.ts`, run with `npm run e2e`. The
  config starts its own sandbox (API 4329, UI 5184) and runs every test in a
  `desktop` (1440x900) and a `phone` (iPhone 15) project.
  - `e2e/fixtures.ts` has helpers to create a listing through the API and open
    it from the inventory in either layout.
  - Any uncaught page error fails the test.
  - Find selectors by role and accessible name, as a seller would see them. To
    see what is on screen, log `await page.locator("body").ariaSnapshot()` or
    take a screenshot.
  - Each test makes its own listings; do not rely on another test's changes.
- **By hand:** `./scripts/sandbox.sh`, then the UI at http://127.0.0.1:5174 or
  the CLI at `--base-url http://127.0.0.1:4319`. Use headless Chromium for
  screenshots (`npx playwright screenshot --device "iPhone 15" --wait-for-timeout 3000 <url> out.png`, or `--viewport-size "1440, 900"` for desktop).

## Code health checks

Four checks guard refactors. Each started with the problems already in the
code recorded, so it fails only on new ones. The records may only shrink: when
you fix a recorded problem, remove it from the record in the same PR, and never
add to a record to make a check pass.

| Check | Command | Record of existing problems |
|---|---|---|
| Types (basedpyright, standard mode) | `basedpyright` | `.basedpyright/baseline.json`; after fixing errors, `basedpyright --writebaseline` and check the diff only removes entries |
| Layers: routes, then services, then repositories, then models; a lower one never imports a higher one | `lint-imports` | `ignore_imports` in `pyproject.toml` |
| Unused backend functions, methods, classes and properties (vulture) | `python scripts/check-dead-code.py` | `server/dead_code_baseline.py`; `--write-baseline` after deleting code |
| Unused frontend files, exports and dependencies | `npm run knip` | `ignoreIssues` in `knip.json` |

- Code that something calls only by name (a handler method a library calls, a
  callback) goes in `server/dead_code_allowlist.py`, with a comment naming the
  caller.
- knip's record works file by file. A file listed there is not checked for that
  issue type at all. Shrink the list rather than adding to it.
- ORM fields use `Mapped[...] = mapped_column(...)`. Keep database nullability
  explicit: a Python type refactor must not silently change existing tables.
  Type checking blocks CI on new errors; its baseline may only shrink.
- The extension bridge and connection state live in `services/extension_connection.py`.
  Import that service from other services; `routes/extension.py` only registers
  the HTTP and WebSocket endpoints.

## Traps

- `config.py` reads `VENDOO_STUDIO_DATA_DIR` when it is imported. Set it before
  anything imports `vendoo_studio`, or code runs against the default data
  folder, and category resolution finds no category trees.
- The API rejects browser requests whose origin is not its own port or the web
  port. A second dev server needs both `VENDOO_STUDIO_PORT` and
  `VENDOO_STUDIO_WEB_PORT` set; `scripts/dev.sh` and `vite.config.ts` read
  them.
- Some backend tests read frontend and extension source files. After moving or
  renaming a `.ts`, `.tsx` or extension file, grep `server/tests` and run both
  suites.
- CI rejects two tracked modules whose names differ only by case (`Foo.tsx`
  beside `foo.ts`). Pick a different base name.
- Every model change needs an Alembic revision (root `AGENTS.md`, **Database
  schema**).
- Generation is slow in the sandbox as well (20 to 30 seconds), because every
  real pass runs and only the model is fake. Give browser tests that generate
  a long timeout instead of sleeping.

## Hosted and native sandboxes

`../sandbox.sh --hosted` runs the actual hosted API on temporary Postgres and
the cloud UI with two locally signed sample sellers. `npm run e2e:hosted`
checks desktop/phone hosted flows. The iPhone Debug app uses the same API;
`../anteroom-ios/test-sandbox.sh` runs its XCUITest on a Mac. See
`../docs/agent-sandboxes.md`. Never deploy `hosted_sandbox` or point a sandbox
at an existing seller database. Staging preparation creates no paid resources.
