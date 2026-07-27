# Background Studio Batch Uploads Design

## Goal

Let users select up to ten photos, remove each background safely, and refine successful results one at a time with the existing editor. Preserve the current single-image workflow and backend job model.

## Scope

Version one includes:

- Selecting or dropping one to ten JPEG, PNG, or WebP files at once.
- A visible batch queue with thumbnail, filename, and per-item status.
- Sequential background removal using the existing `POST /api/jobs` endpoint.
- Automatic selection of the first successful result.
- Selecting any ready item and moving through ready results with Previous and Next controls.
- Independent mask settings, brush history, preview state, and export controls for each backend job.
- Retrying or removing an individual failed item.
- Canceling unstarted items and deleting created backend jobs when starting a new batch.
- Preserving the current one-file experience when only one file is selected.

Version one does not include a new backend batch endpoint, parallel inference, combined ZIP export, cross-session persistence, queue reordering, or more than ten files.

## Architecture

The frontend owns batch orchestration. The backend remains job-oriented and unchanged unless verification reveals a concrete missing contract.

Each selected file becomes a batch item with a stable client ID and this state:

- `file`: the original browser `File` while upload or retry remains possible.
- `name` and `previewUrl`: queue presentation data.
- `status`: `queued`, `processing`, `ready`, `failed`, or `cancelled`.
- `job`: the backend job metadata after successful processing.
- `error`: an item-specific user-facing failure message.
- `editor`: threshold, feather, background mode, solid color, comparison position, brush mode, brush size, softness, stroke count, server revision, and uncertainty state.

Only one item may be `processing`. Processing uses the existing upload request and waits for a terminal response before starting the next queued item. This avoids MPS contention and preserves the backend's current inference and capacity behavior.

The existing editor remains the single editing surface. Selecting a ready item loads its job and editor state into that surface. Before switching away, the current editor settings are saved back to the item's state. Brush mutations remain persisted on the item's backend job.

## User Experience

### Upload state

The empty screen retains the existing drop zone and file chooser, but the input accepts multiple files. Copy states that users may select up to ten photos.

After selection, the queue appears immediately in selection order. Each item shows:

- A local thumbnail.
- Filename.
- Status text.
- Retry for failed items.
- Remove for queued, failed, or ready items when no conflicting operation is active.

The currently selected item has a clear active treatment. Processing continues sequentially without requiring the user to keep an item selected.

### Editing state

When a result becomes ready, it can open in the existing editor. The queue remains visible as a compact strip or side panel depending on viewport width.

Previous and Next navigate among ready items only. Queue selection can jump directly to any ready item. Queued and processing items are visible but cannot open in the editor. Failed items expose Retry.

For a one-file batch, navigation is hidden and the interaction remains equivalent to today's single-image workflow.

### Completion state

When all items have reached `ready`, `failed`, or `cancelled`, the queue shows a concise batch summary. Exports remain per-item through the existing PNG and JPEG actions.

`New batch` performs best-effort deletion of every created backend job, revokes local object URLs, clears queue/editor state, and returns to the upload screen. If cleanup is uncertain, the UI preserves the existing uncertainty protections rather than pretending deletion succeeded.

## Failure Handling

Failures belong to individual items and do not stop later queued photos.

- Validation or inference failure: mark that item `failed`, retain the local file, and continue.
- Retry: reset only that item to `queued`; process it when it reaches the front of the remaining queue.
- Job expiration: mark that item failed/expired without discarding other items.
- Removal: delete its backend job when one exists, revoke its thumbnail URL, and select the nearest ready item if necessary.
- Batch reset: stop scheduling new work, invalidate stale async operations, then attempt cleanup of all known jobs.
- Page unload: retain the current best-effort beacon cleanup behavior for every known job ID.

Stale responses must be rejected by item ID and operation token so an old upload, preview, mutation, export, or deletion cannot overwrite another selected item.

## Limits and Resource Safety

The frontend enforces a hard maximum of ten selected files. Existing backend file-size, pixel-count, disk, and job-capacity limits remain authoritative.

Inference is sequential. There is no client-side or backend parallel model execution. The queue may continue after an individual capacity or validation failure, but repeated capacity failures must remain visible rather than retrying automatically.

Local thumbnail and preview object URLs are revoked when replaced, removed, reset, or unmounted.

## Testing

Frontend tests cover:

- Multiple file selection and ten-file enforcement.
- Sequential requests with no overlapping inference.
- Per-item queued, processing, ready, and failed states.
- Continuing after one failed item.
- Retry and removal behavior.
- Selecting and navigating ready items.
- Preserving independent editor state when switching.
- Rejecting stale responses after switching or reset.
- Cleaning all known jobs and object URLs on new batch and unmount.
- Single-file regression behavior.
- Responsive queue/editor structure and keyboard accessibility.

Backend tests confirm the existing API supports multiple independent jobs, job-specific mutation/export, and independent deletion. Production backend changes are added only if those tests expose a missing contract.

Verification includes the full backend and frontend suites, production build, dependency audit, and a real browser smoke test with multiple photos: processing, switching, refining one result, and exporting individual outputs.

## Acceptance Criteria

- A user can choose two to ten supported photos in one action.
- Processing occurs one photo at a time and automatically advances.
- One failure does not block later photos.
- Every successful photo remains independently refinable and exportable.
- Switching photos does not leak editor state or stale responses between jobs.
- Retry, remove, and new-batch cleanup act only on the intended jobs.
- Selecting one photo still behaves like the existing single-image workflow.
- The implementation passes all existing and new tests plus a real multi-photo UI smoke test.
