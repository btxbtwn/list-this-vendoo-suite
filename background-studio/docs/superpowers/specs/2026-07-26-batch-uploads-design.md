# Background Studio Batch Uploads Design

## Goal

Let users select up to ten photos, remove each background safely, and refine successful results one at a time with the existing editor. Preserve the current single-image experience while making every batch item independently recoverable, editable, and disposable.

## Scope

Version one includes:

- Selecting or dropping one to ten JPEG, PNG, or WebP files at once.
- A queue with bounded thumbnails, filenames, and per-item status.
- Sequential background removal through the existing `POST /api/jobs` contract.
- Automatic selection of the first successful result only when no ready result is already selected.
- Selecting any ready item and moving through ready results with Previous and Next controls.
- Independent editor settings, brush history, preview ownership, errors, and operation state per item.
- Retrying or removing an individual failed or expired item.
- Canceling unstarted items and reconciling or deleting created jobs when starting a new batch.
- Preserving the current one-file experience when only one file is selected.

Version one does not include parallel inference, combined ZIP export, cross-session persistence, queue reordering, or more than ten files.

## Architecture

### Backend contracts

The backend remains job-oriented; it does not gain a batch-creation endpoint. Three focused backend changes support retained batches:

1. Raise the live-job limit from eight to twelve. Ten slots are available for a full batch, with two slots of reconciliation and cleanup headroom. Existing byte and pixel capacity limits remain authoritative.
2. Add a lightweight authenticated-local `POST /api/jobs/{job_id}/touch` endpoint. It updates the job's last-access time without reading or rendering image data and returns `204`, `404`, or `410` consistently with existing job lookup semantics.
3. Verify that ten simultaneously retained jobs can each be queried, previewed, exported, touched, and deleted independently.

Inference remains serialized by the existing `InferenceService`. The frontend sends only one creation request at a time.

### Frontend state

A reducer owns the canonical batch state. There is no second global copy of persistent editor settings to save during selection changes.

Batch state contains:

- `batchId` and monotonically increasing `batchGeneration`.
- Ordered item IDs and `selectedItemId`.
- An item map.
- A cleanup ledger keyed by every backend job ID that is not confirmed deleted.
- Queue-running and announcement state.

Each item has:

- A stable client `itemId` and `itemGeneration`.
- The original browser `File`, retained so validation, inference, or expiration failures can be retried during the current page session.
- Filename and a bounded thumbnail object URL.
- A preallocated backend `jobId` used for every create, reconcile, retry, and cleanup operation for that item generation.
- Status: `queued`, `processing`, `reconciling`, `ready`, `failed`, `expired`, `removing`, or `cancelled`.
- Item-specific error text.
- Backend dimensions after creation.
- Canonical editor settings: threshold, feather, background mode, solid color, comparison, brush mode, brush size, softness, stroke count, server revision, and uncertainty causes.
- Preview state: request sequence, source revision, parameters fingerprint, readiness, object URL, and item-specific preview error.
- Operation sequences for create/reconcile, preview, mutation, export, and deletion.

Every reducer action carries the relevant `batchGeneration`, `itemId`, `itemGeneration`, `jobId`, and operation sequence. Reducer guards reject stale actions. A mutation that completes for an unselected item updates that item's revision and stroke count without touching the selected item.

### Job creation and reconciliation

`createJobForItem` is separate from editor selection and never deletes another item's job.

Before upload, the frontend preallocates a backend job ID and records it in the cleanup ledger. It submits that ID with the existing multipart `job_id` field.

On a valid `201`, the matching item becomes ready and the ledger records the job as present. A valid stale `201` from a discarded batch or replaced item generation triggers compensating deletion instead of being ignored.

If transport, parsing, or response-shape failure leaves creation uncertain, the item enters `reconciling`. The frontend queries that exact preallocated job ID using the existing reconciliation contract:

- Present and complete: accept the job and mark the item ready.
- Confirmed absent: mark the item failed and permit retry with a new item generation and job ID.
- Present but incomplete: continue bounded reconciliation.
- Unknown or reconciliation failure: keep the item uncertain and its job ID in the cleanup ledger; do not allow retry yet.

Retry never creates another job while a prior attempt remains unresolved.

### Cleanup ledger

The cleanup ledger is independent of visible items. Removing an item or resetting the batch cannot erase an unresolved backend job ID.

Each entry records `jobId`, originating batch/item generation, and `present`, `deleting`, `deleted`, or `unknown`. Confirmed deletion removes the entry. Failed or interrupted deletion returns it to `unknown` for reconciliation.

A new batch may be shown while cleanup continues, but unresolved ledger entries count against the twelve-job capacity. Upload scheduling pauses before it would exceed available capacity and displays a cleanup message instead of producing repeated capacity errors.

On reset or unmount:

- Increment the batch generation and stop scheduling queued items.
- Abort frontend requests where possible.
- Reconcile every in-flight preallocated job ID.
- Compensating-delete stale successful creations.
- Attempt deletion of every known present or unknown job.
- Preserve unresolved IDs in the ledger until deletion or confirmed absence.
- Revoke all thumbnail and preview object URLs.

`sendBeacon` remains best effort only; it does not count as confirmed deletion.

## Thumbnails and Browser Memory

Queue thumbnails are bounded derivatives, not direct full-resolution file URLs.

For each accepted file, the frontend decodes with EXIF orientation applied, scales to fit within 192×192 without upscaling, and writes a compressed thumbnail blob. The temporary source URL or bitmap is released immediately after thumbnail creation. Only the small thumbnail object URL remains mounted. It is revoked when replaced, removed, reset, or unmounted.

Thumbnail failure does not prevent processing; the queue falls back to a non-image file placeholder and reports no global error.

## Processing and Job Lifetime

Only one item may be `processing` or actively reconciling creation at a time. A terminal item result advances the queue. One failed item does not stop later queued items.

While a batch contains ready jobs, the frontend touches each retained ready job every five minutes and when the page becomes visible. Touches are bounded and sequential, and stop when jobs are removed or the component unmounts. The existing thirty-minute TTL therefore remains the safety boundary for abandoned sessions while active batches retain their editable jobs.

A `404` or `410` touch marks only that item expired. Because the original `File` remains available, the item can be retried after the old job is confirmed absent or deleted.

## User Experience

### Upload and queue

The drop zone and chooser accept multiple files and state the ten-photo maximum. Unsupported files and selections beyond ten receive deterministic per-file or batch-limit messages; accepted files remain in selection order.

The queue is a semantic list. Each item contains:

- A bounded thumbnail or file placeholder.
- Filename.
- Status text.
- A button to select a ready item.
- `Retry <filename>` when retry is safe.
- `Remove <filename>` when removal is safe.

The active item uses `aria-current="true"` and a non-color indicator. Status changes use one restrained `aria-live="polite"` region for completion, failure, and final summary rather than announcing every progress render.

Automatic first-success selection occurs only when no ready item is selected and never moves keyboard focus. Processing a background item never steals focus.

### Editing

The existing editor is derived from the selected item's reducer state. Queue selection can jump to a ready item. Previous and Next navigate ready items only and use accessible names that include position where useful.

Switching immediately invalidates visible preview readiness. A preview may update the item that requested it, but only a preview identity matching all of `batchGeneration + itemId + itemGeneration + jobId + editor-parameter fingerprint + serverRevision + requestSequence` may replace the visible selected preview.

Preview, mutation, export, and deletion errors remain owned by their originating item. Late operations cannot overwrite another item's image, controls, revision, stroke count, or error.

For one selected file, the queue may collapse to a compact single-item summary, Previous/Next remain hidden, and the editor interaction remains equivalent to the current workflow.

### Removal and focus

Removing the selected item chooses the nearest ready neighbor, preferring the next item and then the previous item. Focus moves predictably to that selected item's queue button; if no ready item remains, focus moves to the queue heading or upload control. Removing an unselected item preserves current focus.

Disabled controls remain semantically named. Queued or processing items are not selectable as editors but their status remains readable.

### Completion and reset

When every visible item is ready, failed, expired, or cancelled, the live region announces one concise batch summary. Exports remain per item through existing PNG and JPEG actions.

`New batch` invalidates the old batch immediately, begins ledger-driven cleanup, and returns to upload once visible state is safely detached. Unknown cleanup IDs remain tracked even after the old queue disappears.

## Error Handling

- Validation or inference failure: mark only that item failed, retain its file, and continue.
- Lost creation response: reconcile the preallocated ID; do not expose Retry while unresolved.
- Reset during inference: invalidate the batch; reconcile the ID and delete any resulting job.
- Retry: only after absence/deletion is confirmed; use a new item generation and job ID.
- Expiration: mark only that item expired and offer safe retry.
- Preview/mutation/export failure: attribute it to the originating item and preserve other items.
- Deletion failure: retain the ID as unknown in the cleanup ledger and retry reconciliation later.
- Capacity pressure: pause queue scheduling with a clear message; do not spin or auto-retry repeatedly.

## Testing

Frontend tests explicitly cover:

- Multiple selection, unsupported files, order, and ten-file enforcement.
- Bounded 192×192 EXIF-corrected thumbnails for very large dimensions and object-URL revocation.
- Ten retained successful jobs.
- Strictly sequential creates with no overlapping inference.
- Item B processing never deleting or resetting item A.
- Continuing after a validation or inference failure.
- Lost creation response after backend success, exact-ID reconciliation, and blocked Retry while unresolved.
- Reset during inference followed by stale success and compensating deletion.
- Several deletion failures retaining several independent cleanup-ledger entries.
- Retry after confirmed absence and retry after expiration using the retained `File`.
- Canonical independent editor state while switching items.
- Switching during preview, mutation, and export completion.
- Removing the selected item while its preview is pending.
- A mutation response updating its originating unselected item.
- Preview identity invalidation across item selection and revisions.
- Touch scheduling, page visibility touch, expiration handling, and a deliberately slow ten-item queue.
- Unmount cleanup with queued, ready, uncertain, and processing items together.
- Single-file regression behavior.
- Semantic queue controls, `aria-current`, accessible Retry/Remove names, restrained live announcements, deterministic removal focus, and no focus stealing.
- Mobile queue/editor layout plus keyboard and screen-reader focus order.

Backend tests cover:

- Twelve-job capacity and rejection beyond it.
- Ten simultaneously retained jobs with independent status, preview, export, touch, mutation, and deletion.
- Touch refreshing last access without rendering or mutating image data.
- Touch `404`/`410` behavior and cleanup races.
- Existing single-job behavior and limits not related to live-job count.

Verification includes full backend/frontend suites, production build, dependency audit, and a real browser smoke test with multiple photos: sequential processing, queue switching, refining one result, expiration-safe touches, and individual exports.

## Acceptance Criteria

- A user can choose two to ten supported photos in one action.
- Processing is strictly sequential and advances automatically.
- Ten successful jobs can remain live and independently editable.
- One failure does not block later photos.
- Lost responses and stale successes cannot duplicate or orphan jobs.
- Every successful photo remains independently refinable and exportable while the active batch lease is maintained.
- Switching does not leak editor state, preview readiness, responses, or errors between items.
- Retry, remove, reset, unmount, and stale completion cleanup act on the intended job IDs through the ledger.
- Queue thumbnails have bounded decode/display memory.
- Queue interaction is keyboard and screen-reader accessible without focus theft.
- Selecting one photo still behaves like the existing single-image workflow.
- The implementation passes all existing and new tests plus a real multi-photo UI smoke test.
