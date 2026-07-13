# Vendoo Listing Studio Specification

## 1. Objective

Create a purpose-built local web application that lets the user:

1. Add product photos and optional notes.
2. Chat with Xiaomi MiMo about the item.
3. Generate a complete Vendoo-compatible listing.
4. Review and revise the listing conversationally.
5. Edit individual fields or raw JSON directly.
6. Validate the approved listing.
7. Click **Send to Vendoo**.
8. Have the Chrome extension open a new Vendoo listing, upload the approved photos, fill and verify the general form, and fill and verify each selected marketplace.
9. Watch progress and retry failed steps from the web app.

The system is local-only, intended for one user and one active listing job at a time, and must always stop before publication.

## 2. Product Decisions

### Confirmed

- Purpose-built interface, not a T3 Code or LibreChat fork.
- React and TypeScript frontend.
- FastAPI Python backend.
- SQLite persistence.
- Xiaomi MiMo API.
- `mimo-v2.5` for multimodal photo analysis.
- `mimo-v2.5-pro` for listing synthesis, chat, and revisions.
- macOS Keychain for API-key storage.
- Chrome extension controls Vendoo.
- Draft saving only; never publish automatically.
- Human approval required before sending to Vendoo.
- Existing extension popup remains as a manual fallback.
- One automation job runs at a time.

### Security Decision

The API key previously posted in chat must be rotated. It must not be committed, written to SQLite, included in logs, returned to the frontend, or sent to the extension. The replacement key will be entered through the application's local Settings page.

## 3. System Architecture

```text
Vendoo Listing Studio (http://127.0.0.1:4318)
├── React frontend
│   ├── Listing library
│   ├── Photo workspace
│   ├── MiMo chat
│   ├── Structured listing and JSON editors
│   ├── Validation
│   └── Automation progress
├── FastAPI backend
│   ├── MiMo provider
│   ├── Listing rules and schema
│   ├── Conversation and revision service
│   ├── Photo storage
│   ├── SQLite repository
│   ├── Keychain service
│   ├── Job orchestrator
│   └── Authenticated WebSocket server
└── Chrome extension
    ├── Reconnecting WebSocket client
    ├── Durable active-job state
    ├── Vendoo tab creation
    ├── Sequential step runner
    └── Vendoo content-script fill, save, and audit operations
```

The frontend communicates with FastAPI through HTTP and Server-Sent Events. The extension connects to FastAPI through an authenticated loopback WebSocket. API keys never leave the backend process.

## 4. Proposed Repository Structure

Add a new application at the workspace root:

```text
vendoo-studio/
├── README.md
├── pyproject.toml
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx
│   ├── app/
│   │   ├── App.tsx
│   │   ├── router.tsx
│   │   └── query-client.ts
│   ├── api/
│   │   ├── client.ts
│   │   ├── conversations.ts
│   │   ├── listings.ts
│   │   ├── jobs.ts
│   │   └── settings.ts
│   ├── components/
│   │   ├── AppShell.tsx
│   │   ├── PhotoTray.tsx
│   │   ├── ChatPanel.tsx
│   │   ├── ChatComposer.tsx
│   │   ├── ListingEditor.tsx
│   │   ├── JsonEditor.tsx
│   │   ├── ValidationPanel.tsx
│   │   ├── ExtensionStatus.tsx
│   │   └── JobProgress.tsx
│   ├── features/
│   │   ├── conversations/
│   │   ├── listings/
│   │   ├── automation/
│   │   └── settings/
│   ├── styles/
│   │   ├── tokens.css
│   │   └── app.css
│   └── types/api.ts
├── server/vendoo_studio/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── conversation.py
│   │   ├── listing.py
│   │   ├── job.py
│   │   └── protocol.py
│   ├── repositories/
│   │   ├── conversations.py
│   │   ├── listings.py
│   │   └── jobs.py
│   ├── services/
│   │   ├── keychain.py
│   │   ├── photos.py
│   │   ├── listing_rules.py
│   │   ├── listing_generator.py
│   │   ├── listing_revisions.py
│   │   └── extension_gateway.py
│   ├── providers/xiaomi_mimo.py
│   └── routes/
│       ├── conversations.py
│       ├── listings.py
│       ├── photos.py
│       ├── jobs.py
│       ├── settings.py
│       ├── events.py
│       └── extension.py
└── tests/
    ├── server/
    └── frontend/
```

Do not add Redis, MongoDB, Celery, Docker, or a cloud backend in version 1.

## 5. Frontend Specification

### Main Layout

Desktop uses three resizable columns:

```text
┌───────────────┬──────────────────────────┬──────────────────────┐
│ Listings      │ Photos and Chat          │ Listing              │
│ Search        │ Photo thumbnails         │ General              │
│ Recent items  │ Conversation             │ Marketplace tabs     │
│ Job status    │ Chat composer            │ JSON and validation  │
│ + New listing │                          │                      │
├───────────────┴──────────────────────────┴──────────────────────┤
│ Extension connected · Valid listing        [Send to Vendoo]    │
└────────────────────────────────────────────────────────────────┘
```

Mobile and narrow screens use Photos, Chat, Listing, and Automation tabs.

### Visual Direction

- Purpose-built professional workspace.
- Dense enough for daily operational use.
- T3 Code-inspired information hierarchy, not a visual clone.
- Neutral dark or warm-gray shell with marketplace colors used sparingly.
- Monospace typography only for JSON and technical status.
- Avoid generic dashboard cards and excessive rounded containers.
- Persistent status bar for extension and validation state.
- Fully usable desktop and mobile layouts.

### Listing Library

- Create a new listing.
- Search by title, brand, SKU, or job ID.
- Filter by draft, ready, sending, completed, and failed status.
- Show last-updated time and completed Vendoo draft link.

### Workspace

- Drag-and-drop multiple photos.
- File picker and folder picker where browser support allows it.
- Reorder and remove photos before approval.
- Image preview.
- Notes, cost, SKU, labels, measurements, and package-dimensions inputs.

### Chat

- Stream model responses.
- Include uploaded images in conversation context.
- Support generation and revision instructions.
- Display model changes as a field diff.
- Allow accepting, undoing, and restoring revisions.
- Ask the user when brand or category remains uncertain instead of guessing.

### Listing Editor

Tabs:

- General
- eBay
- Poshmark
- Mercari
- Depop
- Etsy
- Raw JSON

Requirements:

- Friendly structured inputs.
- Required-field indicators and inline validation.
- Marketplace-specific field groups.
- Syntax-highlighted raw JSON editing.
- Valid JSON edits update the structured editor.
- Invalid JSON cannot overwrite the last valid listing.
- Revision history and restore action.

### Send Controls

**Send to Vendoo** is enabled only when:

- The extension is connected.
- The listing passes validation.
- Required photos are present.
- No critical uncertainty remains unresolved.
- No automation job is active.
- The user confirms an immutable listing snapshot.

The confirmation shows the title, photo count, selected marketplaces, draft-only behavior, and the no-publish guarantee.

### Automation Progress

```text
✓ Vendoo opened
✓ Photos uploaded and verified: 7
✓ General form saved and audited
✓ eBay saved and audited
● Poshmark filling
○ Mercari
○ Depop
○ Etsy
```

Failures show the failed field or section, evidence, last error, retry action, cancel action, and any available Vendoo draft link.

## 6. Backend Specification

### Runtime

- Bind only to `127.0.0.1`.
- Default port: `4318`.
- Serve the built React frontend from FastAPI in production.
- Use Vite with an API proxy during development.
- Provide one documented startup command.

### Dependencies

Python:

- FastAPI
- Uvicorn
- Pydantic
- SQLAlchemy or SQLModel
- SQLite driver
- `keyring`
- `httpx`
- `python-multipart`
- Pillow

Frontend:

- React
- TypeScript
- Vite
- TanStack Query
- Accessible local components
- Monaco Editor only if its complexity remains justified

### API Endpoints

```text
GET    /api/health
GET    /api/status

GET    /api/settings/provider
PUT    /api/settings/provider
POST   /api/settings/provider/test
DELETE /api/settings/provider/key

POST   /api/conversations
GET    /api/conversations
GET    /api/conversations/{conversation_id}
POST   /api/conversations/{conversation_id}/messages

POST   /api/conversations/{conversation_id}/photos
DELETE /api/conversations/{conversation_id}/photos/{photo_id}
PATCH  /api/conversations/{conversation_id}/photos/order
GET    /api/photos/{photo_id}

GET    /api/conversations/{conversation_id}/listing
PUT    /api/conversations/{conversation_id}/listing
POST   /api/conversations/{conversation_id}/listing/validate
GET    /api/conversations/{conversation_id}/revisions
POST   /api/conversations/{conversation_id}/revisions/{revision_id}/restore

POST   /api/jobs
GET    /api/jobs
GET    /api/jobs/{job_id}
POST   /api/jobs/{job_id}/retry
POST   /api/jobs/{job_id}/cancel
GET    /api/jobs/{job_id}/events
GET    /api/jobs/{job_id}/photos/{photo_id}

WS     /api/extension/ws
```

Provider responses return only masked configuration:

```json
{
  "provider": "xiaomi-mimo",
  "configured": true,
  "maskedKey": "sk-...4K9P",
  "visionModel": "mimo-v2.5",
  "listingModel": "mimo-v2.5-pro"
}
```

## 7. Listing Generation Pipeline

### Stage 1: Photo Analysis

Use `mimo-v2.5` to produce structured evidence rather than listing copy.

Input:

- Ordered product photos.
- User notes.
- Extraction instructions derived from `skills/list-this/SKILL.md`.

Output example:

```json
{
  "brand": {
    "value": "Levi's",
    "confidence": 0.98,
    "evidencePhotoIds": ["photo-2"]
  },
  "size": {
    "value": "M",
    "source": "tag",
    "confidence": 0.96
  },
  "condition": {
    "value": "Pre-Owned - Good",
    "visibleFlaws": ["Small mark on left sleeve"]
  },
  "measurements": [],
  "uncertainties": []
}
```

The model must separate visible facts from inference, identify tag evidence, flag disagreements, avoid invented details, and use measurement-derived sizing only under the existing skill rules.

### Stage 2: Listing Synthesis

Use `mimo-v2.5-pro` with:

- Structured photo evidence.
- User notes.
- Current listing rules.
- Vendoo JSON schema.
- Marketplace value constraints.
- Conversation instructions.

The output contains a user-facing response, complete proposed listing, uncertainties, and validation warnings.

### Stage 3: Revision

Chat revisions produce a patch rather than silently replacing the listing:

```json
{
  "message": "I shortened the title and changed the price.",
  "listingPatch": [
    {"op": "replace", "path": "/title", "value": "..."},
    {"op": "replace", "path": "/price", "value": 45}
  ]
}
```

The server applies the patch, validates the complete result, stores a revision, returns a diff, and preserves the previous valid revision.

### Listing Rules Source

The editorial policy remains in:

- `skills/list-this/SKILL.md`
- `skills/list-this/references/vendoo_listing_template.md`

`listing_rules.py` loads or packages the relevant rules. The Pydantic schema is the canonical machine-readable contract; the skill remains the canonical editorial policy.

## 8. Listing Schema

Define the complete schema in `vendoo-studio/server/vendoo_studio/models/listing.py` and generate frontend TypeScript types from OpenAPI.

```json
{
  "title": "...",
  "description": "...",
  "price": 45,
  "cost": 8,
  "quantity": 1,
  "brand": "...",
  "condition": "...",
  "primaryColor": "...",
  "secondaryColor": "...",
  "category_path": "...",
  "size": "...",
  "sizeType": "...",
  "tags": [],
  "labels": [],
  "weight_lb": 0,
  "weight_oz": 8,
  "package_dimensions_in": "13x10x3",
  "internal_notes": "...",
  "ebay_specifics": {},
  "poshmark_specifics": {},
  "mercari_specifics": {},
  "depop_specifics": {},
  "etsy_specifics": {}
}
```

Validation levels:

- **Error:** blocks Send to Vendoo.
- **Warning:** requires acknowledgement.
- **Information:** quality recommendation.

Blockers include missing core listing fields, missing required photos, invalid marketplace values, unresolved brand/category conflicts, malformed dimensions, and invalid JSON.

## 9. Persistence Model

SQLite tables:

### `conversations`

- ID, title, status, notes, and timestamps.

### `messages`

- ID, conversation ID, role, text, provider/model, and timestamp.

### `photos`

- ID, conversation ID, original/stored filename, MIME type, size, display order, SHA-256 checksum, and timestamp.

### `listings`

- Conversation ID, current revision ID, validation status, and timestamp.

### `listing_revisions`

- ID, conversation ID, listing JSON, source, parent revision ID, and timestamp.

### `jobs`

- ID, conversation ID, approved revision ID, immutable listing snapshot, status, current step, Vendoo item ID/URL, attempts, last error, and timestamps.

### `job_events`

- ID, job ID, sequence number, type, step, payload, and timestamp.

API keys must not appear in any table.

## 10. Extension Protocol

### Connection

The background service worker connects to:

```text
ws://127.0.0.1:4318/api/extension/ws
```

- The backend generates a local pairing token.
- The extension stores it in `chrome.storage.local`.
- The server permits one active extension connection.
- Heartbeats keep the MV3 worker active while connected.
- Reconnection uses bounded exponential backoff.

### Message Envelope

```json
{
  "version": 1,
  "type": "job.start",
  "messageId": "uuid",
  "jobId": "uuid",
  "sentAt": "ISO-8601",
  "payload": {}
}
```

Server-to-extension messages:

- `connection.accepted`
- `job.start`
- `job.retry`
- `job.cancel`
- `ping`

Extension-to-server messages:

- `extension.ready`
- `job.accepted`
- `job.progress`
- `job.step_completed`
- `job.step_failed`
- `job.cancelled`
- `job.completed`
- `pong`

### Idempotency

- Job IDs are unique.
- Extension persists active and completed job IDs.
- Repeated starts return current state instead of creating another listing.
- Retry resumes at an explicit step.
- Approved listing snapshots cannot change during execution.

## 11. Automation State Machine

```text
queued
awaiting_extension
dispatched
opening_vendoo
waiting_for_vendoo
uploading_photos
filling_general
saving_general
auditing_general
filling_ebay
saving_ebay
auditing_ebay
filling_poshmark
saving_poshmark
auditing_poshmark
filling_mercari
saving_mercari
auditing_mercari
filling_depop
saving_depop
auditing_depop
filling_etsy
saving_etsy
auditing_etsy
completed
failed
cancelled
```

Field states follow the existing direct-flow contract:

```text
not_started
attempted_unverified
visibly_committed
persisted_after_save
audited_complete
blocked_with_evidence
```

No section is complete when values were merely typed. Completion requires visible committed values after save.

## 12. Existing Extension Changes

### `vendoo-extension/manifest.json`

- Add the minimum tab permission needed for deterministic tab creation and querying.
- Add loopback host access for `http://127.0.0.1:4318/*` and the local WebSocket.
- Keep existing Vendoo and marketplace permissions.
- Update name, version, and description for Studio integration.
- Do not add `<all_urls>`.

### `vendoo-extension/background.js`

Add:

- Existing popup-message compatibility.
- WebSocket lifecycle and pairing.
- Active-job persistence and idempotency.
- Vendoo tab creation or controlled reuse.
- Vendoo readiness polling.
- Sequential step execution.
- Timeouts, retries, progress forwarding, and restart recovery.

Suggested functions:

```text
connectToStudio()
handleStudioMessage()
acceptJob()
openVendooListing()
waitForContentScript()
runJob()
runStep()
sendProgress()
restoreActiveJob()
```

The current `startVendooFill()` assumption that a listing tab already exists must not apply to Studio jobs.

### `vendoo-extension/content-scripts/vendoo.js`

Replace the single broad fill command with explicit operations:

```text
UPLOAD_PHOTOS
FILL_GENERAL
SAVE_GENERAL
AUDIT_GENERAL
FILL_MARKETPLACE
SAVE_MARKETPLACE
AUDIT_MARKETPLACE
GET_PAGE_STATE
```

Required changes:

- Upload through `#imageInput`.
- Fetch authorized job photos from the backend.
- Preserve photo ordering and verify visible upload count.
- Fill category path.
- Fill SKU only when explicitly supplied.
- Return structured field results.
- Separate filling, saving, and auditing.
- Detect validation blockers and pending search text.
- Verify committed chips, tokens, and selected options.
- Capture Vendoo item ID and URL after general save.
- Remove unconditional success when a fill function merely returns.
- Stop calling `clickSave()` from marketplace fill functions.

Structured result example:

```json
{
  "ok": false,
  "step": "audit_ebay",
  "fields": {
    "brand": {
      "state": "audited_complete",
      "expected": "Levi's",
      "observed": "Levi's"
    },
    "features": {
      "state": "attempted_unverified",
      "expected": ["Comfortable", "Lightweight"],
      "observed": ["Comfortable"]
    }
  },
  "error": "One eBay feature did not persist after save"
}
```

### `vendoo-extension/popup.html` and `popup.js`

- Add Studio connection status.
- Add pairing/unpairing controls.
- Show active job summary and last error.
- Add Open Studio action.
- Preserve manual JSON and platform controls as fallback behavior.

### Documentation

Update:

- `vendoo-extension/README.md`
- `vendoo-extension/TROUBLESHOOTING.md`
- Root `README.md`

Direct marketplace scripts are not part of the primary Studio flow and should remain unchanged unless testing proves a concrete dependency.

## 13. Save and Audit Requirements

The existing `clickSave()` behavior is insufficient because clicking a likely button does not prove persistence.

A save succeeds only when:

1. Save begins.
2. Loading completes.
3. No validation error is visible.
4. Vendoo confirms success or reaches stable persisted state.
5. The form is re-read after save.
6. Expected fields remain visibly committed.
7. Token fields show committed pills.
8. Dropdown fields show closed committed values.
9. No transient search text remains.
10. General save produces a stable Vendoo item ID.

If audit fails, report mismatched fields, return the section to `attempted_unverified`, retry with a stricter interaction, save again, audit again, and fail with evidence after bounded retries.

## 14. Photo Handling

### Storage

- Copy uploads into an app-managed directory.
- Generate safe internal filenames.
- Store original names as metadata.
- Verify MIME type and actual format.
- Reject unsupported or oversized files.
- Never expose arbitrary filesystem paths.

### Model Input

- Preserve original uploads.
- Generate resized inference copies if needed.
- Correct EXIF orientation.
- Send ordered photos to `mimo-v2.5`.

### Extension Transfer

- Create job-scoped signed photo URLs.
- Extension downloads bytes over loopback HTTP.
- Content script creates native `File` objects and assigns them through `#imageInput`.
- Wait for all Vendoo thumbnails to finish uploading.
- Audit count and order before continuing.

Use a Native Messaging host only if browser-based file assignment is tested and proven incompatible.

## 15. Security Requirements

- Bind only to `127.0.0.1`.
- Store MiMo API key in macOS Keychain.
- Redact authorization headers and secrets from logs.
- Never send the key to React or the extension.
- Never store the key in SQLite or browser storage.
- Use an explicit CORS allowlist.
- Validate HTTP and WebSocket origins.
- Require an extension pairing token.
- Use signed, expiring photo URLs.
- Restrict files to registered job assets.
- Reject path traversal.
- Limit upload size and count.
- Escape model output in the UI.
- Validate model JSON before persistence.
- Do not expose a publish command in protocol version 1.

## 16. Logging and Diagnostics

Backend logs may include request ID, conversation ID, job ID, step, duration, provider/model, token usage, and redacted errors.

Extension logs may include connection state, job ID, step transitions, retries, audit failures, and sanitized Vendoo URLs.

Do not log API keys, pairing tokens, authorization URLs, image bytes, base64 payloads, or full listing content by default.

Each failed job preserves a structured event history viewable in Studio.

## 17. Testing Strategy

### Backend Unit Tests

- Valid and invalid listing schemas.
- MiMo response parsing.
- Patch application and rollback.
- Mocked Keychain operations.
- Photo path traversal rejection.
- Signed-photo expiration.
- Job transition validation.
- Duplicate-job idempotency.

### Frontend Tests

- Photo upload, reorder, and removal.
- Streaming chat.
- Listing diff display.
- Structured editor and JSON synchronization.
- Invalid JSON preserving the last valid listing.
- Send-button enablement.
- Job progress and retry states.
- Full API key never displayed.

### Extension Tests

- Protocol message validation.
- Job transitions and retries.
- Idempotency.
- Field normalization and comparison.
- Save/audit aggregation.
- Tab creation and content-script readiness with mocked Chrome APIs.
- Worker restart recovery.

### End-to-End Tests

Mocked flow:

- Fake MiMo API.
- Fake extension WebSocket client.
- Generate, approve, dispatch, report progress, and complete.

Live Vendoo smoke test:

1. Use a disposable item.
2. Upload known photos.
3. Save and audit general fields.
4. Confirm stable Vendoo item ID.
5. Fill, save, and audit selected marketplaces.
6. Confirm no publish action occurred.

## 18. Implementation Milestones

### Milestone 1: Contracts and Foundation

- Create `vendoo-studio/`.
- Add FastAPI, React, SQLite, health endpoints, listing schema, and generated frontend types.
- Verify one command starts the app and data survives restart.

### Milestone 2: Settings and MiMo

- Add Keychain settings, MiMo connection test, multimodal analysis, Pro synthesis, and streaming chat.
- Verify photos produce evidence and Pro produces valid listing JSON.

### Milestone 3: Listing Workspace

- Add library, photo tray, chat, structured editor, JSON editor, validation, and revision history.
- Verify generation, revisions, direct edits, undo, and responsive behavior.

### Milestone 4: Extension Connection

- Add pairing, authenticated WebSocket, heartbeat, reconnect, durable jobs, and acknowledgements.
- Verify online status, duplicate prevention, and restart recovery.

### Milestone 5: Vendoo General Form

- Add automatic tab creation, readiness detection, photo upload, general fill/save/audit, and draft URL return.
- Verify a new persisted draft with the correct photo count and fields.

### Milestone 6: Marketplace Pipeline

- Implement sequential fill/save/audit/retry for eBay, Poshmark, Mercari, Depop, and Etsy.
- Verify each marketplace reaches `audited_complete` or `blocked_with_evidence`.

### Milestone 7: Recovery and Polish

- Add retry, cancellation, event history, draft links, diagnostics, documentation, and live smoke testing.
- Verify a failed step resumes without creating another Vendoo item.

## 19. Relevant Existing Files

- `README.md`: monorepo overview and Studio workflow.
- `skills/list-this/SKILL.md`: canonical listing-generation policy.
- `skills/list-this/references/vendoo_listing_template.md`: JSON and marketplace guidance.

- `skills/list-this/references/vendoo-extension-architecture.md`: current extension architecture.
- `vendoo-extension/manifest.json`: permissions and extension metadata.
- `vendoo-extension/background.js`: Studio connection and job orchestration.
- `vendoo-extension/content-scripts/vendoo.js`: photo upload and fill/save/audit operations.
- `vendoo-extension/popup.html`: pairing and Studio status.
- `vendoo-extension/popup.js`: pairing, status, and manual fallback.
- `vendoo-extension/sample-listing.json`: shared validation and automation fixture.
- `vendoo-extension/diagnostic-collector.js`: structured failure evidence where applicable.
- `vendoo-extension/README.md`: setup and workflow documentation.
- `vendoo-extension/TROUBLESHOOTING.md`: connection and automation troubleshooting.

## 20. Non-Goals for Version 1

- Automatic publication.
- Multi-user accounts.
- Cloud hosting.
- Native mobile application.
- Inventory management or sales analytics.
- Distributed workers.
- Multiple simultaneous automation jobs.
- LibreChat or T3 Code integration.
- Direct automation of native marketplace sites.
- Automatic comp research without a separately selected search provider.
- Native Messaging unless browser-based photo upload fails.
- A generalized provider framework beyond the small MiMo boundary.

## 21. Completion Criteria

Version 1 is complete when the user can:

1. Start the local application.
2. Configure a rotated Xiaomi MiMo key securely.
3. Upload and reorder product photos.
4. Generate a listing using MiMo V2.5 and V2.5 Pro.
5. Chat to revise the listing.
6. Edit structured fields or raw JSON.
7. Pass validation.
8. See that the extension is connected.
9. Click **Send to Vendoo**.
10. Have a new Vendoo draft created automatically.
11. Have photos and general fields saved and audited.
12. Have each selected marketplace saved and audited.
13. See live progress and actionable failures.
14. Retry a failed step without creating a duplicate item.
15. Open the completed Vendoo draft.
16. Confirm that no listing was published automatically.
