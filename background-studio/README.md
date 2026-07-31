# Background Studio

Background Studio is a macOS web app for removing an image background with BiRefNet-HR, refining the derived alpha with reversible threshold and feather controls, previewing transparency or a solid color, and exporting full-resolution PNG/JPEG files. When used remotely, image uploads travel through the private Tailnet to Tailscale Serve on this Mac, then Vite proxies them to the loopback FastAPI process.

The default production setup offloads only model inference to a private Runpod Serverless endpoint. The Mac keeps the original full-resolution image, job storage, mask edits, previews, and exports. Runpod receives a deterministic 1024×1024 letterboxed PNG and returns a 1024×1024 grayscale mask; the worker retains neither. The pinned model uses `trust_remote_code=True`, so repository-supplied Python runs inside the Runpod worker with that container's privileges. The app does not use Bria weights.

## Requirements

- macOS on Apple Silicon or Intel
- Python 3.11
- Node.js 20 or newer
- About 8 GB of free disk space for Python packages and model data

## Exact setup commands

```bash
cd /Users/cris/Developer/list-this-vendoo-suite/background-studio
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

## Run

Terminal 1:

```bash id="9ts0a1"
cd /Users/cris/Developer/list-this-vendoo-suite/background-studio
source .venv/bin/activate
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

Terminal 2:

```bash id="b1apj0"
cd /Users/cris/Developer/list-this-vendoo-suite/background-studio/frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`.

### Runpod GPU inference

The production endpoint is `background-studio-birefnet-hr`
(`wksnckg4xiy9jo`). It is a load-balanced Serverless endpoint with zero
minimum workers, one maximum worker, request-count scaling, FlashBoot, and a
60-second idle timeout. It prefers an RTX 4090 from Runpod's `ADA_24` pool and
can fall back to a 24 GB Ampere GPU when that pool has no usable host. A small
port-80 front door satisfies Runpod's load-balancer health checks while the
dependency installer and BiRefNet-HR API start on loopback port 8000.

Runpod requires its own API key at the gateway even though the worker also
checks an app-specific token. Create a **Restricted** API key in Runpod
Settings and grant it access only to this Serverless endpoint. Store it
without putting it in shell history:

```bash
cd /Users/cris/Developer/list-this-vendoo-suite/background-studio
./scripts/store-runpod-api-key.sh
```

The endpoint URL, Runpod API key, and worker token are read from macOS
Keychain service `background-studio-runpod`. They never enter the repository,
SQLite, logs, frontend responses, or extension messages. When all three
Keychain items exist, the backend selects Runpod automatically. Force local
inference for an individual launch with:

```bash
BACKGROUND_STUDIO_REMOVER_BACKEND=local \
  uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

The first request after scale-to-zero includes worker startup and can be
substantially slower than a warm request. Cold-start gateway statuses are
retried for up to five minutes; an ambiguous read timeout is not retried. The
GPU is billed only while a worker is initializing or running. Runpod reports
idle and throttled Flex workers as non-billable, so the endpoint configuration
can remain available continuously without an always-on GPU.

### Private Tailnet access

After starting the backend and frontend exactly as above, configure the existing Vite process as a private Tailscale Serve route:

```bash
cd /Users/cris/Developer/list-this-vendoo-suite/background-studio
./scripts/start-private-tailnet.sh
tailscale serve status
```

Then open `https://criss-mac-mini-1.tail6c7361.ts.net:8445`. This route is available only to authorized devices on the Tailnet. Vite and FastAPI remain bound to loopback; the helper does not start or supervise either application process and never enables Funnel.

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

```bash id="ngabs5"
cd /Users/cris/Developer/list-this-vendoo-suite/background-studio
source .venv/bin/activate
pytest -q backend/tests
cd frontend
npm test
```

## Limits and storage

Defaults are 25 MiB per upload, 40 megapixels, 8 live jobs, 1.5 GiB of temporary job data, and 30 minutes of idle retention. Oriented originals and raw masks are immutable PNG files in a mode-0700 temporary directory; files are mode 0600. Derived previews and exports are rendered on demand. Startup removes stale job directories and shutdown removes all live jobs. Override limits with `BACKGROUND_STUDIO_MAX_UPLOAD_BYTES`, `BACKGROUND_STUDIO_MAX_PIXELS`, `BACKGROUND_STUDIO_MAX_JOBS`, `BACKGROUND_STUDIO_DISK_QUOTA_BYTES`, `BACKGROUND_STUDIO_JOB_TTL_SECONDS`, or `BACKGROUND_STUDIO_TEMP_ROOT`.
