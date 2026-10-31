# Anteroom for iPhone

A native SwiftUI app on the hosted Anteroom API (`vendoo_studio.hosted:app`)
and Supabase, step 5 of [`docs/cloud-architecture.md`](../docs/cloud-architecture.md).

What works now: email-link sign-in, draft inventory with search, editing a
draft's title, notes and General fields, and adding photos from the camera or
library. The listing assistant connects native generation and text chat to the
hosted durable-task API when the server advertises generation and has a provider.
Marketplace tabs and publishing are not implemented on iPhone.

## Interface

The native screens follow the workspace's neutral light/dark surfaces, blue
accent, compact inventory rows, and bordered General editor fields. Sign-in
uses the hosted workspace's wording. General fields follow the canonical
`skills/list-this/references/listing-editor-fields.json` order and labels.
Photos, labels and private notes remain available alongside them.

This is the first visual alignment pass, not desktop feature parity. The
hosted API still does not expose generation or the full marketplace workflow.

## iPhone navigation

Inventory and Settings are native tabs, each with its own navigation stack.
New listing is a modal task, not a tab: Cancel writes nothing, Create runs
once while the sheet is busy, and success opens the new draft after dismissal.
Settings shows the signed-in account and installed version, with confirmation
before signing out. Inventory keeps its search and open listing across tabs.

Fields expose their labels to VoiceOver; price/cost and photo controls stack
at accessibility text sizes. Photo deletion is a visible action with
confirmation, rather than a long-press-only gesture. Photos save immediately;
listing text still saves with Save.

Device review: check tab switching with an open edited draft, Cancel/Create
(including a failed request and retry), the largest accessibility text size,
VoiceOver field labels, photo add/delete, and light/dark appearance.

## Build on a Mac

Needs Xcode 16 or newer and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```sh
brew install xcodegen
cd anteroom-ios
cp Config/Local.xcconfig.example Config/Local.xcconfig   # add the publishable key and your team ID
xcodegen
open Anteroom.xcodeproj
```

The Xcode project is generated from `project.yml` and not tracked. Change
`project.yml`, never the generated project, and run `xcodegen` again.

## Sign-in

The app asks Supabase to email a link that opens `anteroom://login-callback`.
Add that URL to the Supabase project's **Auth → URL Configuration → Redirect
URLs**, or the link will open the web app instead. Open the link on the same
iPhone that asked for it.

## CI and TestFlight

`.github/workflows/ios.yml` builds for the Simulator on every change under
`anteroom-ios/`. On `main` (or when run by hand from the Actions tab) it also
archives, signs and uploads the build to TestFlight, numbered by the workflow
run. Install it on the iPhone from the TestFlight app.

Signing uses an App Store Connect API key (Admin role) stored as the
repository secrets `ASC_KEY_ID`, `ASC_ISSUER_ID` and `ASC_KEY_P8`; Xcode
creates and renews the certificate and profile with it. The publishable key
comes from the repository variable `SUPABASE_PUBLISHABLE_KEY`. Pull requests
never run the upload job.

## Shared backend port

The iPhone is a native client of the hosted FastAPI backend. It never embeds
Python, stores provider credentials, or talks to the desktop HTTP server.
Generation and chat use the existing seller-authenticated workspace contracts:
`GET /api/runtime`, `/api/status`, conversation messages/activity, streaming
`POST /generate` and `/messages`, explicit `/stop`, and `resume=true` to observe
existing work without submitting it again. The server saves generated revisions;
the native editor reloads on return from the assistant. Unsaved local edits must
be saved first. Disconnecting never cancels or automatically retries work.

The first functional port adds native generation, a saved text transcript,
progress, stop, and explicit reconnect. Provider setup currently remains in the
web app. Chat attachments, live token rendering, and automatic foreground
reconnection remain to be ported. Generation requires server deployment with
the background worker and a configured provider; compilation does not verify
those production settings.

The complete feature-by-feature tracker is
[`docs/iphone-parity.md`](../docs/iphone-parity.md). It separates native
implementation, hosted backend availability and device verification.

Listing history uses the existing shared revisions API: browse saved versions,
preview General details and restore the full server snapshot with the current
revision ID as a conflict guard. Unsaved edits must be saved first. Restore
creates a new revision; it does not restore photos/private notes or publish.

Swift stream framing tests run in the iOS build workflow. Device verification
must cover a configured account generating from photos, assistant edits, an
interrupted connection followed by Reconnect, Stop, and refresh of the saved
listing without submitting duplicate work. No test or app flow publishes.

## Local sandbox and UI tests

See [agent sandboxes](../docs/agent-sandboxes.md). Run `./sandbox.sh --hosted`
from the repo root, then launch Debug with
`ANTEROOM_SANDBOX_URL=http://localhost:4320` in the Xcode scheme environment.
Release ignores this variable. `./anteroom-ios/test-sandbox.sh` starts the local
hosted backend and runs the draft creation/relaunch UI test without accounts.

## Desktop visual alignment

The General editor uses the desktop inspector's Listing, Pricing, Condition,
Item, Size, Color & material, Shipping, and Inventory & identifiers sections,
with flat dividers instead of one large card. Photos come before the fields;
assistant/history live in the native actions menu. Inventory rows use cover
photos and the same compact title/status hierarchy. Photos show six thumbnails
in an adaptive grid, with an explicit expand control for larger sets.
Thumbnails are authenticated requests to the existing shared backend.

For offline simulator layout review, run `./tools/build-layout-review.sh` on a
Mac and install the resulting `.app` with device tooling. It has its own bundle
ID and uses production row/field/section views with clearly labelled sample
data. It does not replace the signed-in app or test API behavior. The sample
photo illustrations are placeholders, not uploaded product photos. Review
light/dark appearance and larger text sizes; live cover-photo loading, uploads
and edits still need configured-account verification.

## Seller inputs and measurements

Photos are followed by native Notes & Labels, Pricing & Shipping, and
Measurements (in), before generated General listing fields. These controls use
the desktop ItemDetails notes keys: SKU, seller notes, known flaws, labels,
cost of goods, package dimensions, garment and per-garment measurements.
Top, Pants and Skirt retain their separate values when switching. Measurements
are seller text in inches, so fractions are not converted or rounded.

Save sends the structured notes with the existing optimistic draft save.
Unedited notes are sent byte-for-byte unchanged; editing known fields preserves
unknown root fields and nested measurement values. Plain narrative notes remain
seller notes when other fields are added. No database or API schema changes are
needed. Seller inputs are evidence for generation, separate from generated
price/cost/SKU fields. Existing generated labels remain preserved by the General
save contract; the visible seller labels use desktop's `vendooLabels` notes key.
Package dimensions display saved seller values; shared preference defaults and
recent-label suggestions remain part of the settings port.

The iOS workflow runs executable seller-note preservation tests and the hosted
sandbox UI test that saves seller inputs, switches garments, relaunches the app
and checks the saved values. Screenshots are exported from XCTest results into
the `iphone-sandbox-results` workflow artifact, on success as well as failure.
