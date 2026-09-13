# Background Studio

Background Studio is a macOS web app for removing an image background with BiRefNet-HR, refining the derived alpha with reversible threshold and feather controls, previewing transparency or a solid color, and exporting full-resolution PNG/JPEG files. When used remotely, image uploads travel through the private Tailnet to Tailscale Serve on this Mac, then Vite proxies them to the loopback FastAPI process.

The default production setup offloads only model inference to a private Runpod Serverless endpoint. The Mac keeps the original full-resolution image, job storage, mask edits, previews, and exports. The production path uses a deterministic 2048×2048 letterboxed canvas and mask for higher-resolution edge recovery. The worker still supports 1024px and 1536px compatibility modes, but the worker and Mac backend must use the same canvas setting. The pinned model uses `trust_remote_code=True`, so repository-supplied Python runs inside the Runpod worker with that container's privileges. The app does not use Bria weights.

## Requirements

- macOS on Apple Silicon or Intel
- Python 3.11
- Node.js 20 or newer
- About 8 GB of free disk space for Python packages and model data

## Setup

From this directory:

```bash
./scripts/setup.sh
./scripts/dev.sh
```

`setup.sh` creates `.venv`, installs backend requirements, and installs frontend packages. `dev.sh` starts FastAPI on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`.

Open `http://127.0.0.1:5173`.

Manual equivalent:

```bash
cd background-studio
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
cd frontend
npm install
```

Then run:

```bash
# terminal 1
cd background-studio
source .venv/bin/activate
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1

# terminal 2
cd background-studio/frontend
npm run dev -- --host 127.0.0.1
```

### Runpod GPU inference

Inference can stay on this Mac, or you can point the backend at your own private Runpod Serverless endpoint. Endpoint URL, Runpod API key, and worker token are read from macOS Keychain service `background-studio-runpod`. They never enter the repository, SQLite, logs, or frontend responses.

Store credentials without putting them in shell history:

```bash
cd background-studio
./scripts/store-runpod-api-key.sh
```

When all three Keychain items exist, the backend selects Runpod automatically. Force local inference for an individual launch with:

```bash
BACKGROUND_STUDIO_REMOVER_BACKEND=local \
  uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

The first request after scale-to-zero includes worker startup and can be substantially slower than a warm request. Cold-start gateway statuses are retried for up to five minutes; an ambiguous read timeout is not retried. The GPU is billed only while a worker is initializing or running. The deployed endpoint and Mac backend must use the same canvas size (`BACKGROUND_STUDIO_CANVAS_SIZE` / `BACKGROUND_STUDIO_RUNPOD_CANVAS_SIZE`, default 2048).

The pinned model uses `trust_remote_code=True`, so repository-supplied Python runs inside the Runpod worker with that container's privileges.

### Private Tailnet access

After starting the backend and frontend, configure a private Tailscale Serve route for this Mac:

```bash
cd background-studio
./scripts/start-private-tailnet.sh
tailscale serve status
```

The helper reads this machine's Tailscale DNS name. The route is available only to authorized devices on the Tailnet. Vite and FastAPI remain bound to loopback; the helper does not start or supervise either application process and never enables Funnel.

To disable only this route with the installed Tailscale CLI:

```bash
tailscale serve --https 8445 off
```

Do **not** use `tailscale serve reset`: it would remove unrelated Serve routes on this Mac.

For local fallback, the first removal downloads the pinned
`ZhengPeng7/BiRefNet_HR` model revision from Hugging Face. Loading it uses
`trust_remote_code=True`, which executes repository-supplied Python with the
same privileges as the backend process. The revision pin makes that code
reproducible but is not a sandbox or security boundary. No Hugging Face token
is required for this public model. Model weights and trusted model code persist
in the standard Hugging Face cache, normally `~/.cache/huggingface`, after jobs
and temporary images are deleted.

The server intentionally supports one process only. Do not increase `--workers`; a process lock rejects a second backend using the same temporary root. Requests must arrive through loopback Host and client addresses.

## Tests

```bash
cd background-studio
source .venv/bin/activate
pytest -q backend/tests
cd frontend
npm test
```

## Limits and storage

Defaults are 25 MiB per upload, 40 megapixels, 8 live jobs, 1.5 GiB of temporary job data, and 30 minutes of idle retention. Oriented originals and raw masks are immutable PNG files in a mode-0700 temporary directory; files are mode 0600. Derived previews and exports are rendered on demand. Startup removes stale job directories and shutdown removes all live jobs. Override limits with `BACKGROUND_STUDIO_MAX_UPLOAD_BYTES`, `BACKGROUND_STUDIO_MAX_PIXELS`, `BACKGROUND_STUDIO_MAX_JOBS`, `BACKGROUND_STUDIO_DISK_QUOTA_BYTES`, `BACKGROUND_STUDIO_JOB_TTL_SECONDS`, or `BACKGROUND_STUDIO_TEMP_ROOT`.

The frontend keeps a small, versioned recovery manifest in browser storage so a mobile page reload can restore the queue and reconnect to live jobs. It stores metadata only (job IDs, filenames, dimensions, and editor settings), never image bytes or credentials. Jobs still expire after 30 minutes of inactivity, and a backend restart removes its in-memory jobs; those jobs cannot be recovered from the browser manifest.
