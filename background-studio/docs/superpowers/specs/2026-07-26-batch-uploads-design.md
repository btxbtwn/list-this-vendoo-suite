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

The backend remains job-oriented; it does not gain a batch-creation endpoint. Four focused backend changes support retained batches:

1. Raise the live-job limit from eight to twelve. Ten slots are available for a full batch, with two slots of reconciliation and cleanup headroom. Existing byte and pixel capacity limits remain authoritative.
2. Add a lightweight authenticated-local `POST /api/jobs/{job_id}/touch` endpoint. It updates the job's last-access time without reading or rendering image data and returns `204`, `404`, or `410` consistently with existing job lookup semantics.
3. Add an idempotent `POST /api/jobs/{job_id}/cancel` endpoint. Under the store lock it tombstones an unused valid ID, cancels and terminalizes a creating generation, or terminalizes a live job before deleting its files. `204` means commit is impossible and physical cleanup is complete. `202 {state: "cleanup_pending"}` means commit is impossible but the backend quarantine/cleanup worker still owns physical cleanup. A nonterminal failure never claims cancellation. This closes the race where a reconciliation `404` arrives before a delayed create reserves its ID.
4. Verify that ten simultaneously retained jobs can each be queried, previewed, exported, touched, canceled, and deleted independently.

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
- Status: `queued`, `processing`, `reconciling`, `cleanup-pending`, `ready`, `failed`, `expired`, `removing`, or `cancelled`.
- Item-specific error text.
- Backend dimensions after creation.
- Canonical editor settings: threshold, feather, background mode, solid color, comparison, brush mode, brush size, softness, stroke count, server revision, and uncertainty causes.
- Preview state: request sequence, source revision, parameters fingerprint, readiness, object URL, and item-specific preview error.
- Operation sequences for create/reconcile, preview, mutation, export, and deletion.

Every reducer action carries the relevant `batchGeneration`, `itemId`, `itemGeneration`, `jobId`, and operation sequence. Reducer guards reject stale actions. A mutation that completes for an unselected item updates that item's revision and stroke count without touching the selected item.

### Job creation and reconciliation

`createJobForItem` is separate from editor selection and never deletes another item's job.

Before upload, the frontend preallocates a backend job ID and synchronously writes a cleanup-ledger entry to `sessionStorage` before dispatching `POST /api/jobs`. The request does not begin if write-ahead persistence fails. It submits that ID with the existing multipart `job_id` field.

On a valid `201`, the matching item becomes ready and the ledger records the job as present. A valid stale `201` from a discarded batch or replaced item generation triggers compensating cancellation instead of being ignored.

If transport, parsing, or response-shape failure leaves creation uncertain, the item enters `reconciling`. The frontend queries that exact preallocated job ID using the existing reconciliation contract:

- Present and complete: accept the job and mark the item ready.
- `404 unknown`: do not treat absence as terminal because the original request may still reserve later. Call the idempotent cancel endpoint; only its successful `204` makes Retry safe.
- Present but incomplete: continue bounded reconciliation.
- Terminal `410`: mark the item failed and permit retry with a new item generation and job ID.
- Unknown or reconciliation/cancel failure after bounded foreground attempts: move the item to `cleanup-pending`, transfer responsibility to background ledger reconciliation, keep Retry disabled, and advance later queued items when server capacity permits.

Retry never creates another job while a prior attempt remains unresolved. Lifecycle `410`, cancel `204`, and cancel `202 cleanup_pending` prove commit terminality and permit a new item generation; only `204` proves physical cleanup and permits ledger removal. Validation, capacity, inference, cancellation, and cleanup responses without terminal proof follow reconciliation.

Capacity `507` follows the same rule. The old ID is reconciled/canceled first. Manual Resume appears only after terminality is proven, increments `itemGeneration`, allocates and write-ahead persists a new `jobId`, and never resubmits the tombstoned ID.

### Cleanup ledger

The cleanup ledger is independent of visible items. Removing an item or resetting the batch cannot erase an unresolved backend job ID. Entries are write-ahead persisted synchronously to `sessionStorage` before creation, restored on mount, and removed only after physical-cleanup proof. If storage is unavailable, the affected upload remains failed locally and no backend request starts. This survives component remounts and page reloads; a hard tab close, browser crash without session restoration, or storage clearing may leave jobs until backend TTL cleanup.

Each entry records `jobId`, an independent `ledgerEntryGeneration`, originating batch/item generation, commit-terminal state, physical-cleanup state, and ledger operation sequence. Ledger transitions are guarded by `jobId + ledgerEntryGeneration + ledger operation sequence`, never by the visible `batchGeneration`. Starting a new batch cannot stop old-batch cleanup. Stale creation success always dispatches compensating cancellation even when its item action is rejected. Cancel `202` keeps the entry cleanup-pending; retries continue until `204` or backend TTL/quarantine cleanup provides equivalent physical-cleanup proof.

Cancel tombstones are checked atomically by every create reservation and do not consume live-job capacity or disk quota. They are never evicted while the backend process runs. A bounded maximum of 4,096 tombstones rejects additional unknown-ID cancellations rather than evicting safety state; process restart safely clears them because no request from the prior process can later commit.

A new batch may be shown while cleanup continues. Locally unresolved ledger entries count against the twelve-job capacity, but the frontend cannot know about jobs in another tab or abandoned session. Server `507` is authoritative backpressure: scheduling pauses, preserves queued items, and offers bounded manual Resume after cleanup rather than treating capacity as an ordinary item failure or spinning automatically.

On reset or unmount:

- Increment the batch generation and stop scheduling queued items.
- Abort frontend requests where possible.
- Reconcile and cancel every in-flight preallocated job ID.
- Compensating-cancel stale successful creations.
- Attempt cancellation/deletion of every known present or unknown job.
- Preserve unresolved IDs until terminal lifecycle state or successful cancellation/deletion proves they cannot commit.
- Revoke all thumbnail and preview object URLs.

`sendBeacon` remains best effort only; it does not count as confirmed deletion.

## Thumbnails and Browser Memory

Queue thumbnails are bounded derivatives, not direct full-resolution file URLs.

Thumbnail work has concurrency one. A header-only parser reads bounded leading bytes to establish JPEG, PNG, or WebP dimensions before full decode. Files larger than 8 MiB, files above a 20-megapixel thumbnail-decode limit, malformed headers, and formats whose dimensions cannot be established safely use the placeholder path without calling `createImageBitmap`. For eligible files, `createImageBitmap` receives EXIF-aware orientation and 192-pixel resize hints where supported, then a bounded canvas writes the thumbnail blob. Bitmap, canvas backing storage, and any temporary source URL are released immediately. Only the small thumbnail object URL remains mounted. It is revoked when replaced, removed, reset, or unmounted.

Thumbnail failure, unavailable resize hints, or unsafe dimensions do not prevent backend processing; the queue uses a file placeholder and reports no global error. The design guarantees bounded retained thumbnail memory and sequential decode attempts, not that every browser decoder honors resize hints without a transient source decode.

## Processing and Job Lifetime

Only one item may be `processing` or actively reconciling creation at a time. A terminal result or transfer to background `cleanup-pending` advances the queue when capacity permits. One failed or uncertain item does not stop later queued items indefinitely.

While a batch contains ready jobs, the frontend touches each retained ready job every five minutes and when the page becomes visible. Touches are bounded and sequential, and stop when jobs are removed or the component unmounts. This retains jobs while JavaScript heartbeat execution is permitted; mobile/background timer suspension may exceed the thirty-minute TTL, so uninterrupted retention is not promised while the browser is suspended.

A `404` or `410` touch marks only that item expired. The transition aborts that item's active requests, invalidates every operation sequence, clears preview readiness, revokes its preview URL, and makes reducers reject completions unless the item remains in the operation's required state. Because the original `File` remains available, the item can be retried after cancel or lifecycle state proves the old ID terminal.

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

Preview, mutation, export, and deletion errors remain owned by their originating item. Late operations cannot overwrite another item's image, controls, revision, stroke count, or error. Replacing a preview revokes the prior URL. A stale response whose new URL is rejected revokes that URL immediately. Expiration, removal, reset, and unmount revoke every retained preview URL.

For one selected file, the queue may collapse to a compact single-item summary, Previous/Next remain hidden, and the editor interaction remains equivalent to the current workflow.

### Removal and focus

Removing the selected item chooses the nearest ready neighbor, preferring the next item and then the previous item. Focus moves to that selected item's queue button; if no ready item remains, focus moves to the queue heading or upload control. Removing an unselected item preserves focus unless focus was inside the removed item; then focus moves to the next item's primary control, the previous item, the selected item, or the queue heading in that order. Retry control replacement follows the same fallback. Tests activate these controls by keyboard.

Disabled controls remain semantically named. Queued or processing items are not selectable as editors but their status remains readable.

### Completion and reset

When every visible item is ready, failed, expired, or cancelled, the live region announces one concise batch summary. Exports remain per item through existing PNG and JPEG actions.

`New batch` invalidates the old batch immediately, begins ledger-driven cleanup, and returns to upload once visible state is safely detached. Unknown cleanup IDs remain tracked even after the old queue disappears.

## Error Handling

- Validation or inference failure: mark only that item failed, retain its file, and continue.
- Lost creation response: reconcile and atomically cancel the write-ahead-persisted ID; do not expose Retry without commit-terminal proof.
- Reset during inference: invalidate the batch, atomically cancel the ID, and reject or clean any stale result.
- Retry: only after terminal lifecycle state or successful cancellation/deletion proves the old ID cannot commit; use a new item generation and job ID.
- Expiration: mark only that item expired and offer safe retry.
- Preview/mutation/export failure: attribute it to the originating item and preserve other items.
- Deletion failure: retain the ID as unknown in the cleanup ledger and retry reconciliation later.
- Capacity pressure, including another tab or disk quota: reconcile/cancel the attempted ID, pause scheduling, and show bounded manual Resume only after commit terminality. Resume uses a new item generation and new write-ahead-persisted ID. Do not spin or convert remaining queued items to ordinary failures. Selecting ten files does not override existing byte, pixel, memory, or disk quotas.

## Testing

Frontend tests explicitly cover:

- Multiple selection, unsupported files, order, and ten-file enforcement.
- Header-only JPEG/PNG/WebP dimension parsing, placeholder behavior for small-byte extreme dimensions, and proof that unsafe inputs never invoke full decode.
- Bounded 192×192 EXIF-corrected thumbnails for eligible inputs and object-URL revocation.
- Ten retained successful jobs.
- Strictly sequential creates with no overlapping inference.
- Item B processing never deleting or resetting item A.
- Continuing after a validation or inference failure.
- Synchronous ledger persistence before request dispatch, immediate reload recovery, and storage-write failure preventing creation.
- Lost creation response before or after reservation, exact-ID reconciliation/cancellation, and blocked Retry until commit-terminal proof.
- An unresolved first item moving to `cleanup-pending` while later valid items continue when capacity permits.
- Reset during inference followed by stale success and compensating deletion.
- Several deletion failures retaining independent cleanup entries after commit terminality, with safe item Retry and eventual physical cleanup.
- Retry after commit-terminal proof and retry after expiration using the retained `File`.
- Canonical independent editor state while switching items.
- Switching during preview, mutation, and export completion.
- Removing the selected item while its preview is pending.
- A mutation response updating its originating unselected item.
- Preview identity invalidation across item selection and revisions.
- Touch scheduling, page visibility touch, suspended-timer expiration handling, and a deliberately slow ten-item queue.
- Expiration racing preview, mutation, and export completion with operation invalidation and URL cleanup.
- Unmount cleanup with queued, ready, uncertain, and processing items together.
- Single-file regression behavior.
- Semantic queue controls, `aria-current`, accessible Retry/Remove names, restrained live announcements, deterministic removal focus, and no focus stealing.
- Mobile queue/editor layout plus keyboard and screen-reader focus order, including keyboard-triggered Remove and Retry replacement.

Backend tests cover:

- Twelve-job count capacity and rejection beyond it; ten retained jobs remain subject to configured disk, byte, pixel, and memory quotas.
- Ten simultaneously retained jobs with independent status, preview, export, touch, mutation, and deletion.
- Touch refreshing last access without rendering or mutating image data.
- Touch `404`/`410` behavior and cleanup races.
- Atomic cancel of unknown, creating, live, and terminal IDs, including cancel before a substantially delayed reservation.
- Distinct `202 cleanup_pending` and `204 cleanup complete` behavior, durable backend quarantine retry, and process-lifetime bounded tombstones that are never evicted.
- Existing single-job behavior and limits not related to live-job count.

Verification includes full backend/frontend suites, production build, dependency audit, and a real browser smoke test with multiple photos: sequential processing, queue switching, refining one result, expiration-safe touches, and individual exports.

## Acceptance Criteria

- A user can choose two to ten supported photos in one action.
- Processing is strictly sequential and advances automatically.
- Ten ordinary supported jobs that fit configured resource quotas can remain live and independently editable; capacity backpressure preserves queued work when quotas or other tabs consume capacity.
- One failure does not block later photos.
- Write-ahead-persisted lost responses and stale successes cannot duplicate or silently orphan jobs during a recoverable browser session.
- Every successful photo remains independently refinable and exportable while the active batch lease is maintained.
- Switching does not leak editor state, preview readiness, responses, or errors between items.
- Retry, remove, reset, component remount, and stale completion cleanup act on intended IDs through the session-backed ledger; hard browser termination may rely on backend TTL.
- Queue thumbnails have bounded retained memory, one-at-a-time decode attempts, and a safe placeholder path for large files.
- Queue interaction is keyboard and screen-reader accessible without focus theft.
- Selecting one photo still behaves like the existing single-image workflow.
- The implementation passes all existing and new tests plus a real multi-photo UI smoke test.
