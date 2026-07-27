# Background Studio Batch Uploads Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe sequential upload of up to ten photos while preserving independent per-photo refinement, export, cleanup, and the existing single-photo workflow.

**Architecture:** Keep the backend job-oriented and serialized. Add touch/cancel lifecycle contracts, then place frontend batch/editor state behind a pure reducer, bounded thumbnail helpers, and an accessible queue component. `App.jsx` orchestrates effects but never copies editor state between items; every async completion is attributed by batch, item, job, generation, and operation sequence.

**Tech Stack:** FastAPI, Python 3.12, pytest, React 19, Vite, Vitest, Testing Library, browser APIs (`sessionStorage`, `createImageBitmap`, canvas, object URLs).

---

## File structure

- Modify `backend/app/config.py`: raise default live-job capacity and tombstone registry bound.
- Modify `backend/app/store.py`: add touch, atomic cancel, cleanup-pending detection, and per-job quarantine retry.
- Modify `backend/app/main.py`: expose touch and cancel routes.
- Modify `backend/tests/test_app.py`: public API lifecycle, capacity, delayed-create, quarantine, and ten-job tests.
- Create `frontend/src/batchState.js`: pure reducer, item/editor defaults, guarded actions, cleanup-ledger persistence helpers.
- Create `frontend/src/batchState.test.js`: reducer and ledger race coverage.
- Create `frontend/src/imageHeaders.js`: bounded JPEG/PNG/WebP dimension parsing.
- Create `frontend/src/thumbnails.js`: one-at-a-time bounded thumbnail generation and disposal.
- Create `frontend/src/thumbnails.test.js`: unsafe-image and URL-lifecycle tests.
- Create `frontend/src/BatchQueue.jsx`: semantic queue, status, navigation, retry/remove/resume controls.
- Create `frontend/src/BatchQueue.test.jsx`: accessibility and focus tests.
- Modify `frontend/src/App.jsx`: sequential orchestration, selected-item editor binding, per-item preview/mutation/export ownership, keepalive, reset, cleanup reconciliation.
- Modify `frontend/src/App.test.jsx`: integration and single-image regression coverage.
- Modify `frontend/src/styles.css`: desktop/mobile queue layout and active/error/progress states.
- Modify `README.md`: document one-to-ten-photo workflow and active-session retention behavior.

## Chunk 1: Backend lifecycle foundation

### Task 1: Capacity and touch contract

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/store.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_app.py`

- [ ] Add failing API tests proving the default settings admit twelve live slots and ten retained fixtures can each be queried independently.
- [ ] Run the new tests and confirm failure against the current eight-job default.
- [ ] Change `Settings.max_jobs` and environment fallback from `8` to `12`; set the default terminal registry maximum to `4096` and preserve environment overrides.
- [ ] Add a failing test for `POST /api/jobs/{id}/touch`: live returns `204` and advances `last_access`; unknown returns `404`; tombstoned returns `410`; no image/render method runs.
- [ ] Add `JobStore.touch(job_id)` using the store lock and lifecycle checks, then expose the route through `run_in_threadpool`.
- [ ] Lock the existing lightweight `GET /api/jobs/{id}` reconciliation contract with public tests: `200 ready`, `202 creating`, `410 failed/tombstoned`, and `404 unknown`. Unknown never authorizes Retry without a subsequent cancel proof.
- [ ] Add a public-route concurrency test using a blocking fake remover and simultaneous create requests; assert maximum model-call concurrency is exactly one through success, failure, and cancellation.
- [ ] Run focused backend tests, then commit `Add batch job capacity and touch lease`.

### Task 2: Atomic cancellation and physical cleanup status

**Files:**
- Modify: `backend/app/store.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_app.py`

- [ ] Add a failing test where canceling an unknown preallocated ID returns `204`, a substantially delayed create with that ID returns terminal `410`, and the tombstone consumes no live-job slot.
- [ ] Add failing tests for canceling creating, live, and already-terminal IDs.
- [ ] Add a failing quarantine test: filesystem deletion failure terminalizes commit, returns `202 cleanup_pending`, permits a new ID, then a later cancel retry returns `204` after physical cleanup.
- [ ] Implement `JobStore.cancel(job_id)` returning `"complete"` or `"cleanup_pending"`. Under `_changed`, first establish irreversible terminality for unknown, creating, and live IDs; perform filesystem cleanup outside the global store lock; then publish physical-cleanup state. Retry only quarantines belonging to that ID.
- [ ] Enforce this public state table for every syntactically valid ID: unknown/terminal-clean/repeated-clean → `204`; active creation/render lease or quarantine → `202`; live job cleaned successfully → `204`; live job terminalized with failed physical cleanup → `202`. Cancel never returns semantic `404/410` for a valid ID.
- [ ] Keep `_used_job_ids` as the single bounded process-lifetime tombstone/admission registry. Never evict entries; once its configured 4096 bound is full, block both new admission and unknown-ID cancellation with machine-readable `507 {cause: "terminal_registry"}` until process restart.
- [ ] Return machine-readable `507` causes from admission: `live_capacity`, `disk_quota`, `memory_quota`, or `terminal_registry`. Only the first three may expose Resume after the attempted ID reaches cancel `202/204`; terminal-registry exhaustion blocks admission and requires a controlled backend restart.
- [ ] Add a blocking public preview/export lease test: cancel returns `202`, no create can publish, lease release enables cleanup, and repeated cancel returns `204`.
- [ ] Run focused cancellation tests and full backend tests.
- [ ] Commit `Add atomic batch job cancellation`.

## Chunk 2: Pure frontend state and thumbnail safety

### Task 3: Reducer and write-ahead cleanup ledger

**Files:**
- Create: `frontend/src/batchState.js`
- Create: `frontend/src/batchState.test.js`

- [ ] Add one failing reducer test for a two-item batch: item A and B retain independent editor settings and selecting B does not modify A.
- [ ] Implement `createBatchItem(file, batchGeneration)`, `createInitialBatchState()`, `defaultEditorState()`, and `batchReducer(state, action)` with immutable item maps and ordered IDs.
- [ ] Add guarded action tests for stale batch/item/job/operation sequences, including mutation and preview completion for an unselected item. Selection alone does not invalidate item-owned work; parameter/revision/generation changes do. Deselect may abort without recording an error.
- [ ] Implement item-owned preview/mutation/export/touch state and operation sequence increments.
- [ ] Add failing ledger tests proving synchronous persistence occurs before the caller may dispatch a create request, storage failure blocks admission, old-batch ledger actions survive a new visible batch, and `202` commit-terminal entries remain until `204` cleanup completion.
- [ ] Implement `readCleanupLedger`, `writeCleanupEntry`, `updateCleanupEntry`, and `removeCleanupEntry` with schema/version validation and synchronous `sessionStorage` writes.
- [ ] Make malformed/unsupported-version storage fail closed: preserve the raw value, block admission, and surface a recovery error rather than replacing it with an empty ledger. Add tests for restored entries, corruption, and independent ledger-entry guards.
- [ ] Add App-level tests proving `sessionStorage.setItem` completes before POST fetch, storage exceptions produce zero POSTs, updates re-read latest storage so unrelated entries cannot be lost, `202` permits a new generation while retaining the old entry, and only `204` removes it.
- [ ] Run reducer tests and commit `Add batch state and cleanup ledger`.

### Task 4: Safe thumbnail helpers

**Files:**
- Create: `frontend/src/imageHeaders.js`
- Create: `frontend/src/thumbnails.js`
- Create: `frontend/src/thumbnails.test.js`

- [ ] Add failing public-helper tests for bounded header parsing of PNG, JPEG SOF, WebP VP8/VP8L/VP8X, malformed/truncated data, and small-byte extreme dimensions.
- [ ] Implement `readImageDimensions(file, maxHeaderBytes)` without full decode.
- [ ] Add failing tests proving files over 8 MiB, over 20 megapixels, malformed headers, and unknown dimensions return a placeholder without calling `createImageBitmap`.
- [ ] Implement `createBoundedThumbnail(file)` with concurrency-one scheduling, EXIF-aware `createImageBitmap` resize hints, a 192×192 no-upscale canvas, compressed blob output, immediate bitmap/canvas cleanup, and deterministic placeholder fallback.
- [ ] Add tests for revoking temporary and retained URLs on replace/remove/reset/unmount.
- [ ] Run thumbnail tests and commit `Add memory-safe batch thumbnails`.

## Chunk 3: Accessible queue and App orchestration

### Task 5: Semantic batch queue

**Files:**
- Create: `frontend/src/BatchQueue.jsx`
- Create: `frontend/src/BatchQueue.test.jsx`
- Modify: `frontend/src/styles.css`

- [ ] Add a failing test for semantic list items, filename/status text, named Select/Retry/Remove/Resume controls, `aria-current`, and a non-color active indicator.
- [ ] Implement the queue as a presentational component driven entirely by props and callbacks.
- [ ] Add failing keyboard tests for selected-item removal, focused unselected removal, and Retry control replacement; assert deterministic next/previous/selected/heading focus fallback.
- [ ] Implement focus fallback with item/action refs and no automatic focus movement when background processing completes.
- [ ] Add one restrained polite live-region summary and tests preventing per-render announcement spam.
- [ ] Add responsive styles: horizontal scroll/compact cards on mobile, queue plus editor on desktop, no overflow at 320px.
- [ ] Run queue tests and commit `Add accessible batch queue`.

### Task 6: Sequential upload tracer bullet

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.test.jsx`

- [ ] Add one failing integration test: selecting two files sends only item A, waits for its terminal result, then sends item B; both appear ready; item A is not deleted when B completes.
- [ ] Add an 11-file admission test proving the UI creates at most ten items, ledger entries, thumbnails, and POSTs. Document that backend capacity is twelve only for cleanup/reconciliation headroom.
- [ ] Replace global persistent editor state with `useReducer(batchReducer, ...)`; derive `selectedItem`, `job`, editor settings, and busy flags from the selected item.
- [ ] Keep pointer-only ephemeral drawing state local to the visible canvas.
- [ ] Change chooser/drop handling to accept up to ten files, construct items in order, synchronously write each preallocated cleanup entry immediately before its POST, and schedule exactly one create/reconcile at a time.
- [ ] Preserve paste as a one-file batch and preserve the compact single-item workflow.
- [ ] Handle validation/inference failure per item and continue later queued work.
- [ ] Run the complete frontend suite and production build before committing; Tasks 6–8 must never leave a knowingly broken intermediate editor state. Commit `Add sequential batch processing` only when broad checks are green.

### Task 7: Reconciliation, cancellation, backpressure, reset, and keepalive

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.test.jsx`

- [ ] Add a failing lost-response test for present, creating, unknown, `202 cleanup_pending`, and `204 complete` outcomes; Retry remains disabled until commit terminality.
- [ ] Implement bounded foreground reconciliation and cancel; transfer unresolved work to background `cleanup-pending` without stalling later items when capacity permits.
- [ ] Add failing `507` tests for every machine-readable cause. Prove the attempted ID is reconciled/canceled, automatic retries do not spin, recoverable Resume allocates a new item generation/job ID, and `terminal_registry` blocks admission without Resume until restart.
- [ ] Implement server-authoritative capacity pause and cause-aware manual Resume.
- [ ] Add reset-during-inference and stale-success tests; implement generation invalidation plus compensating cancellation independent of visible-batch guards.
- [ ] Add reload/session-ledger restoration and multi-ID cleanup tests.
- [ ] Add fake-timer tests for sequential five-minute touches and visibility touches; `404/410` expiration invalidates preview/mutation/export sequences and enables safe retry from the retained File.
- [ ] Run focused lifecycle tests and commit `Harden batch lifecycle recovery`.
- [ ] Before this and every App orchestration commit, run the complete frontend suite and production build.

### Task 8: Per-item editing, preview, mutation, and export ownership

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.test.jsx`

- [ ] Add a failing integration test that changes item A threshold/background/brush settings, switches to B, changes B, and returns to unchanged A settings.
- [ ] Route every persistent editor control directly to the selected item in the reducer; never save/copy state during selection.
- [ ] Add preview race tests for switch/remove/revision/expiration. Bind preview identity to batch/item/itemGeneration/job/parameters/revision/request sequence; revoke prior and rejected URLs.
- [ ] Add mutation race tests proving an unselected originating item receives its revision/stroke count and the selected item remains unchanged.
- [ ] Add export race tests proving downloads/errors remain attributed to the originating item and expiration cancels completion.
- [ ] Add Previous/Next ready-item navigation and per-item Retry/Remove wiring.
- [ ] Run focused editing tests and all frontend tests; commit `Preserve independent batch refinements`.
- [ ] Run the production build before committing.

## Chunk 4: Documentation, verification, and production

### Task 9: Documentation and broad verification

**Files:**
- Modify: `background-studio/README.md`
- Modify as needed only from failures: files already listed above

- [ ] Document selecting up to ten files, sequential processing, per-photo refinement, individual export, storage/capacity behavior, and active-tab lease limitations.
- [ ] Run focused backend tests.
- [ ] Resolve or create the monorepo app's own Python 3.12 environment. Print `sys.executable`, Python version, and `app.__file__` to prove tests import this checkout; use this exact environment for tests and production.
- [ ] Run that interpreter's `python -m pytest -q backend/tests` and preserve the exact pass count.
- [ ] Run `npm test`, `npm run build`, and `npm audit --audit-level=low` from `frontend/` and preserve exact results.
- [ ] Run `git diff --check`; inspect `git diff --stat` and all changed paths; confirm no `vendoo-studio`, secrets, generated assets, models, caches, or runtime files are staged.
- [ ] Commit `Document Background Studio batch uploads`.

### Task 10: Real multi-photo browser smoke and review loop

**Files:**
- No production edits unless a verified failure requires returning to the relevant TDD task.

- [ ] Start isolated backend and frontend ports with a temporary root; leave existing port 8000 service untouched until promotion.
- [ ] Use at least three distinct local photos through the real model. Verify sequential state changes, queue selection, independent editor settings, one brush refinement, Previous/Next, transparent PNG, solid JPEG, and New batch cleanup.
- [ ] Add real Playwright checks at 320px for horizontal overflow and keyboard focus after DOM replacement, plus a rotated JPEG thumbnail fixture to verify browser orientation/canvas behavior.
- [ ] Add a public TTL test proving touched jobs survive while an untouched control job expires.
- [ ] Validate downloaded file formats, dimensions, alpha/color modes, health job count, closed temporary ports, and removed temporary root.
- [ ] Send the exact final diff and test evidence to a fresh ChatGPT commit review. Route actionable findings back to implementation and reverify.
- [ ] Send the final corrected diff to a separate independent review. Resolve blockers and reverify.
- [ ] Commit any review fixes with focused messages.

### Task 11: Push and production promotion

**Files:**
- Existing deployment helper: `background-studio/scripts/start-private-tailnet.sh`

- [ ] Push `feat/background-studio-batch-uploads` and verify local/remote commit hashes match.
- [ ] Inspect the current production process and private Tailscale Serve configuration without interrupting it.
- [ ] Record the current production commit, process command, environment, ports, Tailscale Serve configuration, and exact rollback command before cutover.
- [ ] Run the repository preflight and validate the launch helper syntax/config.
- [ ] Start and smoke-test the candidate beside production first. Switch private routing only after candidate health passes; retain the old process until post-cutover verification completes. Never enable public Funnel.
- [ ] Verify production health through loopback and the private Tailscale URL.
- [ ] Run a final two-photo production smoke: sequential removal, item switching, one refinement, PNG/JPEG export, and cleanup returning production health to zero jobs.
- [ ] If any post-cutover check fails, execute the recorded routing/process rollback immediately and verify the prior production health endpoint before continuing fixes.
- [ ] Record exact production URL, process identity, branch/commit, tests, and smoke evidence.
