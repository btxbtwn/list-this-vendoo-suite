# Vendoo Listing Studio

Local application for generating and automating Vendoo marketplace listings through Xiaomi MiMo AI.

## Share a Mac app

Build a self-contained `.app` that someone else can unzip and open. They do not need Python, Node, or this git repo.

```bash
cd vendoo-studio
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[package]"
./scripts/package-macos-app.sh
```

That writes `vendoo-studio/release/List This Studio.app` and `vendoo-studio/release/List-This-Studio-macos.zip`.

Publish the zip as the rolling GitHub release (`studio-macos`):

```bash
./scripts/publish-macos-release.sh
```

Pushes to `main` that touch Studio, the extension, or listing skills also build and replace that release through `.github/workflows/studio-macos.yml`.

The packaged app does not git-pull. **Check for updates** compares the stamped build SHA against the GitHub release and, if newer, downloads the zip, replaces the `.app`, and relaunches. Listing data stays in `~/Library/Application Support/List This Studio`.

The recipient:

1. Unzips the archive and moves **List This Studio** into Applications.
2. Opens it. The first time, macOS may require right-click → Open because the build is ad-hoc signed, not notarized.
3. Enters a Xiaomi MiMo API key in Settings.
4. Clicks **Connect Chrome**. Studio opens a managed Chrome window with the Vendoo extension loaded. They sign in to Vendoo there once.

They need macOS 13+ and Google Chrome. Listing photos and the SQLite database live in `~/Library/Application Support/List This Studio`.

## Quick Start (development)

```bash
cd vendoo-studio

# Backend (Python 3.12+)
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn[standard] pydantic sqlalchemy httpx python-multipart pillow keyring aiofiles
PYTHONPATH=server python -m vendoo_studio.main

# Frontend (dev mode, separate terminal)
npm install
npm run dev
```

The app opens at http://127.0.0.1:4318. In development the frontend runs at http://127.0.0.1:5173 with API proxying.

## Setup

1. Open the app in your browser.
2. Go to **Settings** (sidebar).
3. Enter your Xiaomi MiMo API key.
4. Click **Save Key** then **Test Connection**.
5. Load the Chrome extension unpacked from `../vendoo-extension/`.
6. The extension connects automatically and the status bar shows **Extension connected**.

## Workflow

1. **Create a listing** (sidebar + New).
2. **Upload photos** by dragging them into the photo tray.
3. Optionally add notes (cost, flaws, measurements).
4. **Chat with MiMo** - ask it to analyze the photos and generate a listing.
5. **Review the listing** in the right panel (General, eBay, Depop, etc. tabs or raw JSON).
6. Revise by chatting, editing fields, or editing JSON directly.
7. When satisfied, click **Send to Vendoo**.
8. Watch the progress as the extension:
   - Opens a new Vendoo listing
   - Uploads the approved photos
   - Fills and saves the general form
   - Fills and saves each selected marketplace
   - Stops before publishing
9. Open the Vendoo draft to review and publish manually.

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
│       └── providers/   Xiaomi MiMo API client
├── src/                 React frontend
│   ├── app/             Main app and routing
│   ├── api/             API client
│   ├── components/      UI components
│   └── styles/          CSS
└── data/                SQLite database and photo storage
```

## Security

- Binds only to `127.0.0.1` (localhost).
- MiMo API key stored in macOS Keychain, never in SQLite, browser storage, or logs.
- Never sent to the React frontend or Chrome extension.
- Photo URLs use signed tokens for extension access.
- No publication automation - only draft saving.

## Development

### Backend

```bash
source .venv/bin/activate
PYTHONPATH=server python -m vendoo_studio.main
```

Set `VENDOO_STUDIO_DEV=1` for auto-reload.

### Frontend

```bash
npm run dev      # Vite dev server with API proxy
npm run build    # Production build to dist/
```

### Extension

Load unpacked from `../vendoo-extension/` in `chrome://extensions/`. The extension connects to `ws://127.0.0.1:4318/api/extension/ws`.

## Database

SQLite at `data/vendoo_studio.db`. Tables:

- `conversations` - listing sessions
- `messages` - chat history
- `photos` - uploaded images
- `listings` - current listing state
- `listing_revisions` - edit history
- `jobs` - automation jobs
- `job_events` - per-job event log
