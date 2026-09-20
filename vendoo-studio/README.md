# Vendoo Listing Studio

Local Mac app for generating Vendoo marketplace listings with ChatGPT or Xiaomi MiMo, then filling a draft in Chrome. It never publishes.

## Share a Mac app

Build a self-contained `.app`. Recipients do not need Python, Node, or this git repo.

```bash
cd vendoo-studio
./scripts/setup.sh
source .venv/bin/activate
pip install -e ".[package]"
./scripts/package-macos-app.sh
```

That writes `vendoo-studio/release/List This Studio.app` and `vendoo-studio/release/List-This-Studio-macos.zip`. The zip also includes **How to Open.txt**.

Publish the zip as the rolling GitHub release (`studio-macos`):

```bash
./scripts/publish-macos-release.sh
```

Pushes to `main` that touch Studio, the extension, or listing skills also build and replace that release through `.github/workflows/studio-macos.yml`.

The packaged app does not git-pull. **Check for updates** compares the stamped build SHA against the GitHub release and, if newer, downloads the zip, replaces the `.app`, and relaunches. All Studio data stays in `~/Library/Application Support/List This Studio` (listings, photos, drafts, hidden fields, settings, fill logs, logs). API keys remain in macOS Keychain. Settings → About shows the folder path.

The recipient:

1. Unzips the archive and moves **List This Studio** into Applications.
2. Control-clicks the app and chooses **Open** the first time (ad-hoc signed, not notarized).
3. Signs in with ChatGPT or enters a Xiaomi MiMo API key in Settings.
4. Clicks **Connect Chrome**. Studio opens Vendoo in everyday Chrome and copies the listing extension into a Studio-managed folder. Load that unpacked folder once from Settings → Connections (`chrome://extensions/` → Developer mode → Load unpacked).

They need macOS 13+ and Google Chrome.

## Quick start (this repo)

From the repository root:

```bash
./setup.sh
./start.sh
```

Or from this directory:

```bash
./scripts/setup.sh
./scripts/dev.sh
```

`setup.sh` creates `.venv`, installs Python and Node packages, and builds the frontend. `dev.sh` starts the API at http://127.0.0.1:4318 and the Vite app at http://127.0.0.1:5173. `./scripts/doctor.sh` checks that the machine is ready.

Requirements: Python 3.12+, Node.js 20+, Google Chrome.

Then:

1. Open **Settings**.
2. Sign in with ChatGPT, or save a Xiaomi MiMo API key and test it.
3. Click **Connect Chrome**, then load unpacked from the folder shown in Settings → Connections so Chrome stays on Studio's copy.
4. Sign in to Vendoo. The status bar shows **Extension connected**.

## Workflow

1. **Create a listing**.
2. **Upload photos** by dragging them into the photo tray.
3. Optionally add notes (cost, flaws, measurements).
4. Chat to analyze the photos and generate a listing.
5. Review the listing in the right panel.
6. Click **Send to Vendoo**. Studio opens a background Vendoo tab in everyday Chrome, fills and saves a draft, closes the tab, and stops before publishing.
7. Open the Vendoo draft to review and publish manually.

### Editing something that is already listed

Studio writes the Vendoo **form**. Vendoo carries a form change onto a live
marketplace listing only when the listing is taken down and posted again, so
after **Update Vendoo** the buyer still sees the old copy until you delist and
relist in Vendoo (the ⋮ menu beside Vendoo Form → **Delist Item**, which takes
the item off every marketplace at once, then list it again).

Studio labels every step of that rather than leaving it to memory. A blue
**unsent** chip says the edit has not reached the Vendoo form yet — press
**Update Vendoo** and it clears. After that the listing wears an amber
**relist** badge in the sidebar, the editor shows which marketplaces are behind,
and **Filters → Unsent edits / Needs relist** collect each set. The badge survives the
delist itself — in that middle window Vendoo reports the item as a draft, because
it is live nowhere, and the banner switches to "list it again to finish". It
clears itself once Vendoo reports a listing date newer than Studio's last write,
or on **Done** in the banner for a relist Studio cannot see.

## Architecture

```
vendoo-studio/           Local web app (FastAPI + React)
├── server/              Python backend
│   └── vendoo_studio/
│       ├── main.py      FastAPI application
│       ├── config.py    Settings and paths
│       ├── database.py  SQLite setup
│       ├── models/      Pydantic schemas, SQLAlchemy models, protocol
│       ├── routes/      API endpoints
│       ├── services/    Keychain, photos, extension gateway
│       ├── repositories/ Database queries
│       └── providers/   ChatGPT and Xiaomi MiMo clients
├── src/                 React frontend
│   ├── app/             Main app and routing
│   ├── api/             API client
│   ├── components/      UI components
│   └── styles/          CSS
└── data/                SQLite database and photo storage (dev only)
```

## Security

- Binds only to `127.0.0.1` (localhost).
- Optional **Settings → Connections → Tailscale HTTPS** uses private Tailscale Serve to proxy HTTPS to that loopback port. Funnel stays off; only devices on your Tailnet can open the link. Same Studio process and data as on the Mac — not a second install.
- API keys and ChatGPT tokens live in macOS Keychain, never in SQLite, browser storage, or logs.
- Never sent to the React frontend or Chrome extension.
- Photos are served only through the Studio origin (`GET /api/photos/{id}`).
- No publication automation — only draft saving.

## Development

```bash
./scripts/dev.sh     # backend + frontend together
./scripts/doctor.sh  # check Python, Node, Chrome, ports
cd vendoo-studio && npm run build
PYTHONPATH=server .venv/bin/python -m pytest -q server/tests
```

Set `VENDOO_STUDIO_DEV=1` if you start the backend yourself and want auto-reload.

The extension connects to `ws://127.0.0.1:4318/api/extension/ws`. **Connect Chrome** opens Vendoo in everyday Chrome and reloads Studio's listing extension. Load unpacked from the folder shown in Settings → Connections (`data/vendoo-extension/` in development).

## Database

SQLite at `data/vendoo_studio.db` in development, or `~/Library/Application Support/List This Studio` in the packaged app. Replacing the `.app` does not touch this folder. Tables:

- `conversations` — listing sessions
- `messages` — chat history
- `photos` — uploaded images
- `listings` — current listing state
- `listing_revisions` — edit history
- `jobs` — automation jobs
- `job_events` — per-job event log
- `category_trees` / `category_tree_nodes` — full General/eBay/Poshmark/Mercari/Depop/Etsy category trees

The same data folder also holds `photos/`, `fill-logs/`, `settings.json` (marketplaces, hidden fields, UI prefs), `pairing_token.txt`, `catalog-index/`, `vendoo-extension/`, `backups/`, and `logs/`.

### Backups

Studio snapshots the database to `backups/` on startup, every six hours, and before any update or schema migration. Snapshots are written with `VACUUM INTO`, so they are consistent while Studio keeps running, and each one is checked with `PRAGMA integrity_check` before it is kept. Recent snapshots are kept for a day, then one per day for a month, and the newest three are never discarded.

**Copy them off this machine.** Snapshots in `backups/` die with the disk they sit on. Set a backup folder in **Settings → Backups** — an external drive, a synced folder, or a network share — and every snapshot goes there too, along with your photos. Photos are copied incrementally and are never deleted from the backup folder when they are deleted in Studio, because that is the copy you want when the deletion was a mistake. The same thing over the API:

```bash
curl -X PUT http://127.0.0.1:4318/api/backups/folder \
  -H 'Content-Type: application/json' \
  -d '{"folder": "/Volumes/Backup/List This Studio"}'
```

Do not point that at the live database, and do not put `data/` itself inside Dropbox or iCloud: a sync daemon copying an open SQLite file mid-write produces snapshots that will not open.

| | |
|---|---|
| List snapshots | `GET /api/backups` |
| Snapshot now | `POST /api/backups` |
| Check a database | `./scripts/check-db-schema.sh [db]` |
| Restore one | `./scripts/restore-db.sh <snapshot.db>` |

Restoring quits nothing for you — close Studio first. The current database is snapshotted before it is replaced, so restoring the wrong copy is itself undoable.

### Schema changes

The schema is owned by Alembic; revisions live in `server/vendoo_studio/migrations/versions/`. On startup Studio migrates to the newest revision, snapshotting first, and refuses to open a database stamped with a revision it does not recognise — that is what stops an older build from writing into a database a newer one created.

A database from before migrations existed is brought up to the current schema, checked for anything still missing, and only then recorded as current.

`test_the_models_match_the_migrations` compares what the migrations build against what the models declare, so a model change without a revision fails in CI rather than on someone else's machine. Adding a column to a model requires a revision:

```bash
.venv/bin/alembic revision --autogenerate -m "add whatever"
```


Category leaves, observed schemas, skill dropdown options, listing-rule chunks, and extension fill helpers are materialized under `catalog-index/` in the same data directory and searched with Semble (`GET /api/catalog/search`). First launch may download the local embedding model once.

### Category tree seed

A checked-in seed lives at `data/category-trees-seed.json.gz` (those two tables only). Studio imports it automatically on launch whenever any of the six marketplace trees is missing or incomplete — including after a packaged app update that ships the seed. Listings, photos, jobs, and settings are left untouched.

Manual import (optional):

```bash
cd vendoo-studio
./scripts/category-trees.sh import \
  --db "$HOME/Library/Application Support/List This Studio/vendoo_studio.db"
```

Export from a DB that already has complete trees with `./scripts/category-trees.sh export --db /path/to/vendoo_studio.db`.
