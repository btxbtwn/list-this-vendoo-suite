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

The packaged app does not git-pull. **Check for updates** compares the stamped build SHA against the GitHub release and, if newer, downloads the zip, replaces the `.app`, and relaunches. Listing data stays in `~/Library/Application Support/List This Studio`.

The recipient:

1. Unzips the archive and moves **List This Studio** into Applications.
2. Control-clicks the app and chooses **Open** the first time (ad-hoc signed, not notarized).
3. Signs in with ChatGPT or enters a Xiaomi MiMo API key in Settings.
4. Clicks **Connect Chrome**. Studio opens Vendoo in everyday Chrome. Load the unpacked listing extension there once (`chrome://extensions/` → Developer mode → Load unpacked), then sign in to Vendoo. Zip users pick `~/Library/Application Support/List This Studio/vendoo-extension`; from this repo, pick `vendoo-extension/`.

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
3. Click **Connect Chrome** and sign in to Vendoo.

## Workflow

1. **Create a listing**.
2. **Upload photos** by dragging them into the photo tray.
3. Optionally add notes (cost, flaws, measurements).
4. Chat to analyze the photos and generate a listing.
5. Review the listing in the right panel.
6. Click **Send to Vendoo**. Studio fills and saves a draft, then stops before publishing.

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
- API keys and ChatGPT tokens live in macOS Keychain, never in SQLite, browser storage, or logs.
- Never sent to the React frontend or Chrome extension.
- Photos are served only on localhost (`GET /api/photos/{id}`).
- No publication automation — only draft saving.

## Development

```bash
./scripts/dev.sh     # backend + frontend together
./scripts/doctor.sh  # check Python, Node, Chrome, ports
cd vendoo-studio && npm run build
PYTHONPATH=server .venv/bin/python -m pytest -q server/tests
```

Set `VENDOO_STUDIO_DEV=1` if you start the backend yourself and want auto-reload.

The extension connects to `ws://127.0.0.1:4318/api/extension/ws`. **Connect Chrome** opens Vendoo in everyday Chrome; load the unpacked extension there once.

## Database

SQLite at `data/vendoo_studio.db` in development, or `~/Library/Application Support/List This Studio` in the packaged app. Tables:

- `conversations` — listing sessions
- `messages` — chat history
- `photos` — uploaded images
- `listings` — current listing state
- `listing_revisions` — edit history
- `jobs` — automation jobs
- `job_events` — per-job event log
