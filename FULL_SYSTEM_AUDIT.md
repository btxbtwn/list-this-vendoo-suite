# List This / Vendoo Listing Studio — full-system audit record

Audit date: September 13, 2026, America/Chicago (event timestamps below are September 14 UTC). Repository: `btxbtwn/list-this-vendoo-suite`. Tested commit: `acfd1c24d90f7a803f1167f8ad2f10770a0e6b79`.

## 1. Executive summary

A real, retrievable Vendoo draft was created in the authorized everyday Chrome session and repeatedly reopened. It is incomplete: **zero of the five approved photos are present**, eBay and Depop automation fail to activate their forms, required specifics are absent, Mercari has a T-shirts category for the blouse, and Etsy retains an unsupported made-to-order value and a Live Listing configuration. Every inspected marketplace publication status remains `notListed: true`.

All five implemented marketplace workflows were attempted: eBay, Poshmark, Mercari, Depop, and Etsy. The all-platform pipeline stopped at eBay; separate, sequential runs exercised the remaining platforms. Etsy, Poshmark, and Mercari returned `completed`, demonstrating that completion does not mean a complete or accurate saved draft. The four additional selectable platforms—Facebook, Grailed, Whatnot, and Shopify—are filtered out before extension dispatch because they are not implemented as fillable platforms.

A second test used the ordinary new-listing Send path, without the automatically created schema-probe draft. It reported five photos uploaded and General saved, but recorded item ID **`new`**, which is a route name, not a durable Vendoo item ID. No second valid retrievable draft was independently established. That attempt was not blindly retried.

Isolated tests found data corruption from invalid typed JSON, revision restoration across conversations, a pairing-token bypass, and Retry bypassing validation and the one-active-job guard. Live schema discovery also replaced the approved job snapshot and converted Etsy materials from an array to a string. No application defects were fixed.

Continuation testing imported the disposable Vendoo draft through the real extension, preserved its item ID/URL, reloaded it in Studio, and declined the update confirmation without creating another job. The import also confirmed zero photos, lost the saved Vendoo labels, normalized `Multi` to `Multicolor`, marked the photo-less item Ready, and left the imported conversation in a `listing` state that cannot be settled. Recovery testing found that a late extension response can change Cancelled to Failed, a stale seller-details save can erase the Vendoo binding, an offline autosave can remain stuck at Saving and lose the edit, and Diagnose Page currently produces no download because its injected collector references an unavailable outer constant. A benign loopback-only probe also confirmed server-side request forgery through imported photo URLs.

## 2. Final verdict and coverage limits

**Primary acceptance: PARTIAL.** A real draft exists and was independently reopened, but it is not an accurate five-photo, all-marketplace draft. It must not be treated as ready for publication.

This document is an evidence-backed audit record, **not a claim that every requested scenario was executed**. The coverage matrix identifies unexecuted cases explicitly. Account logout, destructive interruption of everyday Chrome, every live injected DOM failure, every repair action, and a separate eligible Etsy fixture were not completed. Import, extension disable/reload, offline retry/cancel, offline autosave, and isolated per-stage failure propagation were completed after the first report pass. Screenshots were taken at representative transitions and material defects; continuous video, a complete HAR, and screenshots before/after every transition were not captured. These are coverage gaps, not passes.

Pass A began with documented setup and actual UI workflows before implementation investigation. Pass B followed the first real workflow failures and used source inspection, automated tests, isolated probes, and additional live reproduction. Existing tests and extension event claims were not accepted as substitutes for reopening the draft.

## 3. Environment

| Item | Observed value |
|---|---|
| OS | macOS 26.3.1, build 25D2128 |
| Python | 3.14.5; repository `.venv` used for backend verification |
| Node / npm | 26.0.0 / 11.12.1 |
| Chrome | 152.0.7977.84, everyday profile with existing Vendoo session |
| Studio | 0.1.0, development mode |
| Extension | 0.2.25 |
| Extension build | `567151c79f6f0bf5b7d50a035d583dd289a8814d39ab1a491877e28d8ecf4345` |
| Frontend / backend | `http://127.0.0.1:5173` / `http://127.0.0.1:4318` |
| Data directory | `vendoo-studio/data/` |
| Managed extension load path | `vendoo-studio/data/vendoo-extension/` |
| Canonical rules | `skills/list-this/`; legacy extension wrapper was not used as authority |
| Provider | Existing ChatGPT connection; `gpt-5.6-luna` for vision and listing; reasoning changed from Medium to High through Settings |
| Other integrations | Existing MiMo configuration retained; Brave Search not configured |
| Browser controller | CuaDriver 0.24.0, separately granted existing-profile session through `/tmp/vendoo-audit-cua.sock` |
| Final process state | Repo backend and Vite listening only on 127.0.0.1; no active automation jobs |

The existing-profile grant was explicitly authorized by the user. It was enabled through the installed CuaDriver application; no Chrome profile was replaced and no fresh disposable Vendoo login was substituted. Extension status reported paired, connected, current, and synchronized with this checkout. No token values were needed in the report.

## 4. Git and local work preservation

Initial worktree was clean on `t3code/fix-vendoo-photo-upload`. `origin` was confirmed as `https://github.com/btxbtwn/list-this-vendoo-suite.git`. Executed `git fetch origin`, `git switch main`, and `git pull --ff-only origin main`.

Recorded HEAD: `acfd1c24d90f7a803f1167f8ad2f10770a0e6b79` — `acfd1c2 Merge pull request #168 from btxbtwn/t3code/stop-restoring-hidden-fields`.

Setup itself changed two tracked generated files: `vendoo-studio/public/favicon.png` and `vendoo-studio/server/vendoo_studio.egg-info/SOURCES.txt`. It also produced untracked `vendoo-studio/data/settings.json`. These changes were preserved. The report and audit artifacts are uncommitted. No reset, stash, rebase, merge, commit, push, or pull request was performed.

## 5. Setup results

| Command / action | Result | Evidence |
|---|---|---|
| `./setup.sh` | Exit 0; created environment, installed dependencies, built frontend; changed generated tracked files | [setup.log](audit-artifacts-2026-09-13/setup.log) |
| `cd vendoo-studio && ./scripts/doctor.sh` | Warned port 4318 occupied, then still printed Ready | [doctor-initial.log](audit-artifacts-2026-09-13/doctor-initial.log) |
| Initial `./start.sh` | Exit 1; correctly refused occupied backend port | [start-conflict.log](audit-artifacts-2026-09-13/start-conflict.log) |
| Resolve process conflict | Identified old packaged Studio backend, confirmed no active automation job, terminated that backend gracefully | PID 17950; application source differed from checkout |
| Start current checkout | `./start.sh`; backend PID 30108, frontend PID 30132 | [start-main.log](audit-artifacts-2026-09-13/start-main.log) |
| Listener check | Both ports bound to 127.0.0.1 only | `lsof -nP -iTCP:4318 -iTCP:5173 -sTCP:LISTEN` |

Vite briefly returned proxy connection-refused errors while the backend was starting. Startup then recovered. No stale server was silently accepted as the tested build. Setup/doctor duration was not separately instrumented; it must not be inferred from the later build durations.

## 6. Feature coverage matrix

Legend: **Live** = exercised through real UI/browser; **Isolated** = current code in disposable database; **Static** = inspected only; **Not run** = no behavioral conclusion.

| Area | Coverage and outcome |
|---|---|
| Onboarding | Live configured guide plus isolated missing-dependency guide; all guide sections, Skip, reopening and Escape exercised; modal focus trap failed |
| Provider/settings | Live existing status, model/reasoning controls and navigation/search; provider test clicked but final success not independently recorded; sign-out/sign-in cycle not run |
| Missing provider | Isolated UI and API: both Create controls disabled with direct sign-in guidance; provider says Not configured while MiMo model names remain visible; missing-provider POST loses prompt persistence |
| Chrome/extension | Live existing-profile connection, version/build, pairing and managed path; disable/offline retry/cancel/re-enable/reload exercised; isolated outdated-version UI accurately reported the mismatch and offered Connect Chrome; mid-job disconnect remains incomplete |
| Marketplace selection | Live All/None and individual selections for all nine options; final selection All; only five dispatch implementations |
| Listing CRUD | Live sidebar creation, selection/search, title changes, reload/switch persistence; deletion confirmation inspected without deleting unrelated listings; settled state observed; full empty-state CRUD matrix not completed |
| Photos | Live five uploads, preview, arrows/Escape, reorder/restore, delete/re-upload test photo, unsupported/oversize and partial failure; isolated MIME spoof/traversal; duplicate-upload UI case not completed |
| Seller details | Live Good, 13x10x3, 22.5/27/9, blank original-price preservation; full rapid-write race, label override and zero/blank matrix not completed |
| Generation | Live exact supplied prompt, photo failure, generation retry, evidence/comps, saved revisions, reload/reattachment, four refinements |
| Cancel/retry chat | Live missing-field Ask Chat, cancel, restored input; persistent In Progress defect; isolated missing-provider persistence failure |
| Editor/JSON | Live General, all implemented tabs inspected, valid JSON, malformed JSON alert, `{}`, extra fields, false/zero/array/null round trip; isolated typed nested corruption and cross-conversation restore |
| Strict validation | 46 independent code-level cases; selected invalid Ready/Send UI observations; most invalid cases were not dispatched to the real extension |
| Send/new draft | Live schema-created draft/update/reopen plus independent ordinary Send attempt; acceptance fails accuracy/photos |
| eBay | Live all-platform fill failed twice on primary and once on second fixture; form manually reopened; required specifics missing |
| Poshmark | Live isolated fill/save/audit completed; reopened; primary color missing and approved style tags not preserved |
| Mercari | Live isolated fill/save/audit completed; reopened after loading settled; brand/carrier correct, category T-shirts incorrect |
| Depop | Live isolated send failed activation; reopened; source/age/style missing; parcel label differs from approved fixture |
| Etsy | Live selected, sent, saved, reopened per later user instruction; modern item validation absent and false made-to-order default retained |
| Other four selected platforms | Live selection plus static dispatch tracing; end-to-end unsupported, not passed |
| Fields/repair | Live stale cache, Refresh, missing-field Ask Chat/cancel, listing hide/Restore All and global hide/Show restoration; bulk Fill, all status-specific Ask Chat actions, global Always hide and Settings Show restoration passed; all per-status repair actions not completed |
| Import | Live extension import of only the disposable draft; ID/URL and fields persisted across reload; zero photos reflected; overwrite confirmation declined with no new job; imported state/label/color defects found |
| Responsive | Exact 1920×1080, 1440×900, 1280×800, 820×1180, 390×844; tab overflow and mobile Settings exit problem |
| Accessibility | Live keyboard/photo/dialog checks, isolated setup-guide tab order, DOM semantics, Lighthouse snapshot; setup modal focus escaped; no full screen-reader session |
| Recovery/concurrency | Live retry, reload, extension disable/reload, offline cancel, cancel-during-fill and offline autosave; isolated provider/empty/malformed responses, restart reconciliation, outdated-extension messaging, 22 pipeline failure stages, second-create rejection and retry bypass; live process/Chrome shutdown and selector fault injection remain incomplete |
| Security | Local binding, tracked-file secret scan, isolated upload/CORS/pairing/loopback-import probes, static Keychain/update/extension review; unauthenticated import SSRF confirmed; no exhaustive runtime memory or all-log secret proof |

## 7. End-to-end timeline

All times below are UTC on 2026-09-14. Local date remained September 13.

| Time | Observation |
|---|---|
| 00:31:45 | Created primary disposable Studio conversation `9a64e584adee` |
| About 00:36–00:40 | Uploaded five photos; exact Ask Chat prompt incorrectly said photo details unavailable; generation retry later analyzed photos and produced listing/comps |
| 00:40:09 | Studio automatically queued schema-probe job `eb8bad1d1e1f` after generation |
| 00:41:27 | Probe completed and bound real category-only draft `tYhkw1rewBBuMnSmjpzt` |
| Before 00:44:09 | Completed title/description/evidence refinements; approved revision `d1e71b3b36ad`; existing-draft overwrite declined once, then confirmed |
| 00:44:09 | First full update attempt; reused probe draft and skipped photos |
| 00:45:04 | Failed `filling_ebay`: `Could not activate ebay marketplace section` |
| 00:57:53–00:57:56 | Retry resumed eBay and failed identically; same draft ID |
| 00:59:04 | Created second disposable Studio conversation `842b7f1762be`; applied approved JSON and uploaded five photos through UI |
| 01:00:41 | Ordinary Send job `0093f5d1dd0f`, without previous Vendoo binding |
| 01:00:55 | Photo upload step reported five photos |
| 01:02:18 | Save reported item ID `new` and `/app/item/new`; subsequent retrieval could not resolve an item ID |
| 01:02:48 | Second job failed eBay activation |
| 01:06:42–01:08:19 | Etsy-only retry of primary completed; reopened to verify false made-to-order value and Live Listing configuration while NOT LISTED |
| 01:10:18–01:11:28 | Poshmark-only update completed; reopened |
| 01:16:38–01:17:30 | Mercari-only update completed; reopened; initial lazy-loading blanks later disproved after waiting |
| 01:18:28–01:19:17 | Depop-only update failed activation; reopened for comparison |
| After platform runs | Restored all nine selections; refreshed saved draft; exercised missing-field Ask Chat/cancel; confirmed zero active automation jobs |
| Continuation | Disabled the Studio Bridge in Chrome; retry moved to `awaiting_extension`; cancelled it offline; re-enabled and reloaded the same unpacked build successfully |
| 01:52:02 | Cancelled new job `b587781cacc3` during General fill; its tab closed, then a late content-script error changed the terminal state from Cancelled to Failed |
| Continuation | Imported draft `tYhkw1rewBBuMnSmjpzt` through the extension as conversation `b0e8ac2fda3b` / import job `531a96b3b0e6`; reloaded; declined overwrite confirmation; no additional job created |
| Continuation | Diagnose Page produced no download; isolated execution reproduced `ReferenceError: COLLECTOR_VERSION is not defined` |
| Continuation | Offline seller-details autosave remained at Saving, logged an unhandled rejection, and lost the edit after reload; online rapid values then persisted exactly |

The full ordered payloads are in [primary events](audit-artifacts-2026-09-13/final-eb8bad1d1e1f-events.json) and [ordinary-send events](audit-artifacts-2026-09-13/final-0093f5d1dd0f-events.json). The event vocabulary uses `step_started`, `step_completed`, and `step_failed`; requested conceptual stages are not all separate event types. Missing stages were not invented.

## 8. Vendoo item ID and draft URL

Verified primary item: **`tYhkw1rewBBuMnSmjpzt`**.

[Open the disposable Vendoo draft](https://web.vendoo.co/app/item/tYhkw1rewBBuMnSmjpzt).

Studio conversation: `9a64e584adee`; job: `eb8bad1d1e1f`. The draft was reopened through Open Listing and inspected independently through the everyday Chrome controller. Its final API/form read identifies the same ID and all marketplace statuses as not listed.

The second job's recorded ID `new` is invalid. `/app/item/new` is not evidence of a saved draft. The audit did not search or modify unrelated inventory to guess which item it might have created. Do not use that binding for an automatic retry. Neither audit listing nor the verified test draft was deleted.

## 9. Approved Studio snapshot versus saved General

Approval is the user's original explicit authorization to create and save disposable Vendoo drafts, plus later instructions to include Etsy and test all platforms. It does not authorize publication. The exact pre-send listing is [approved-studio-snapshot.json](audit-artifacts-2026-09-13/approved-studio-snapshot.json); independent final retrieval is [final-saved-draft.json](audit-artifacts-2026-09-13/final-saved-draft.json). Account/address/policy fields are redacted.

| Field | Approved Studio | Reopened Vendoo | Result |
|---|---|---|---|
| Photos | Five, IMG_4251 through IMG_4255 in order | `images: []` | **Missing all five** |
| Title | Notations XL Retro Short Sleeve Button-Up Shirt Black White Gray Relaxed | Exact match | Correct; 72 characters |
| Description | Approved paragraphs, uncertainty statements, exact 22.5/27/9 measurements | Exact saved text match | Correct General copy |
| Price | 14 | 14 | Correct transfer; comp derivation insufficiently explained |
| Brand | Notations | Notations | Correct |
| Size | XL / Regular | XL / Regular | Correct |
| Department | Women | Women's terminal category | Aligned General category |
| Condition | Pre-Owned - Good | Pre-owned code `v_preowned`; displayed equivalent | Supported broad equivalent; marketplace conditions checked separately |
| Colors | Multi / Black | Multicolor / Black | Correct General mapping |
| Quantity | 1 | 1 | Correct |
| SKU | NOTATIONS-XL | NOTATIONS-XL | Correct |
| Category | Clothing, Shoes & Accessories > Women > Women's Clothing > Tops | Same terminal path, `isLeaf: true` | Correct General selection |
| Cost | Generated 0; seller COG input left blank | 0 | Transfer matches snapshot; blank seller knowledge is not evidence of zero cost |
| Weight | Generated default 0 lb 8 oz | 0 lb 8 oz | Transfer correct; weight was not independently measured |
| Dimensions | 13x10x3 | 13 × 10 × 3 | Correct |
| Labels | To List | To List observed in draft; Fields called it empty | Saved label correct; Fields disagreement |
| Tags | Floral, Abstract Print, Button-Up, Casual, Woven | Same array in saved General data | Correct General transfer |
| Country | China in eBay specifics | eBay country-specific field absent | Missing marketplace fact |
| Material/care/date | Unknown, no invented care/date | General description preserves uncertainty | Correct after chat repair; initial generation had false Machine Washable |

All five local photo records still exist for each audit Studio conversation. Reordering the second listing and restoring the order persisted; deleting/re-uploading only the disposable fifth photo left the final count five. Local photo integrity does not establish Vendoo upload success.

## 10. Marketplace-by-marketplace comparison

The comparison uses settled live form observations plus the saved API object. A raw checkbox input value `on` is not proof that the checkbox is checked. A hidden input's single value is not the full multi-select array. Such scraper disagreements are identified below.

| Marketplace | Correct / retained | Missing, incorrect, or unverified |
|---|---|---|
| eBay | Inherited title, description, brand, quantity, SKU, dimensions/weight, terminal Tops category, fixed price 14 | Automation failed before filling specifics. Department, size, size type, China, material/care uncertainty handling and other approved specifics not populated. Auto-accept/minimum are blank. Default `statusItem: Active` is configuration, not actual publication; status remains notListed |
| Poshmark | Title/description, Notations, Good, XL, quantity 1, price 14, SKU; Blouses terminal category | Primary color blank. Approved platform style tags Floral/Casual/Relaxed Fit replaced by general tags. Original price 0 is not a verified retail price. Completed status did not establish field accuracy |
| Mercari | Settled form shows Notations, Good, price 14, quantity 1, 0 lb 8 oz, 13x10x3, USPS Ground Advantage, Buyer pays; smartPricing/smartOffers false in API | Category is Women > Tops & blouses > **T-shirts**, inappropriate for the button-front blouse. Initial brand/carrier blanks were loading transients and are **not** final defects. Size saved as category option ID 6; label-to-XL correspondence not independently established |
| Depop | Inherited description, Notations, Used - Good, Multi/Black, price 14, quantity 1, SKU, Blouses category | Source/age/style arrays empty despite approved Preloved/Modern/three styles. Material/occasion remain unfilled. Actual parcel label Extra small differs from approved Small fixture. Size ID 19 requires explicit label verification. Activation failure means no successful Depop-specific fill/audit |
| Etsy | Physical Item, another company/person, finished product, description, quantity 1, price 14, SKU, Blouses category, automatic renewal; actual status NOT LISTED | Unknown when-made became Made To Order; configuration Live Listing (`active`), not Draft; primary color blank; branded title retained despite canonical Etsy-safe title rule; tags merged to ten instead of preserving approved five; materials absent; eligible-item policy not enforced; profile matching not verified against approved named choices |
| Facebook / Grailed / Whatnot / Shopify | Selection checkboxes work | No fill pipeline. `selected_fillable_marketplaces` removes them. Settings gives no clear unsupported notice; an empty Fields view has an unavailable-platform message, which is not shown when inherited fields populate that view. End-to-end blocked by missing implementation |

All saved platform fields, including optional/nested fields, are included in the sanitized final snapshot and the field comparison appendix. Fields not independently resolved to a human-readable dropdown label are marked unverified rather than assumed correct.

The extension import of the same disposable draft created local conversation `b0e8ac2fda3b` and terminal import job `531a96b3b0e6`. Title, description, price, brand, size, condition, category, weight, dimensions, SKU and tags survived. Photos correctly imported as zero because the remote draft has none. Approved `To List` became an empty labels array because the importer reads `generalDetails.labels` while Vendoo returned root-level label IDs; `Multi` normalized to `Multicolor`. All five marketplace objects were present, but account/policy-shaped keys were redacted in retained evidence. Reload preserved ID/URL and fields. Clicking Update displayed the explicit existing-item warning; Cancel created no second job. Evidence: [imported-listing.json](audit-artifacts-2026-09-13/recovery-continuation/imported-listing.json), [imported-photos.json](audit-artifacts-2026-09-13/recovery-continuation/imported-photos.json), and [import-decline-reload-result.json](audit-artifacts-2026-09-13/recovery-continuation/import-decline-reload-result.json).

## 11. Fill-log accuracy review

The final job summary is **25 filled, 1 skipped, 1 not found, 1 failed, 0 uncertain, 30 new**. These are the latest job ledger counts, not the cumulative successful fields across all attempts. Retry clears prior portions of the ledger, so event history is required to reconstruct earlier results.

Three independent disagreements were established: (1) General audit returned success while all photos were absent; (2) initial Fields read showed old blank values until explicit Refresh; (3) form scraping collapsed tags to the last hidden-input value (`Woven`) and represented unchecked switches as `on`, while the saved API preserved arrays and `false`. Vendoo Labels was called empty despite the actual To List label.

Missing-field Ask Chat received marketplace IDs and field names and instructed changes to only those fields. Its count included irrelevant/unknown fields such as care/material. Cancel restored that prompt in the input and the user message remained persisted, but the conversation stayed In Progress. Bulk Fill was not executed because a 55-field batch included fields whose source/meaning was not independently approved. No claim is made that leftover-field filling is safe or accurate.

Global hidden-field verification also passed: hiding SKU Always produced only an `always` entry with an empty listing-scoped list; Settings → Show restored both lists to empty. See [global-hidden-sku.json](audit-artifacts-2026-09-13/global-hidden-sku.json) and [global-hidden-restored.json](audit-artifacts-2026-09-13/global-hidden-restored.json).

## 12. Passed workflows

- Clean-main update, conflict refusal, documented setup, current local startup, existing-profile access and current paired extension.
- Five-photo local upload and metadata retention; preview navigation/Escape; test-photo reorder and restoration; unsupported/oversize rejection.
- Exact measurement decimals persisted; an actually blank original-price field stayed blank after keyboard editing and reload.
- Generation retry eventually produced evidence/comps; targeted title and uncertainty refinements persisted; JSON false/zero/array/null round-tripped in the manual fixture.
- Existing-draft overwrite cancellation left the draft unchanged; confirmed updates stayed on the disposable item; Poshmark/Mercari/Etsy save stages completed and were independently reopened; no actual publication observed.
- Real extension import bound only the disposable draft, persisted across reload, showed the overwrite warning, and declining it created no update job. Exact rapid seller details persisted online after reload; extension disable/re-enable/reload recovered the expected build.
- The isolated outdated-extension state displayed `Extension outdated` and offered `Connect Chrome` both in the footer and Connections settings, with the managed load path and an accurate explanation of the reload flow. Evidence: [outdated-ui-results.json](audit-artifacts-2026-09-13/recovery-continuation/outdated-ui-results.json).

## 13. Failed workflows

The defect catalog below contains reproducible failures and static security risks. The principal failures are missing Vendoo photos, invalid new-item ID acceptance, eBay/Depop activation, incomplete completed states, permissive validation, JSON data corruption, mutable approval snapshots, retry concurrency, Etsy false defaults, stale/misleading field reads, lost/empty failed prompts, cancellation terminal-state races, lost Vendoo binding, failed autosave recovery, broken Diagnose Page, import SSRF/state/data loss, and mobile Settings navigation.

## 14. Blocked and unexecuted workflows

| Workflow | Exact limitation / required next action |
|---|---|
| Valid Etsy vintage/handmade/craft/digital test | No independently verified eligible fixture supplied. Provide its photos and eligibility evidence to test those paths; the user's later instruction authorized testing this blouse but did not make its eligibility factual |
| Four additional selected platforms | Implemented dispatch support is absent; credentials alone cannot unblock these flows |
| Independent ChatGPT Web code review | CloakBrowser coding-review session presented a sign-in wall. Sign into that separate review session if that independent review channel is required. Studio's provider login already worked and was not the blocker |
| Second new-item saved-draft verification | Job recorded `new`; valid item identity unknown. An item ID must be recovered through reliable save/readback behavior before safe retry; do not guess unrelated inventory |
| Account disconnected/logged-out matrix | Provider-absent/Chrome-absent UI was exercised in isolation; real Vendoo logout was not executed because the existing authorized session could not be restored without known credentials. No missing-credentials claim applies to the successful connected path |
| Chrome shutdown and live process restart during jobs; every live injected missing/disabled DOM control | Not executed against everyday Chrome. Repository restart reconciliation and 22 isolated extension stages were exercised, but those are not substitutes for live browser/selector failures |
| Every repair action and every editor field | Hide/restore, Refresh, Ask Chat, representative typed values and rapid autosave were exercised; exhaustive per-field manual repair remains incomplete |
| Full screen-reader, complete console/HAR/video, screenshots at every transition | Not captured; representative sanitized evidence only |

## 15. Automated verification

| Exact command (working directory) | Exit | Counts | Duration |
|---|---:|---|---:|
| `npm ci` (`vendoo-studio`) | 0 | Install, not tests | 2.395 s |
| `npm run build` (`vendoo-studio`) | 0 | Build, not tests; bundle-size warning | 3.690 s |
| `.venv/bin/python -m pytest -q` (`vendoo-studio`) | 1 | **307 passed, 1 failed, 0 skipped, 5 warnings** | 7.893 s wall / 7.13 s pytest |
| `.venv/bin/python -m pytest -q server/tests/test_chatgpt_oauth.py::SettingsChatGPTRouteTest::test_provider_keeps_masked_mimo_key_while_chatgpt_is_signed_in` | 1 | **0 passed, 1 failed, 0 skipped, 5 warnings** | about 1.2 s wall / 0.56 s pytest |
| `node --check <file>` for all 13 extension JS files | 0 each | 13 syntax checks passed; not behavioral tests | 0.056–0.062 s each |
| `python -m json.tool vendoo-extension/manifest.json` | 0 | 1 JSON check passed | 0.044 s |
| `python -m json.tool skills/list-this/references/vendoo-dropdown-options.json` | 0 | 1 JSON check passed | 0.041 s |
| `skills/list-this/SKILL.md` existence | 0 | File exists | Not timed |
| `gitleaks dir <temporary copy of 241 tracked files> --redact=100 --config .gitleaks.toml` | 0 | No leaks; 2,422,841 bytes scanned | 0.649 s |
| `.venv/bin/python ../audit-artifacts-2026-09-13/validation-matrix.py` | 0 | 46 cases: 37 accepted, 7 blocked, 2 exceptions | Not separately timed |
| `.venv/bin/python ../audit-artifacts-2026-09-13/isolated-probes.py` | 0 | 10 observations; defects detected, not ten passes | Not separately timed |
| `vendoo-studio/.venv/bin/python audit-artifacts-2026-09-13/concurrency-probes.py` (root) | 0 | Create guard 409; retry 200 with 2 active jobs and blank title | 0.696 s final run |
| `.venv/bin/python ../audit-artifacts-2026-09-13/recovery-continuation/recovery-probes.py` (`vendoo-studio`) | 0 | 14 observations: five Ask Chat, four Generate, one stale-note overwrite, four restart states | 0.611 s |
| `node audit-artifacts-2026-09-13/recovery-continuation/extension-pipeline-probe.cjs` | 0 | 22/22 stages reported the exact injected failure; no completion; active extension job retained for retry | 0.043 s |
| `node audit-artifacts-2026-09-13/recovery-continuation/diagnostic-isolation-probe.cjs` | 0 | 1 reproduction; actual serialized collector threw `ReferenceError` | 0.083 s |
| `.venv/bin/python ../audit-artifacts-2026-09-13/recovery-continuation/import-loopback-probe.py` (`vendoo-studio`) | 0 | 1 benign loopback request accepted; imported state/settle conflict reproduced | 0.518 s |

The failing backend assertion at `server/tests/test_chatgpt_oauth.py:272` expected `gpt-5.5` but received `gpt-5.6-luna`. It reproduced individually, so it is not classified as flaky. Complete failure messages and five warning texts are retained in [backend-tests.log](audit-artifacts-2026-09-13/backend-tests.log) and [backend-failure-retest.log](audit-artifacts-2026-09-13/backend-failure-retest.log). No tests were fixed.

A final `gitleaks dir audit-artifacts-2026-09-13 --redact=100 --config .gitleaks.toml --report-format json --report-path /tmp/vendoo-audit-artifact-gitleaks.json` scan exited 0 with no leaks (2.46 MB scanned, 635 ms reported). This is pattern scanning, not proof against all private data.

The initial `gitleaks git` invocation scanned zero commits and was not accepted as evidence; the tracked-file directory scan replaced it. It does not prove absence of secrets in every runtime artifact, database, or browser message. Individual syntax commands/durations are in [extension-skill-checks.json](audit-artifacts-2026-09-13/extension-skill-checks.json).

## 16. Security findings

Actual listeners are loopback-only; random stored photo names prevented the tested traversal. Keychain service code uses keyring for provider keys and OAuth tokens. The tracked-tree scan found no secrets. These are bounded positive observations.

High-risk code findings remain: pairing accepts a fixed literal, token file permissions are 0644, the WebSocket replaces the current connection before authentication without an Origin gate, and downloaded update bundles are extracted/launched without a verified digest or signature in the reviewed path while quarantine is removed. Image MIME claims are trusted even when decoding fails. The unauthenticated import endpoint fetches arbitrary HTTP(S) photo URLs and successfully reached a benign loopback server, establishing SSRF. See C01–C03, C18 and C27.

Diagnostics/form scraping can include private account/address fields. The audit encountered those fields during inspection and redacted them from retained artifacts; this prevents any blanket claim that diagnostics are inherently safe to share. No credentials/cookies/tokens were intentionally exported. Browser tool output was not a complete secret audit, and the report does not assert that secrets can never enter SQLite or all extension messages.

## 17. Data-integrity findings

Typed nested JSON can be saved before validation throws, making subsequent reads fail. Revision restore can copy another conversation's revision. Learned-field backfill mutates job snapshots and changes empty-array types. Retry reapproves the latest revision without revalidation. Cancelled chat leaves an In Progress status. A later extension error can overwrite Cancelled with Failed. Whole-note autosaves can erase a Vendoo item binding captured by another flow; this was reproduced with two stale/current note snapshots. A network-rejected autosave stays at Saving and loses the edit on reload. These are independent of live marketplace account state.

Original photos and exact measurements survived the exercised operations. General condition did not unexpectedly change in the primary run. Online rapid edits of Good, 22.5, 27 and 9 persisted exactly on the imported local record. The ordinary Send path's invalid `new` binding remains unresolved, and after the valid binding disappeared the UI opened another new-item job; it was cancelled before General save, so duplicate creation was not proven, but the risk is concrete.

## 18. Accessibility findings

Lighthouse snapshot: accessibility **93**, best practices **100**; 37 passed audit items and 6 failed overall (some failures are SEO/agent discovery, not relevant local-app defects). Relevant failures: user zoom disabled by `maximum-scale=1`, job-status contrast 4.41:1 versus 4.5:1, and a button using `role=listitem`. A later real console warning reported focus retained inside an `aria-hidden` sidebar during mobile pane switching.

Photo Escape and arrow navigation worked. Listing hide-menu keyboard activation, Settings search keyboard selection/Escape, and Restore All worked. The first-run guide closed on Escape, but Tab escaped the modal to the underlying Open Settings button, confirming a focus-trap failure. All accessible names, live announcements and screen-reader behavior remain incomplete coverage. Evidence: [accessibility-failures.json](audit-artifacts-2026-09-13/accessibility-failures.json), [browser-console-final.txt](audit-artifacts-2026-09-13/browser-console-final.txt), [isolated-first-run-results.json](audit-artifacts-2026-09-13/recovery-continuation/isolated-first-run-results.json).

## 19. Responsive-layout findings

At exact 1920×1080, 1440×900 and 1280×800, the editor remains narrow and later marketplace/JSON tabs extend beyond its initial visible area. The tab strip is horizontally scrollable, but its scrollbar is hidden; this is a discoverability defect, not proof that JSON is unreachable. At 390×844 JSON ends near x=434, outside the visible viewport. Document width itself remains 390; no page-wide horizontal overflow was measured. The 820×1180 editor fits all tabs.

Mobile Settings has a stronger problem: Back to listings opens the Settings sidebar without leaving Settings, while the actual Back button is in a footer hidden below 900px. Escape closes the sidebar but does not exit Settings. Switching viewport/reloading restored access during this audit.

Use the exact-size `*-verified.png`, `tablet-editor-820x1180.png`, and `mobile-*.png` artifacts. Earlier screenshots named for requested desktop/mobile sizes were constrained by the native window/device scale and are not measurement evidence. They are listed separately or removed from the deliverable where privacy/ambiguity made them unsuitable.

## 20. Product-policy and canonical-rule findings

The user initially excluded Etsy for this modern Notations blouse, then explicitly instructed testing/submitting Etsy with all platforms. The audit followed the later instruction **only to the saved Vendoo draft boundary**. It did not fabricate vintage age or handmade status. Studio did not enforce eligibility; Vendoo defaults nevertheless introduced Made To Order.

Canonical sources disagree: `SKILL.md:296–309` requires whole-dollar comp ×1.35 pricing, while `vendoo_listing_template.md:16` requires eBay/Etsy .99 prices. The template's 200–300-character universal description and no-measurements-in-body instruction also differ from the skill's physical-item format and fixture instructions. These disagreements need an explicit canonical decision before writing a single validator.

The generated 72-character title follows the skill's brand/size/vibe/item/color/fit order. The exact measurements and unknown material/care/date statements were preserved after refinement. Initial Machine Washable was unsupported and had no validation warning. Default 8 oz and zero original price/cost were not independently verified facts.

Two comp pages were independently checked: [Mercari sold item](https://www.mercari.com/us/item/m65412464455/) displayed sold and $10.80; [Poshmark sold item](https://poshmark.com/listing/Notations-Woman-Soft-Velvet-Top-Sparkle-Floral-Pattern-Size-Plus-1X-Short-Sleeve-694a8f67fedc5c45747394b7) displayed Sold and $16. These were different sizes/styles. Displayed sold-page prices are not proof of negotiated transaction amounts. The UI's $10–$11 market estimate and $14 price were not transparently reconciled with both comps. At $14, the required auto-accept/minimum are $12/$10; saved eBay offer fields remained blank.

## 21. Known-issue retest table

| # | Previously reported issue | Status | Evidence / limitation |
|---:|---|---|---|
| 1 | Create disabled without provider | Confirmed | Both sidebar and empty-state Create controls disabled in isolated missing-provider UI; sign-in recovery text shown |
| 2 | Failed Ask Chat prompt cleared/not persisted | Confirmed | Isolated missing-provider request leaves zero messages; UI keeps retry text only in memory |
| 3 | Default model displayed unconfigured | Confirmed | Provider status says Not configured while Vision/Listing/footer show `mimo-v2.5` / `mimo-v2.5-pro` |
| 4 | Duplicate title/description/price errors | Confirmed | Independent validation cases and invalid-listing screenshot |
| 5 | Invalid Send looks enabled | Confirmed | Green enabled-looking button; click handler guards invalid state, so appearance is not successful dispatch |
| 6 | Ready with invalid marketplace values | Confirmed | Approved fixture can_send true, no warnings; validation matrix |
| 7 | eBay validation covers few specifics | Confirmed | Only four optional warnings, and empty specifics bypass even those |
| 8 | Invalid Depop enums reach Ready | Confirmed | Enum matrix accepted; real approved Boho/Work values not validated |
| 9 | Etsy eligibility absent | Confirmed | Modern fixture selected/sent; no eligibility gate |
| 10 | Inferred material/care receives no warning | Confirmed | Generated Machine Washable and uncertainty validation cases |
| 11 | Login redirect called image-input missing | Blocked | Signed-out live scenario not run; no authentication-failure claim from this session |
| 12 | Login detection occurs after photo upload | Partially confirmed (current code contradicts old sequencing) | Current WAIT_FOR_FORM precedes photo stage and checks login; actual signed-out UI not reproduced |
| 13 | Retry repeats authentication failure | Blocked | Authentication failure not exercised; eBay activation retry did repeat failure |
| 14 | Category/Labels placeholders look saved | Confirmed | Empty controls display Clothing >… / To List, A19 like values |
| 15 | Desktop tabs clip/overflow | Confirmed | Exact viewport measurements; horizontal scroll exists but hidden affordance |
| 16 | Completion trustworthy without reopen | Confirmed as false-success defect | Completed Etsy/Posh/Mercari attempts still have missing photos/fields |
| 17 | Fill counts match live form | Confirmed as inaccurate | Stale values, missing label, array/checkbox read disagreement; cannot use counts as completeness proof |
| 18 | Failed send unexpectedly changes source condition/data | Partially confirmed | Condition unchanged; schema backfill added keys and converted materials [] to empty string |
| 19 | Failed/retried job duplicates drafts | Partially confirmed | Same valid primary ID reused initially; stale notes erased its binding and a later Send opened a new-item job. Cancel occurred before General save, so a second saved ID was not proven |
| 20 | Modern blouse can be sent to Etsy | Confirmed | Real Etsy-only attempt completed, still unpublished |

## 22. Prioritized fix order

1. Protect pairing/update/import trust, block import SSRF, and ensure no save path can publish; enforce explicit Draft configuration and immutable approval. No actual publication was observed, but configuration must be safe.
2. Stop persistent data corruption, cross-conversation restoration, stale-note binding loss and offline autosave loss; make Cancelled terminal and preserve array/false/zero types.
3. Replace optimistic completion/Ready with saved-ID validation, photo count/order verification, exact readback comparisons and meaningful audit failure; repair import fidelity and lifecycle state.
4. Fix new-item identity, eBay/Depop activation, Diagnose Page, category/dropdown matching and marketplace-specific fields; add one-job/validation guards to retry and all repair paths.
5. Unify canonical rules, implement strict validation, repair empty/failed prompts, cache/logs, disclose unsupported platforms, and then address mobile/accessibility/documentation defects.

## 23. Recommended regression strategy

Every catalog finding includes an automated and manual regression recommendation. The release gate should create one disposable five-photo draft, reopen its durable ID, compare every approved General/platform field, assert all statuses remain notListed, and reject success when any required field or photo differs. This must use the real extension and Vendoo save behavior; mocks alone cannot prove acceptance.

Use isolated tests for malformed JSON, cross-conversation IDs, stale-note conflicts, array/false/zero round trips, pairing/Origin/import URL validation, retry concurrency, terminal cancellation and provider empty/error streams. Add browser tests for pre-upload login detection, asynchronous form mounting, category dependencies, diagnostic download, import round trip, offline autosave recovery, photo persistence and mobile Settings/modal focus. Keep account-bound address/profile data out of snapshots and test logs.

## 24. Explicit publication-safety statement

No Publish, List, Activate, Sell, or equivalent marketplace publication control was intentionally clicked by the audit. No publication operation was observed in job events or reviewed save automation. The final live draft page still showed nine `NOT LISTED` marketplace controls and Studio reported zero active jobs. Reopened draft statuses were `notListed: true`, including Etsy, eBay, Poshmark, Mercari, Depop and the other returned marketplace entries. “Live Listing”/`active` in Etsy configuration is an unsafe saved setting, **not evidence that a marketplace listing became live**.

No existing unrelated listing was edited or deleted. The disposable draft is retained. No source fixes, commits, pushes, merges, rebases, deployments or pull requests were made. The report does not prove all hypothetical publication paths impossible; the static safeguards and observed draft statuses support the bounded statement above.

## Defect catalog

Detailed findings and appendices follow. Each finding distinguishes observed behavior from a likely source explanation. Where console/network/job evidence was not captured or does not apply, that absence is stated rather than manufactured.

### Code defects — security


#### C01 — Pairing accepts a fixed bypass and stores a weak token with broad permissions

**Severity:** High. **Component:** Code defects — security. **Reproduction rate:** 1/1 isolated bypass probe; file mode observed once.

**Preconditions:** Current ExtensionManager and initialized local data directory.

**Exact reproduction:** Call verify_token with the literal direct in an isolated process; inspect token-file mode without reading its contents.

**Expected:** Only a strong, authorized pairing credential is accepted; token file restricted to the current user.

**Actual:** verify_token returned true for direct. Generated token is eight hex characters; actual file mode was 0644.

**Evidence:** [isolated-probes.json](audit-artifacts-2026-09-13/isolated-probes.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** verify_token's unconditional direct fallback at line 92 bypasses generated credentials; normal open() inherits permissive umask; generation truncates UUID at line 82.

**Source:** [vendoo-studio/server/vendoo_studio/routes/extension.py:74](vendoo-studio/server/vendoo_studio/routes/extension.py#L74).

**User impact / data-loss or publication risk:** Unauthorized local/browser pairing could gain automation/data access. No exploit against the real session was performed; publication risk depends on downstream messages.

**Recommended fix:** Only a strong, authorized pairing credential is accepted; token file restricted to the current user. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Reject direct/random/empty tokens; require strong token entropy and 0600 persistence.

**Manual regression:** Pair a current extension, reject an unapproved controller, and confirm the legitimate connection still works.


#### C02 — WebSocket connection can displace paired client before authentication

**Severity:** High. **Component:** Code defects — security. **Reproduction rate:** Static path confirmed; hostile browser exploit not attempted.

**Preconditions:** Reachable local WebSocket endpoint.

**Exact reproduction:** Inspect WebSocket accept, replacement, and authentication ordering; inspect pairing-token route.

**Expected:** Authenticate and enforce Origin before replacing a paired connection; expose pairing credentials only through an authorized flow.

**Actual:** Connection accepted and previous socket closed before authentication; no Origin check in the reviewed handler; pairing-token route returns a token without API authentication.

**Evidence:** [isolated-probes.json](audit-artifacts-2026-09-13/isolated-probes.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Handler lines 411–421 accepts/replaces first; token and WebSocket trust boundaries are inconsistent.

**Source:** [vendoo-studio/server/vendoo_studio/routes/extension.py:380](vendoo-studio/server/vendoo_studio/routes/extension.py#L380).

**User impact / data-loss or publication risk:** Potential denial of service and unauthorized access; runtime exploitability from hostile origins remains untested.

**Recommended fix:** Authenticate and enforce Origin before replacing a paired connection; expose pairing credentials only through an authorized flow. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Untrusted origins/unauthenticated sockets cannot replace a paired client or obtain credentials.

**Manual regression:** Attempt an unpaired connection in an isolated browser and verify the active extension remains paired.


#### C03 — Packaged update path lacks verified artifact integrity and removes quarantine

**Severity:** High. **Component:** Code defects — security. **Reproduction rate:** Static review; no update installed.

**Preconditions:** Packaged update available.

**Exact reproduction:** Trace downloaded zip through extraction, preparation, and app replacement.

**Expected:** Verify the downloaded bytes and trusted signing identity before running or replacing an app.

**Actual:** Reviewed path downloads then extracts without a digest/signature verification; preparation invokes xattr -cr.

**Evidence:** source review only.

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Download/extract at 247–249 is not bound to verified artifact bytes; _prepare_app_bundle at 167–179 removes quarantine.

**Source:** [vendoo-studio/server/vendoo_studio/services/packaged_updates.py:247](vendoo-studio/server/vendoo_studio/services/packaged_updates.py#L247).

**User impact / data-loss or publication risk:** Compromised distribution could execute code as the user. No download was installed during this audit.

**Recommended fix:** Verify the downloaded bytes and trusted signing identity before running or replacing an app. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Reject modified, unsigned, incorrectly signed and path-escaping archives before replacement.

**Manual regression:** Use a trusted test release and a tampered copy in an isolated install; verify only the trusted bundle can launch.


### Code defects — data integrity


#### C04 — Invalid nested JSON is persisted before validation crashes

**Severity:** High. **Component:** Code defects — data integrity. **Reproduction rate:** 1/1 isolated write/read sequence; two validator exception cases.

**Preconditions:** Disposable conversation with valid listing revision.

**Exact reproduction:** PUT listing with ebay_specifics set to a string; GET the listing afterward.

**Expected:** Return a clear validation error without changing the last valid revision.

**Actual:** PUT returned 500 and subsequent GET also returned 500; validator invokes .get on a string after persistence.

**Evidence:** [isolated-probes.json](audit-artifacts-2026-09-13/isolated-probes.json); [validation-matrix.json](audit-artifacts-2026-09-13/validation-matrix.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Raw revision saved before validate_listing; models/validation.py:58–60 assumes nested mappings even after Pydantic errors.

**Source:** [vendoo-studio/server/vendoo_studio/routes/listings.py:82](vendoo-studio/server/vendoo_studio/routes/listings.py#L82).

**User impact / data-loss or publication risk:** Listing editor becomes unreadable; persistent data corruption until recovered. No real user listing was poisoned.

**Recommended fix:** Return a clear validation error without changing the last valid revision. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Malformed nested object types return 422/400 and retain identical current revision; GET remains 200.

**Manual regression:** Apply malformed typed JSON to a disposable listing and reload; confirm prior valid content remains.


#### C05 — Revision restore accepts a revision from another conversation

**Severity:** High. **Component:** Code defects — data integrity. **Reproduction rate:** 1/1 isolated cross-conversation restore.

**Preconditions:** Two disposable conversations and a revision belonging only to A.

**Exact reproduction:** POST B/revisions/<A revision>/restore; read B.

**Expected:** Reject a revision whose conversation does not match the URL.

**Actual:** HTTP 200 copied A's listing into B.

**Evidence:** [isolated-probes.json](audit-artifacts-2026-09-13/isolated-probes.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Revision fetched by global ID without verifying conversation ownership before save.

**Source:** [vendoo-studio/server/vendoo_studio/routes/listings.py:155](vendoo-studio/server/vendoo_studio/routes/listings.py#L155).

**User impact / data-loss or publication risk:** Cross-listing data contamination; no unrelated real listing was touched.

**Recommended fix:** Reject a revision whose conversation does not match the URL. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Cross-conversation restore returns 404/403 and leaves both revisions unchanged.

**Manual regression:** Attempt a mismatched revision restore using disposable fixtures and verify both listings.


#### C06 — Learned-field backfill mutates approved snapshots and changes array types

**Severity:** High. **Component:** Code defects — data integrity. **Reproduction rate:** Observed across primary job backfill; one existing value changed type.

**Preconditions:** Approved job, later discovered marketplace fields.

**Exact reproduction:** Compare approved revision with source after job schema discovery; trace backfill assignments.

**Expected:** Approved job JSON is immutable; metadata discovery preserves existing values/types.

**Actual:** 28 empty learned keys added and etsy_specifics.materials changed from [] to empty string; job.listing_snapshot is reassigned to backfilled latest listing.

**Evidence:** [source-changes-after-jobs.json](audit-artifacts-2026-09-13/source-changes-after-jobs.json); [approved-studio-snapshot.json](audit-artifacts-2026-09-13/approved-studio-snapshot.json); [job-eb8bad1d1e1f-snapshot.json](audit-artifacts-2026-09-13/job-eb8bad1d1e1f-snapshot.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Backfill assigns job.listing_snapshot at line 596. RegistryService.merge_learned_fields at registry.py:459–465 treats empty arrays as missing and writes an empty string.

**Source:** [vendoo-studio/server/vendoo_studio/services/fill_log.py:590](vendoo-studio/server/vendoo_studio/services/fill_log.py#L590).

**User impact / data-loss or publication risk:** Approved data can change during execution and arrays are corrupted; subsequent retries may send different content.

**Recommended fix:** Approved job JSON is immutable; metadata discovery preserves existing values/types. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Hash approved snapshot through schema events and later editor writes; preserve []/false/0/null distinctly.

**Manual regression:** Approve a draft, discover fields while editing another revision, and compare the executed snapshot with approval.


### Code defects — recovery


#### C07 — Retry bypasses validation and the one-active-job guard

**Severity:** High. **Component:** Code defects — recovery. **Reproduction rate:** 1/1 isolated retry sequence; new-job guard correctly rejected second create.

**Preconditions:** Failed job A and queued job B; A edited to blank title.

**Exact reproduction:** Create A; mark its isolated job failed; create B; blank A's title; POST A/retry.

**Expected:** Reject while B is active and reject invalid latest data; approval remains explicit.

**Actual:** Retry returned 200; two jobs were active/queued and A's listing title was blank. Initial second create correctly returned 409.

**Evidence:** [concurrency-probes.json](audit-artifacts-2026-09-13/concurrency-probes.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Retry resets status/snapshot from latest revision at 614–632 without reusing create_job validation and active guard.

**Source:** [vendoo-studio/server/vendoo_studio/routes/jobs.py:591](vendoo-studio/server/vendoo_studio/routes/jobs.py#L591).

**User impact / data-loss or publication risk:** Concurrent automation and invalid data can enter jobs; duplicate/conflicting browser actions possible. No concurrent real automation was run.

**Recommended fix:** Reject while B is active and reject invalid latest data; approval remains explicit. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Every create/retry/repair entry point enforces atomic active-job and validation checks.

**Manual regression:** With one disposable job active, retry another; verify rejection and unchanged approved snapshot.


### Code defects — draft workflow


#### C08 — Schema-probe draft binding causes all photos to be skipped

**Severity:** High. **Component:** Code defects — draft workflow. **Reproduction rate:** All full updates of primary draft; final 0/5 photos.

**Preconditions:** Generation has automatically created a category-only schema draft; five Studio photos.

**Exact reproduction:** Generate listing, let schema probe bind item, then confirm Send/Update; reopen saved draft.

**Expected:** Upload and verify all five approved photos even when reusing a photo-empty probe draft.

**Actual:** Every normal update reused the item ID and skipped upload; final General images array is empty.

**Evidence:** [final-saved-draft.json](audit-artifacts-2026-09-13/final-saved-draft.json); [final-eb8bad1d1e1f-events.json](audit-artifacts-2026-09-13/final-eb8bad1d1e1f-events.json); [photo-metadata.json](audit-artifacts-2026-09-13/photo-metadata.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** skipPhotos is true for any reuse_existing binding; background.js:1676–1681 also returns when item ID exists without checking photo inventory.

**Source:** [vendoo-studio/server/vendoo_studio/routes/extension.py:219](vendoo-studio/server/vendoo_studio/routes/extension.py#L219).

**User impact / data-loss or publication risk:** Incomplete real draft despite completed stages; no photo-order acceptance possible.

**Recommended fix:** Upload and verify all five approved photos even when reusing a photo-empty probe draft. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Probe-created empty draft followed by send uploads exactly five ordered photos and verifies persistence.

**Manual regression:** Generate a new five-photo fixture, send once, reopen by ID, and compare all photos visually.


#### C09 — New route name is accepted as a saved Vendoo item ID

**Severity:** High. **Component:** Code defects — draft workflow. **Reproduction rate:** 1/1 ordinary new-item Send attempt.

**Preconditions:** Second fixture with five photos and no existing Vendoo binding.

**Exact reproduction:** Send once; inspect saving_general event and Open Listing binding.

**Expected:** Wait for durable non-new item ID and successfully reopen it before reporting saved.

**Actual:** Saved ID was new and URL /app/item/new; subsequent readback reported missing item ID.

**Evidence:** [manual-job-timeline.json](audit-artifacts-2026-09-13/manual-job-timeline.json); [final-0093f5d1dd0f-events.json](audit-artifacts-2026-09-13/final-0093f5d1dd0f-events.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Content-script extractItemId accepts any /item/ segment, unlike background.js:839–845 which rejects new. saveGeneral trusts it after a fixed delay.

**Source:** [vendoo-extension/content-scripts/vendoo.js:4368](vendoo-extension/content-scripts/vendoo.js#L4368).

**User impact / data-loss or publication risk:** No reliable draft identity, unsafe retry/deduplication and possible abandoned draft; actual duplicate not established.

**Recommended fix:** Wait for durable non-new item ID and successfully reopen it before reporting saved. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Reject new/empty IDs; wait for persisted ID and verify GET/reopen before binding or completion.

**Manual regression:** Ordinary new-item Send with slow uploads/save; confirm a durable ID and reopened photos before success.


### Code defects — extension


#### C10 — eBay and Depop marketplace activation fails on accessible forms

**Severity:** High. **Component:** Code defects — extension. **Reproduction rate:** eBay 3/3 attempted fills across two fixtures; Depop 1/1 isolated fill.

**Preconditions:** Signed-in Vendoo, saved audit draft, current extension.

**Exact reproduction:** Run all-platform job and retry eBay; select Depop only and update; manually navigate same draft to the corresponding form.

**Expected:** Activate the mounted marketplace form and proceed with required specifics.

**Actual:** Could not activate ebay/depop marketplace section; forms were accessible through manual navigation.

**Evidence:** [final-eb8bad1d1e1f-events.json](audit-artifacts-2026-09-13/final-eb8bad1d1e1f-events.json); [final-0093f5d1dd0f-events.json](audit-artifacts-2026-09-13/final-0093f5d1dd0f-events.json); [vendoo-ebay-inputs.json](audit-artifacts-2026-09-13/vendoo-ebay-inputs.json); [depop-after-attempt.json](audit-artifacts-2026-09-13/depop-after-attempt.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Likely timing/visibility/first-matching-nav assumptions in activateMarketplaceSection, sectionLooksActive and readiness checks (4173, 4226, 4296–4336); exact failing DOM predicate not instrumented.

**Source:** [vendoo-extension/content-scripts/vendoo.js:4296](vendoo-extension/content-scripts/vendoo.js#L4296).

**User impact / data-loss or publication risk:** eBay/Depop draft incomplete; first platform failure prevents later platforms in a combined run.

**Recommended fix:** Activate the mounted marketplace form and proceed with required specifics. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Test real async mounted/offscreen/duplicate nav elements; wait for correct form identity, not initial visibility alone.

**Manual regression:** Start at General and each other marketplace tab, then fill eBay/Depop with slow loading and verify saved specifics.


### Code defects — verification


#### C11 — Audit stages and completion do not verify saved accuracy

**Severity:** High. **Component:** Code defects — verification. **Reproduction rate:** Schema plus three isolated marketplace completions; all lacked photos.

**Preconditions:** Current draft pipeline.

**Exact reproduction:** Observe completed audit stages, then reopen the item and compare against approved snapshot.

**Expected:** Any missing required photo/field or mismatched value fails acceptance; audit details reach Studio.

**Actual:** General/marketplace audit returns ok despite omissions; completed Etsy/Posh/Mercari had inaccurate or missing fields.

**Evidence:** [final-saved-draft.json](audit-artifacts-2026-09-13/final-saved-draft.json); [final-eb8bad1d1e1f-events.json](audit-artifacts-2026-09-13/final-eb8bad1d1e1f-events.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** auditGeneral checks six fields and returns ok true (4129); marketplace audit at 4340–4365 also returns ok on missing controls. Background step payload at 588–595 drops audit fields.

**Source:** [vendoo-extension/content-scripts/vendoo.js:4102](vendoo-extension/content-scripts/vendoo.js#L4102).

**User impact / data-loss or publication risk:** False success can cause a user to trust an incomplete listing. Publication was not observed.

**Recommended fix:** Any missing required photo/field or mismatched value fails acceptance; audit details reach Studio. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Mutate one saved field/photo at a time; completion must fail and show expected/actual differences.

**Manual regression:** Independently reopen every completed draft and compare all photos, required fields and publication statuses.


### Code defects — validation


#### C12 — Marketplace and canonical constraints are largely unenforced

**Severity:** High. **Component:** Code defects — validation. **Reproduction rate:** 46 cases: 37 accepted, 7 blocked, 2 exceptions.

**Preconditions:** Approved fixture independently modified one field per case.

**Exact reproduction:** Run validation-matrix.py and compare canonical enums, required fields, eligibility and title rules.

**Expected:** Reject invalid selected-marketplace payloads with one precise field error before snapshot/dispatch.

**Actual:** Whitespace/81-character titles, bad categories/dimensions, missing facts, invalid Depop/Etsy values and modern Etsy eligibility were accepted; eBay checks only four optional warnings.

**Evidence:** [validation-matrix.json](audit-artifacts-2026-09-13/validation-matrix.json); [approved-studio-snapshot.json](audit-artifacts-2026-09-13/approved-studio-snapshot.json); [06-ready-with-unknown-facts.png](audit-artifacts-2026-09-13/06-ready-with-unknown-facts.png).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Pydantic schema is permissive; enum constants and dimensions regex in models/schema.py:18–44 are unused. Marketplace-specific validation is absent or warning-only.

**Source:** [vendoo-studio/server/vendoo_studio/models/validation.py:21](vendoo-studio/server/vendoo_studio/models/validation.py#L21).

**User impact / data-loss or publication risk:** Invalid marketplace data enters approved snapshots and reaches draft workflows; evidence uncertainty receives no warning.

**Recommended fix:** Reject invalid selected-marketplace payloads with one precise field error before snapshot/dispatch. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Parameterize all requested validation cases and selected-platform boundaries; no exceptions on arbitrary JSON types.

**Manual regression:** Independently corrupt each UI field, verify one actionable error, and verify extension receives no invalid snapshot.


### Code defects — upload


#### C13 — Invalid image bytes are accepted when MIME claims image

**Severity:** Medium. **Component:** Code defects — upload. **Reproduction rate:** 1/1 isolated spoofed upload.

**Preconditions:** Disposable conversation; file content not an image, MIME image/jpeg.

**Exact reproduction:** Upload twelve non-image bytes using image/jpeg and a traversal-shaped original filename.

**Expected:** Reject undecodable image bytes; never trust supplied MIME alone.

**Actual:** HTTP 200, dimensions null; bytes saved under safe random name. Tested path did not escape photo directory.

**Evidence:** [isolated-probes.json](audit-artifacts-2026-09-13/isolated-probes.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Allowed MIME returns early; Pillow decode failure at 59 is ignored after writing the file.

**Source:** [vendoo-studio/server/vendoo_studio/services/photos.py:26](vendoo-studio/server/vendoo_studio/services/photos.py#L26).

**User impact / data-loss or publication risk:** Broken photos reach generation/upload; arbitrary non-image bytes stored. Traversal was not reproduced.

**Recommended fix:** Reject undecodable image bytes; never trust supplied MIME alone. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Reject invalid/truncated/spoofed images without stored records or bytes; retain legitimate supported formats.

**Manual regression:** Upload renamed text as jpg and confirm clear rejection with no thumbnail/count change.


### Code defects — generation


#### C14 — Ask Chat omits photos when history already contains editor messages

**Severity:** High. **Component:** Code defects — generation. **Reproduction rate:** 1/1 initial exact-prompt attempt; later generation retry succeeded.

**Preconditions:** Five photos, manual listing revision, no prior analysis.

**Exact reproduction:** Create/edit listing before first photo analysis, then submit the exact supplied Ask Chat prompt.

**Expected:** Analyze attached photos regardless of preceding editor-generated history.

**Actual:** Assistant said photos were unavailable and requested brand/size/measurements despite five uploads.

**Evidence:** [05-chat-cannot-see-photos.png](audit-artifacts-2026-09-13/05-chat-cannot-see-photos.png); [listing-before-send.json](audit-artifacts-2026-09-13/listing-before-send.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** _build_messages only analyzes when prior analysis exists or history length <=2 (313–319); prior revisions/messages can exceed that threshold. Structured notes are not passed to this analysis branch.

**Source:** [vendoo-studio/server/vendoo_studio/routes/chat.py:302](vendoo-studio/server/vendoo_studio/routes/chat.py#L302).

**User impact / data-loss or publication risk:** Incorrect missing-evidence response and unnecessary user re-entry; generation depends on incidental history.

**Recommended fix:** Analyze attached photos regardless of preceding editor-generated history. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** First Ask Chat after manual revision still receives all photos and exact seller notes.

**Manual regression:** Upload tag/ruler fixture, manually edit title, Ask Chat and verify visible tag facts without restating them.


### Code defects — chat


#### C15 — Completed stream remains duplicated until reload

**Severity:** Medium. **Component:** Code defects — chat. **Reproduction rate:** Observed after initial Ask Chat and refinements; exact count not instrumented.

**Preconditions:** Chat response finishes and persists.

**Exact reproduction:** Send prompt; compare persisted assistant response with remaining streamed text; reload.

**Expected:** One assistant response and cleared transient streaming content.

**Actual:** Assistant answer appeared once as persisted content and again as residual stream; reload removed residual view.

**Evidence:** [05-chat-cannot-see-photos.png](audit-artifacts-2026-09-13/05-chat-cannot-see-photos.png).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Controller cleared before stillMine check in completion paths (467–473 and 539–544), preventing intended stream cleanup.

**Source:** [vendoo-studio/src/components/ChatPanel.tsx:467](vendoo-studio/src/components/ChatPanel.tsx#L467).

**User impact / data-loss or publication risk:** Misleading duplicate output; does not prove duplicate persisted assistant messages.

**Recommended fix:** One assistant response and cleared transient streaming content. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** On successful persistence clear stream exactly once and render one message; reload preserves same count.

**Manual regression:** Complete several refinements and verify no duplicated response before/after reload.


### Code defects — chat recovery


#### C16 — Cancelled chat leaves conversation permanently In Progress

**Severity:** Medium. **Component:** Code defects — chat recovery. **Reproduction rate:** 1/1 live cancellation, status still in_progress after later reads.

**Preconditions:** Missing-field Ask Chat streaming on primary disposable listing.

**Exact reproduction:** Use Fields Ask Chat, cancel, reload/read conversation status after stream closes.

**Expected:** Prompt restored and conversation returns to a settled non-generating status.

**Actual:** Prompt restoration worked, but server conversation remained in_progress while no job was active and UI allowed input.

**Evidence:** [ask-chat-missing-field-context.json](audit-artifacts-2026-09-13/ask-chat-missing-field-context.json); final-state.json.

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Cancelled streaming generator can exit before post-stream status reset at 569–588; cancellation cleanup is not in an outer finally.

**Source:** [vendoo-studio/server/vendoo_studio/routes/chat.py:548](vendoo-studio/server/vendoo_studio/routes/chat.py#L548).

**User impact / data-loss or publication risk:** Misleading busy/listing status and unreliable recovery; input itself was preserved in this tested cancel path.

**Recommended fix:** Prompt restored and conversation returns to a settled non-generating status. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Cancel before/after first token and disconnect SSE; assert status reset and database session closure.

**Manual regression:** Cancel Ask Chat, reload, switch listings and return; verify recoverable prompt and accurate status.


#### C17 — Missing-provider prompt is rejected before persistence

**Severity:** High. **Component:** Code defects — chat recovery. **Reproduction rate:** 1/1 isolated POST with unavailable provider.

**Preconditions:** No listing provider; user submits nonempty prompt.

**Exact reproduction:** POST messages with provider unavailable; fetch message history.

**Expected:** Retain submitted prompt and provide direct Settings recovery; Retry restores correct action after reload.

**Actual:** HTTP 400 instructed Settings, but messages remained empty. Frontend clears input before send and keeps retry text only in memory.

**Evidence:** [isolated-probes.json](audit-artifacts-2026-09-13/isolated-probes.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** _require_provider runs before add_message at 543; ChatPanel.tsx:511 clears input and transient lastSendText cannot survive page reload.

**Source:** [vendoo-studio/server/vendoo_studio/routes/chat.py:539](vendoo-studio/server/vendoo_studio/routes/chat.py#L539).

**User impact / data-loss or publication risk:** User-authored instructions can be lost on failure/reload.

**Recommended fix:** Retain submitted prompt and provide direct Settings recovery; Retry restores correct action after reload. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Provider validation failure persists/restores exact submitted prompt across reload; retries do not duplicate it.

**Manual regression:** With provider unavailable, submit a long prompt, reload, reconnect provider and retry the original text.


### Code defects — diagnostic privacy


#### C18 — Form diagnostics contain private account/address values

**Severity:** High. **Component:** Code defects — diagnostic privacy. **Reproduction rate:** Observed in real form/API inspection; sanitized in retained exports.

**Preconditions:** Signed-in account with saved shipping/address configuration.

**Exact reproduction:** Inspect output structure of draft form scraping, limiting review to key names and redacting values.

**Expected:** Diagnostic exports omit account/address/credential fields by default and expose only listing-relevant evidence.

**Actual:** Form data included local delivery address and location/profile fields; account filtering in discovered-field code did not cover every scraper/export path.

**Evidence:** final-saved-draft.json (redacted); source review.

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Generic scraping reads all listings.* controls including account fields; sanitization differs across collectMarketplaceSchemaFields and raw form scraping.

**Source:** [vendoo-extension/content-scripts/vendoo.js:4450](vendoo-extension/content-scripts/vendoo.js#L4450).

**User impact / data-loss or publication risk:** Private account data can enter frontend diagnostics and exported logs/screenshots. No credential value was intentionally retained.

**Recommended fix:** Diagnostic exports omit account/address/credential fields by default and expose only listing-relevant evidence. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Seed fake private address/token fields and assert absent from every diagnostic/frontend/export payload.

**Manual regression:** Run Diagnose/Refresh with a test account and inspect sanitized export for private fields before sharing.


### Code defects — fill log


#### C19 — DOM readback collapses arrays and misreads unchecked switches

**Severity:** Medium. **Component:** Code defects — fill log. **Reproduction rate:** At least two multi-select arrays and two false switches compared.

**Preconditions:** Saved draft with tags arrays and Mercari switches false.

**Exact reproduction:** Compare final form scrape with saved API object and settled UI.

**Expected:** Preserve all multi-select members, booleans and numeric zero.

**Actual:** Form tags reported Woven instead of five members; smartPricing/smartOffers rendered on although saved API has false.

**Evidence:** [final-saved-draft.json](audit-artifacts-2026-09-13/final-saved-draft.json); [poshmark-after-save.json](audit-artifacts-2026-09-13/poshmark-after-save.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Reads .value instead of checkbox.checked and overwrites repeated name/id keys at 4472; no aggregation for multi-select hidden inputs.

**Source:** [vendoo-extension/content-scripts/vendoo.js:4467](vendoo-extension/content-scripts/vendoo.js#L4467).

**User impact / data-loss or publication risk:** False filled/missing counts and incorrect repair context; underlying saved arrays/false values are intact in these cases.

**Recommended fix:** Preserve all multi-select members, booleans and numeric zero. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Readback fixtures with repeated input names, []/false/0/null; compare to saved values without string damage.

**Manual regression:** Refresh a draft with multiple tags and unchecked switches; ensure Fields matches actual controls.


#### C20 — Cached Fields are presented with live-source identity

**Severity:** Medium. **Component:** Code defects — fill log. **Reproduction rate:** 1/1 initial stale read; explicit Refresh corrected General values.

**Preconditions:** Probe cached blank draft, later full General save.

**Exact reproduction:** Open Fields after update without Refresh, compare to reopened draft, then Refresh.

**Expected:** Invalidate stale cache or label its age/source accurately.

**Actual:** Old blank title/price/dimensions persisted in Fields; cached response retained source api+form and no freshness metadata.

**Evidence:** [saved-draft-sanitized.json](audit-artifacts-2026-09-13/saved-draft-sanitized.json); [final-saved-draft.json](audit-artifacts-2026-09-13/final-saved-draft.json); [job-fill-log.json](audit-artifacts-2026-09-13/job-fill-log.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Cached payload reuses original source; ListingEditor.tsx:99–106 prefetch uses staleTime Infinity without job-completion invalidation.

**Source:** [vendoo-studio/server/vendoo_studio/routes/jobs.py:232](vendoo-studio/server/vendoo_studio/routes/jobs.py#L232).

**User impact / data-loss or publication risk:** Incorrect missing-field repairs may overwrite correct saved data; counts cannot be trusted.

**Recommended fix:** Invalidate stale cache or label its age/source accurately. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Save changes after cached probe, then open Fields and require fresh data or explicit stale badge.

**Manual regression:** Update General, reopen Fields without manual refresh and compare each field to Vendoo.


### Code defects — marketplace mapping


#### C21 — Mercari resolves blouse to T-shirts

**Severity:** High. **Component:** Code defects — marketplace mapping. **Reproduction rate:** 1/1 saved Mercari category.

**Preconditions:** Notations short-sleeve button-front blouse, General Women/Tops.

**Exact reproduction:** Run Mercari-only save, reopen and inspect terminal category breadcrumb/API displayPath.

**Expected:** Select an appropriate blouse/shirt terminal category or flag unresolved mapping.

**Actual:** Saved Women > Tops & blouses > T-shirts (ID 161). Job completed.

**Evidence:** [final-saved-draft.json](audit-artifacts-2026-09-13/final-saved-draft.json); [mercari-settled-after-save.json](audit-artifacts-2026-09-13/mercari-settled-after-save.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Likely broad top/T-shirt synonym matching and default category resolution. Exact winning category candidate was not instrumented; General terminal validation does not detect platform semantic mismatch.

**Source:** [vendoo-extension/content-scripts/vendoo.js:2021](vendoo-extension/content-scripts/vendoo.js#L2021).

**User impact / data-loss or publication risk:** Wrong category and dependent size/specifics, reduced listing accuracy.

**Recommended fix:** Select an appropriate blouse/shirt terminal category or flag unresolved mapping. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Category tests distinguish button-front blouse from knit tee using fixture evidence and each platform's terminal vocabulary.

**Manual regression:** Send blouse and tee separately, reopen Mercari category and size options for both.


### Marketplace-policy issues


#### C22 — Etsy save retains fabricated when-made and non-Draft configuration

**Severity:** High. **Component:** Marketplace-policy issues. **Reproduction rate:** 1/1 Etsy-only completed run and reopen.

**Preconditions:** Modern resale blouse; Etsy selected by later user instruction; approved when_made blank.

**Exact reproduction:** Send Etsy draft only; reopen When Made, Listing State and publication status.

**Expected:** Do not invent eligibility/date; require Draft configuration and surface ineligibility before send.

**Actual:** Made To Order persisted, listingState active/Live Listing, actual notListed true. No publication action observed.

**Evidence:** [etsy-saved-When-Was-It-Made.json](audit-artifacts-2026-09-13/etsy-saved-When-Was-It-Made.json); [etsy-saved-Listing-State.json](audit-artifacts-2026-09-13/etsy-saved-Listing-State.json); [final-not-listed.json](audit-artifacts-2026-09-13/final-not-listed.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** No eligibility validation; blank when_made at 3122 skips clearing default; fillEtsyForm does not enforce listingState Draft.

**Source:** [vendoo-extension/content-scripts/vendoo.js:3082](vendoo-extension/content-scripts/vendoo.js#L3082).

**User impact / data-loss or publication risk:** False item facts and unsafe future publication configuration. This is not evidence of an actual safety failure/publication.

**Recommended fix:** Do not invent eligibility/date; require Draft configuration and surface ineligibility before send. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Modern resale fixture blocked/warned; unknown when-made cannot silently become made_to_order; every saved draft enforces Draft.

**Manual regression:** Use modern validation fixture and separate eligible fixture; reopen configuration and actual NOT LISTED state.


### Code defects — marketplace mapping


#### C23 — Platform-specific values are skipped or replaced by General defaults

**Severity:** Medium. **Component:** Code defects — marketplace mapping. **Reproduction rate:** Poshmark color/tags and Etsy color/tags mismatches in reopened draft.

**Preconditions:** Approved platform-specific fields differ from General.

**Exact reproduction:** Save Poshmark/Etsy, reopen and compare colors, platform tags and title with approved object.

**Expected:** Respect marketplace-specific overrides and report unresolvable live values clearly.

**Actual:** Primary colors blank; Poshmark platform styleTags not preserved; Etsy five tags merged with General five; branded Etsy title remains.

**Evidence:** [approved-studio-snapshot.json](audit-artifacts-2026-09-13/approved-studio-snapshot.json); [final-saved-draft.json](audit-artifacts-2026-09-13/final-saved-draft.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Fillers prefer General colors/title/tags; Etsy explicitly merges both tag lists at 3124. Mapping does not consistently consume contract-specific fields.

**Source:** [vendoo-extension/content-scripts/vendoo.js:3093](vendoo-extension/content-scripts/vendoo.js#L3093).

**User impact / data-loss or publication risk:** Completed drafts differ from approval; merged Etsy tags could exceed 13 on other fixtures (not reached here).

**Recommended fix:** Respect marketplace-specific overrides and report unresolvable live values clearly. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Distinct General/platform overrides must survive send/readback; enforce tag limits after merges, or avoid merges.

**Manual regression:** Use intentionally different approved platform tags/colors and compare saved forms exactly.


### Code defects — continuation recovery, import and diagnostics

#### C24 — A late extension result can overwrite Cancelled with Failed

**Severity:** High. **Component:** Code defects — automation cancellation. **Reproduction rate:** 1/1 live cancellation during General fill.

**Preconditions:** Active real-browser job with a content-script request in flight.

**Exact reproduction:** Start a disposable new-item job; cancel while `filling_general`; observe the tab close and Cancelled events; wait for the in-flight message channel to close.

**Expected:** Cancelled is terminal; late step results are ignored.

**Actual:** Job `b587781cacc3` was cancelled and its tab closed, then changed to Failed at `filling_general` with `sendMessage failed: A listener indicated an asynchronous response ... channel closed`.

**Evidence:** [cancel-late-result-job.json](audit-artifacts-2026-09-13/recovery-continuation/cancel-late-result-job.json); [cancel-late-result-events.json](audit-artifacts-2026-09-13/recovery-continuation/cancel-late-result-events.json).

**Console evidence:** The content-script message-channel error is retained in the sanitized job/event artifacts.

**Network evidence:** No HTTP failure caused this result; it arrived through the paired extension channel after cancellation.

**Job-event evidence:** Two Cancelled events precede the later `step_failed` event for the same job.

**Likely root cause:** `runJob` checks cancellation only before awaiting a step, then unconditionally reports the result at lines 561–579. Backend `job.step_failed` at lines 512–534 overwrites status without rejecting terminal Cancelled jobs.

**Source:** [vendoo-extension/background.js:561](vendoo-extension/background.js#L561); [vendoo-studio/server/vendoo_studio/routes/extension.py:512](vendoo-studio/server/vendoo_studio/routes/extension.py#L512).

**User impact / data-loss or publication risk:** Users cannot trust cancellation state or know whether a save completed. A late successful save could also leave remote state that the cancelled UI does not explain.

**Recommended fix:** Add a cancellation generation/token check after every awaited step and make terminal backend states monotonic.

**Automated regression:** Cancel while a deferred step is pending; resolve/reject it afterward; assert the job remains Cancelled and no later event changes status.

**Manual regression:** Cancel at upload, General fill and marketplace save; wait for all in-flight work; verify stable Cancelled state and accurate remote draft state.

#### C25 — Whole-note autosave can erase the saved Vendoo binding

**Severity:** High. **Component:** Code defects — data integrity. **Reproduction rate:** 1/1 isolated stale-note sequence; missing binding observed on the live primary conversation.

**Preconditions:** Seller-details component holds an older `conv.notes` value while another flow adds `vendooItemId`/`vendooUrl`.

**Exact reproduction:** Capture old seller notes; write a Vendoo binding; submit a later seller edit built from the old notes through the real PATCH route.

**Expected:** Seller edits merge server-side with current notes and preserve independently written bindings.

**Actual:** Final notes contained seller fields but no Vendoo binding. The live UI then offered generic Send and opened a new-item job instead of Update.

**Evidence:** [binding-after-cancel.json](audit-artifacts-2026-09-13/recovery-continuation/binding-after-cancel.json); [recovery-probes.json](audit-artifacts-2026-09-13/recovery-continuation/recovery-probes.json).

**Console evidence:** No console error; both writes succeed, making this silent lost-update behavior.

**Network evidence:** The real PATCH endpoint accepts the entire stale notes string without version/precondition enforcement.

**Job-event evidence:** Prior job retained `tYhkw1rewBBuMnSmjpzt`; later job `b587781cacc3` had no item ID and opened the new-item path.

**Likely root cause:** `ItemDetails.save` spreads the render-time `conv.notes` snapshot and PATCH replaces the full notes column at `conversations.py:128–132`; no server-side merge, revision or compare-and-swap exists.

**Source:** [vendoo-studio/src/components/ItemDetails.tsx:159](vendoo-studio/src/components/ItemDetails.tsx#L159); [vendoo-studio/server/vendoo_studio/routes/conversations.py:128](vendoo-studio/server/vendoo_studio/routes/conversations.py#L128).

**User impact / data-loss or publication risk:** A later Send can create another draft or target the wrong workflow because Studio forgets the existing item identity.

**Recommended fix:** Store binding separately or merge typed note fields atomically on the server with an optimistic concurrency token.

**Automated regression:** Interleave binding and seller-detail writes from stale clients; assert both survive and Send remains Update.

**Manual regression:** Save seller fields while a draft binding is added/refreshed; reload and confirm the exact same draft ID remains attached.

#### C26 — Diagnose Page cannot execute its serialized collector

**Severity:** Medium. **Component:** Code defects — extension diagnostics. **Reproduction rate:** 1/1 real popup attempt with no download; 1/1 isolated serialization reproduction.

**Preconditions:** Extension popup open on the disposable Vendoo draft.

**Exact reproduction:** Click Diagnose Page; check Downloads; serialize `collectPageDiagnostics` exactly as `chrome.scripting.executeScript({func})` does and invoke it in an isolated page context.

**Expected:** A sanitized diagnostic JSON downloads and the popup reports field/dropdown counts.

**Actual:** No diagnostic file downloaded. Isolated execution throws `ReferenceError: COLLECTOR_VERSION is not defined`.

**Evidence:** [diagnostic-isolation-probe.json](audit-artifacts-2026-09-13/recovery-continuation/diagnostic-isolation-probe.json); [extension-popup.png](audit-artifacts-2026-09-13/recovery-continuation/extension-popup.png).

**Console evidence:** The popup closes when Chrome focuses the target tab; the caught error was not durably surfaced after closure.

**Network evidence:** Not applicable; the failure occurs before download creation.

**Job-event evidence:** Diagnostics are popup-triggered and create no automation job.

**Likely root cause:** The injected function references module-scope `COLLECTOR_VERSION`; Chrome serializes `func` without its lexical environment.

**Source:** [vendoo-extension/diagnostic-collector.js:3](vendoo-extension/diagnostic-collector.js#L3); [vendoo-extension/background.js:2106](vendoo-extension/background.js#L2106).

**User impact / data-loss or publication risk:** Users lose the primary recovery artifact when Vendoo selectors change; no publication risk observed.

**Recommended fix:** Make the injected collector self-contained or inject a file, then sanitize/download and persist a recoverable result.

**Automated regression:** Execute the serialized collector in a clean page realm and assert a structured result without free-variable errors.

**Manual regression:** Run Diagnose Page on General and every marketplace; verify a sanitized file and matching popup counts.

#### C27 — Import photo download permits server-side requests to loopback/private targets

**Severity:** High. **Component:** Code defects — security. **Reproduction rate:** 1/1 benign loopback probe.

**Preconditions:** Local Studio HTTP API reachable; no authentication is required by the import route.

**Exact reproduction:** In a disposable DB, run a benign PNG server on `127.0.0.1`; POST its URL in `image_urls` to `/api/imports/vendoo`.

**Expected:** Accept only trusted Vendoo/CDN image hosts and reject loopback, private, link-local and redirect-to-private destinations.

**Actual:** Import returned 200, requested `/audit-image.png` from loopback, and stored one photo.

**Evidence:** [import-loopback-probe.json](audit-artifacts-2026-09-13/recovery-continuation/import-loopback-probe.json).

**Console evidence:** No error; the request was treated as a normal import.

**Network evidence:** The benign local HTTP server recorded the request. No private service or credential endpoint was contacted.

**Job-event evidence:** Import created an `imported` job; no browser automation ran.

**Likely root cause:** `image_urls_from_vendoo` accepts arbitrary HTTP(S) URLs and `httpx.AsyncClient` follows redirects without hostname/IP validation.

**Source:** [vendoo-studio/server/vendoo_studio/services/vendoo_import.py:188](vendoo-studio/server/vendoo_studio/services/vendoo_import.py#L188); [vendoo-studio/server/vendoo_studio/services/vendoo_import.py:234](vendoo-studio/server/vendoo_studio/services/vendoo_import.py#L234).

**User impact / data-loss or publication risk:** Any web origin allowed to reach the loopback API could make Studio probe local/private network resources; response bytes are processed and written as photos.

**Recommended fix:** Require authorized import requests, allowlist expected HTTPS image hosts, resolve and reject non-public IPs on every redirect, and cap bytes before buffering.

**Automated regression:** Reject loopback/private/link-local/IPv6/encoded/redirect targets; allow a fixture on an approved public host.

**Manual regression:** Import the disposable Vendoo draft and confirm approved CDN photos still download while local URLs are rejected clearly.

#### C28 — Imported conversations are permanently classified as busy

**Severity:** Medium. **Component:** Code defects — import lifecycle. **Reproduction rate:** 1/1 live import; 1/1 isolated settle request.

**Preconditions:** Successful Vendoo import.

**Exact reproduction:** Import the disposable draft, then use Settle or POST the settle route.

**Expected:** Import ends in a stable, settleable local state.

**Actual:** Import forces conversation status to `listing`; `listing` is a busy status, so Settle returns 409 “Cannot settle a listing that is still in progress” even though no automation job is active.

**Evidence:** [import-jobs.json](audit-artifacts-2026-09-13/recovery-continuation/import-jobs.json); [import-loopback-probe.json](audit-artifacts-2026-09-13/recovery-continuation/import-loopback-probe.json).

**Console evidence:** No client crash; lifecycle status is internally inconsistent.

**Network evidence:** Import returned 200; settle returned 409.

**Job-event evidence:** The only imported job is terminal status `imported`; active-job count remained zero.

**Likely root cause:** Import explicitly calls `update_status(..., "listing")`; settle rejects every `listing` conversation via `BUSY_LISTING_STATUSES`.

**Source:** [vendoo-studio/server/vendoo_studio/routes/imports.py:124](vendoo-studio/server/vendoo_studio/routes/imports.py#L124); [vendoo-studio/server/vendoo_studio/routes/conversations.py:99](vendoo-studio/server/vendoo_studio/routes/conversations.py#L99).

**User impact / data-loss or publication risk:** Imported records cannot use normal lifecycle cleanup and appear perpetually active.

**Recommended fix:** Give imported drafts a terminal imported/draft conversation state, or derive busy state from active jobs rather than the generic `listing` label.

**Automated regression:** Import then settle/unsettle; assert no active-job conflict and stable persistence.

**Manual regression:** Import the disposable draft, settle it, reload, then reopen without losing binding or fields.

#### C29 — Empty Ask Chat response finishes without an error or assistant record

**Severity:** Medium. **Component:** Code defects — chat recovery. **Reproduction rate:** 1/1 isolated empty stream.

**Preconditions:** Configured provider returns an empty stream.

**Exact reproduction:** Submit Ask Chat through the real route with a provider stub yielding no items; read SSE and message history.

**Expected:** Clear empty-response error, persisted user prompt, and a retry action identifying the failed request.

**Actual:** Route returns only `[DONE]`, persists the prompt, creates no assistant/error message, leaves listing/revision unchanged, and resets to Draft.

**Evidence:** [recovery-probes.json](audit-artifacts-2026-09-13/recovery-continuation/recovery-probes.json).

**Console evidence:** No server exception because empty output is accepted on the general Ask Chat path.

**Network evidence:** HTTP 200 with a successful-looking terminal SSE marker and no error event.

**Job-event evidence:** Ask Chat is not an automation job.

**Likely root cause:** `send_message.stream_response` validates/persists only when `full_text` is truthy and always emits `[DONE]`; unlike listing generation it has no empty-response guard.

**Source:** [vendoo-studio/server/vendoo_studio/routes/chat.py:547](vendoo-studio/server/vendoo_studio/routes/chat.py#L547).

**User impact / data-loss or publication risk:** The user sees an unexplained no-op and cannot distinguish provider failure from a successful unchanged response.

**Recommended fix:** Emit a typed error event for empty output, retain the exact prompt, and make Retry restore that action.

**Automated regression:** Empty and whitespace streams must produce a visible recoverable error without changing listing/revision.

**Manual regression:** Simulate empty provider response; verify prompt restoration, direct recovery text and successful retry.

#### C30 — Offline seller-details autosave gets stuck and loses the edit

**Severity:** High. **Component:** Code defects — autosave recovery. **Reproduction rate:** 1/1 live Studio-tab network interruption.

**Preconditions:** Existing imported disposable listing; Studio frontend network forced Offline only for that test tab.

**Exact reproduction:** Edit Condition; wait past the 500 ms debounce; observe request failure; restore network; wait; reload.

**Expected:** Saving changes to a visible error, preserves the unsaved value, and retries or offers Retry after connectivity returns.

**Actual:** UI remained `SAVING…`, console logged an unhandled promise rejection at `ItemDetails.tsx:171/190`, no recovery action appeared, and the edit disappeared after reload.

**Evidence:** [offline-autosave.png](audit-artifacts-2026-09-13/recovery-continuation/offline-autosave.png); [offline-autosave-result.json](audit-artifacts-2026-09-13/recovery-continuation/offline-autosave-result.json).

**Console evidence:** `net::ERR_INTERNET_DISCONNECTED`; `Uncaught (in promise)` from `client.ts:24`, `client.ts:56`, `ItemDetails.tsx:171`, `ItemDetails.tsx:190`.

**Network evidence:** PATCH failed while the tab was Offline; no automatic request followed network restoration.

**Job-event evidence:** No automation job was active; this is local autosave loss.

**Likely root cause:** `save` awaits the API with no catch/finally; rejection skips invalidation and `setSaving(false)`. Debounced state has no durable retry queue.

**Source:** [vendoo-studio/src/components/ItemDetails.tsx:159](vendoo-studio/src/components/ItemDetails.tsx#L159).

**User impact / data-loss or publication risk:** Seller-entered condition, measurements, costs or dimensions can be silently lost during transient network/backend failure.

**Recommended fix:** Catch and display failures, clear Saving in finally, retain dirty state, and retry with version-aware conflict handling.

**Automated regression:** Reject a debounced save, restore transport, assert visible error/dirty state and successful retry without stale overwrite.

**Manual regression:** Toggle Studio offline during each seller field; verify no value disappears after recovery/reload.

#### C31 — Import loses labels and treats a photo-less bound draft as Ready

**Severity:** High. **Component:** Code defects — import fidelity/validation. **Reproduction rate:** 1/1 live import of the verified disposable draft.

**Preconditions:** Saved Vendoo draft `tYhkw1rewBBuMnSmjpzt` with no photos and root-level label IDs.

**Exact reproduction:** Import through the extension; reload the imported record; compare approved snapshot, cached Vendoo item and imported Studio JSON.

**Expected:** Preserve every representable value, warn about unmapped values, show missing photos, and block Ready/Update until required content is complete.

**Actual:** Title/description/price/brand/size/dimensions matched, but approved label `To List` became `[]`, `Multi` became `Multicolor`, photo count stayed zero, and Studio still displayed Ready with Update enabled.

**Evidence:** [imported-listing.json](audit-artifacts-2026-09-13/recovery-continuation/imported-listing.json); [imported-photos.json](audit-artifacts-2026-09-13/recovery-continuation/imported-photos.json); [imported-reloaded.png](audit-artifacts-2026-09-13/recovery-continuation/imported-reloaded.png).

**Console evidence:** No mapping or missing-photo error was shown after import/reload.

**Network evidence:** Import returned 200 with `photo_count: 0`; listing GET returned `can_send: true` and no errors.

**Job-event evidence:** Import job `531a96b3b0e6` retained the correct item ID/URL; no update job was created after confirmation was declined.

**Likely root cause:** Import reads labels only from `generalDetails`, while Vendoo returned root-level label IDs; listing validation disables photo requirements whenever a Vendoo binding exists.

**Source:** [vendoo-studio/server/vendoo_studio/services/vendoo_import.py:138](vendoo-studio/server/vendoo_studio/services/vendoo_import.py#L138); [vendoo-studio/server/vendoo_studio/routes/listings.py:54](vendoo-studio/server/vendoo_studio/routes/listings.py#L54).

**User impact / data-loss or publication risk:** Re-import can silently drop workflow labels and invite an incomplete zero-photo update while claiming Ready.

**Recommended fix:** Map root label IDs through the live label registry, report unmapped values, preserve canonical color vocabulary, and validate bound updates against explicit photo/readback policy.

**Automated regression:** Import root/general labels, canonical colors and zero/five photos; compare round-trip JSON and Ready state exactly.

**Manual regression:** Import the disposable draft, compare all fields/photos, and verify incomplete imports cannot appear Ready.

### UX defects


#### U01 — Send appears enabled while invalid and errors are duplicated

**Severity:** Medium. **Component:** UX defects. **Reproduction rate:** Live invalid editor plus repeated required-field matrix cases.

**Preconditions:** Missing title/description/price or other blocked values.

**Exact reproduction:** Open invalid listing, inspect button appearance, validation errors and click behavior.

**Expected:** Disabled or clearly unavailable Send, one actionable error per field, focus/link to field.

**Actual:** Green enabled-looking Send; click handler blocks, but duplicated required/Pydantic errors appear as combined text without clear focus targets.

**Evidence:** [02-invalid-new-listing.png](audit-artifacts-2026-09-13/02-invalid-new-listing.png); [05-chat-cannot-see-photos.png](audit-artifacts-2026-09-13/05-chat-cannot-see-photos.png); [validation-matrix.json](audit-artifacts-2026-09-13/validation-matrix.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** disabled only covers pending; click guards canSend at 666. validation.py:41 adds duplicate required errors after Pydantic.

**Source:** [vendoo-studio/src/components/ListingEditor.tsx:664](vendoo-studio/src/components/ListingEditor.tsx#L664).

**User impact / data-loss or publication risk:** Confusing readiness and recovery; invalid-title click was not observed to dispatch.

**Recommended fix:** Disabled or clearly unavailable Send, one actionable error per field, focus/link to field. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Disabled state matches can_send and one error per field; keyboard error activation focuses control.

**Manual regression:** Clear required fields and use mouse/keyboard; confirm clear unavailable state and direct recovery.


#### U02 — Unconfigured provider blocks drafting and still displays a model

**Severity:** Medium. **Component:** UX defects. **Reproduction rate:** Static plus transient initial loading state; full logout UI not run.

**Preconditions:** Provider not configured or status pending.

**Exact reproduction:** Inspect create controls and ProviderStatus rendering with absent provider data.

**Expected:** Manual draft creation remains usable; disconnected status explains provider setup without implying a model connection.

**Actual:** Create disabled via providerConfigured; status defaults to mimo-v2.5-pro regardless of connection.

**Evidence:** [isolated-probes.json](audit-artifacts-2026-09-13/isolated-probes.json); source review.

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** canCreate is tied to provider availability at 231; ProviderStatus.tsx:11–16 displays fallback model unconditionally.

**Source:** [vendoo-studio/src/app/App.tsx:74](vendoo-studio/src/app/App.tsx#L74).

**User impact / data-loss or publication risk:** Manual workflow blocked unnecessarily and connection state misleading; persistent missing-provider UI remains a retest gap.

**Recommended fix:** Manual draft creation remains usable; disconnected status explains provider setup without implying a model connection. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Render disconnected/pending/connected fixtures; manual creation works and model shown only with qualified connection status.

**Manual regression:** Remove provider in isolated setup, create manual listing, and follow direct provider recovery.


#### U03 — Category and label placeholders resemble saved values

**Severity:** Low. **Component:** UX defects. **Reproduction rate:** Observed in both test listings.

**Preconditions:** Seller override fields are empty.

**Exact reproduction:** Inspect Category/Labels without typing; compare actual saved notes.

**Expected:** Examples clearly distinct from populated values.

**Actual:** Clothing >… and To List, A19 look populated though controls are empty.

**Evidence:** [05-chat-cannot-see-photos.png](audit-artifacts-2026-09-13/05-chat-cannot-see-photos.png); [layout-1280x800-verified.png](audit-artifacts-2026-09-13/layout-1280x800-verified.png).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Concrete example placeholders styled like editable field content; default/example versus stored data is not visually explicit.

**Source:** [vendoo-studio/src/components/ItemDetails.tsx:92](vendoo-studio/src/components/ItemDetails.tsx#L92).

**User impact / data-loss or publication risk:** Seller may assume category/labels have been saved; no direct data loss observed.

**Recommended fix:** Examples clearly distinct from populated values. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Empty seller controls expose explicit empty state and never serialize placeholder content.

**Manual regression:** Open untouched listing and distinguish examples from saved values without clicking fields.


#### U04 — Later editor tabs require undisclosed horizontal scrolling

**Severity:** Low. **Component:** UX defects. **Reproduction rate:** Three desktop sizes plus 390px mobile; tablet fits.

**Preconditions:** All five implemented marketplaces selected.

**Exact reproduction:** Inspect initial tab strip at requested exact viewport sizes; measure last tab bounding box.

**Expected:** Visible affordance for more tabs or responsive layout that makes all tabs discoverable.

**Actual:** JSON extends beyond editor/viewport initially; overflow scroll exists, scrollbar hidden.

**Evidence:** [layout-1280x800-verified.png](audit-artifacts-2026-09-13/layout-1280x800-verified.png); [mobile-all-platform-tabs.png](audit-artifacts-2026-09-13/mobile-all-platform-tabs.png); [tablet-editor-820x1180.png](audit-artifacts-2026-09-13/tablet-editor-820x1180.png).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Scrollable tab-group plus zero-height scrollbar at 2569; fixed narrow editor exposes no cue.

**Source:** [vendoo-studio/src/styles/app.css:2553](vendoo-studio/src/styles/app.css#L2553).

**User impact / data-loss or publication risk:** Users miss JSON/later tabs; not proof of unreachable controls.

**Recommended fix:** Visible affordance for more tabs or responsive layout that makes all tabs discoverable. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** At all target sizes, each tab is discoverable and reachable through keyboard/touch with visible overflow cue.

**Manual regression:** Find and activate every tab without prior knowledge of hidden horizontal scrolling.


#### U05 — Mobile Settings has no reachable exit to listings

**Severity:** Medium. **Component:** UX defects. **Reproduction rate:** 1/1 at 390px; desktop recovery worked.

**Preconditions:** Mobile Settings open.

**Exact reproduction:** Tap Back to listings, inspect Settings sidebar; try Escape and visible controls.

**Expected:** Back exits Settings and returns to listing list.

**Actual:** Back opens Settings navigation; actual close-Settings button is in hidden footer. Escape only changes sidebar visibility.

**Evidence:** [mobile-settings-no-exit.png](audit-artifacts-2026-09-13/mobile-settings-no-exit.png).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Mobile hides sidebar-footer containing onCloseSettings (ListingSidebar.tsx:565–574); App.tsx:249 only sets mobileSidebarOpen.

**Source:** [vendoo-studio/src/styles/app.css:3792](vendoo-studio/src/styles/app.css#L3792).

**User impact / data-loss or publication risk:** Mobile user trapped in Settings until reload/alternate navigation.

**Recommended fix:** Back exits Settings and returns to listing list. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Mobile Settings exit visible and returns activeView to listings; keyboard/Escape contract explicit.

**Manual regression:** On phone/iPad, open Settings, switch section, return to listings without reload.


### UX defects — accessibility


#### U06 — Zoom restriction, focus hiding and field semantics impair accessibility

**Severity:** Medium. **Component:** UX defects — accessibility. **Reproduction rate:** One Lighthouse snapshot, one real aria-hidden console warning, and 1/1 isolated first-run keyboard test.

**Preconditions:** Desktop/mobile UI and current DOM.

**Exact reproduction:** Run snapshot audit; move between mobile sidebar/panes with focus retained; open the setup-guide modal and press Tab; inspect viewport meta and field controls.

**Expected:** Allow zoom, maintain visible focus outside aria-hidden content, valid roles and sufficient text contrast.

**Actual:** maximum-scale=1; retained focus inside hidden sidebar; button role=listitem; job text contrast 4.41:1. In the setup guide, Tab moved focus to the underlying “Open Settings” control outside the modal; Escape did close the guide.

**Evidence:** [accessibility-failures.json](audit-artifacts-2026-09-13/accessibility-failures.json); [browser-console-final.txt](audit-artifacts-2026-09-13/browser-console-final.txt); [isolated-first-run-results.json](audit-artifacts-2026-09-13/recovery-continuation/isolated-first-run-results.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Viewport restriction plus mobile aria-hidden toggling in ListingSidebar.tsx:364; FillLogPanel button semantics and low-contrast styling; FirstRunGuide declares a dialog but does not trap/restore focus.

**Source:** [vendoo-studio/index.html:5](vendoo-studio/index.html#L5); [vendoo-studio/src/components/FirstRunGuide.tsx:175](vendoo-studio/src/components/FirstRunGuide.tsx#L175).

**User impact / data-loss or publication risk:** Low-vision/keyboard/assistive technology barriers; full screen-reader impact not tested.

**Recommended fix:** Allow zoom, maintain visible focus outside aria-hidden content, valid roles and sufficient text contrast. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** axe/DOM checks and keyboard focus assertions at all viewports; allow 200% zoom and >=4.5 contrast.

**Manual regression:** Zoom to 200%, navigate dialogs/sidebar/Fields by keyboard and screen reader without focus loss.


### UX defects — uploads


#### U07 — Partial upload failure hides that a valid photo was saved

**Severity:** Medium. **Component:** UX defects — uploads. **Reproduction rate:** 1/1 live mixed batch; 1/1 isolated mixed batch.

**Preconditions:** One valid photo plus unsupported text in same UI upload.

**Exact reproduction:** Upload both files together; observe error and fetch photo list.

**Expected:** Per-file outcomes or transactional rollback; successful photo count refreshed.

**Actual:** HTTP 400 unsupported type but valid photo was already stored; UI presented batch error without explaining partial success.

**Evidence:** [isolated-probes.json](audit-artifacts-2026-09-13/isolated-probes.json); [ui-unsupported-upload.json](audit-artifacts-2026-09-13/ui-unsupported-upload.json); [final-842b7f1762be-photos.json](audit-artifacts-2026-09-13/final-842b7f1762be-photos.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Loop commits earlier photos before later failure; PhotoTray catch does not reconcile partial server result.

**Source:** [vendoo-studio/server/vendoo_studio/routes/photos.py:32](vendoo-studio/server/vendoo_studio/routes/photos.py#L32).

**User impact / data-loss or publication risk:** Users may retry and create duplicates or misread photo counts; duplicate creation itself not tested.

**Recommended fix:** Per-file outcomes or transactional rollback; successful photo count refreshed. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Mixed batch returns explicit saved/failed list and UI reconciles exactly once.

**Manual regression:** Upload valid+invalid files, retry only failed one, and verify predictable count/order.


### UX defects — platform scope


#### U08 — Four selectable marketplaces are silently omitted from sending

**Severity:** Medium. **Component:** UX defects — platform scope. **Reproduction rate:** All nine selected; dispatch filtering inspected.

**Preconditions:** Facebook, Grailed, Whatnot or Shopify selected.

**Exact reproduction:** Select All; compare catalog fillable flags and dispatch platform list.

**Expected:** Clearly identify unavailable send support or implement the selected workflow.

**Actual:** UI offers all nine; four have fillable false and are filtered without a Settings warning. Empty Fields views have an unsupported message, but inherited-field views can omit it.

**Evidence:** [all-marketplaces.json](audit-artifacts-2026-09-13/all-marketplaces.json).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** selected_fillable_marketplaces restricts to five while Settings labels selection as controlling Send.

**Source:** [vendoo-studio/server/vendoo_studio/services/marketplaces.py:64](vendoo-studio/server/vendoo_studio/services/marketplaces.py#L64).

**User impact / data-loss or publication risk:** User reasonably expects every selected platform tested/sent; unavailable workflows hidden.

**Recommended fix:** Clearly identify unavailable send support or implement the selected workflow. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Selection UI accurately reflects supported send targets; unsupported selected target produces explicit blocker.

**Manual regression:** Select each platform individually and verify either real saved form or a clear unsupported explanation.


### Test-coverage gaps


#### T01 — Backend suite has a reproducible provider default expectation failure

**Severity:** Medium. **Component:** Test-coverage gaps. **Reproduction rate:** Full run 1 failure; individual retry also fails.

**Preconditions:** Current main and documented venv.

**Exact reproduction:** Run full pytest command, then exact failing node.

**Expected:** Current provider contract and tests agree with isolated defaults.

**Actual:** Expected gpt-5.5, received gpt-5.6-luna; 307 passed and one failed.

**Evidence:** [backend-tests.log](audit-artifacts-2026-09-13/backend-tests.log); [backend-failure-retest.log](audit-artifacts-2026-09-13/backend-failure-retest.log).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Hardcoded test model expectation differs from effective configured/default model; test isolation/default contract needs resolution.

**Source:** [vendoo-studio/server/tests/test_chatgpt_oauth.py:272](vendoo-studio/server/tests/test_chatgpt_oauth.py#L272).

**User impact / data-loss or publication risk:** CI-equivalent checks not green; does not alone establish broken provider connection.

**Recommended fix:** Current provider contract and tests agree with isolated defaults. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Pin expected contract or isolate settings correctly; rerun full suite and individual node.

**Manual regression:** Confirm Settings shows the selected model before and after provider reconnect.


### Documentation problems


#### D01 — Doctor says Ready after identifying a startup-blocking occupied port

**Severity:** Low. **Component:** Documentation problems. **Reproduction rate:** 1/1 initial doctor run.

**Preconditions:** Existing packaged Studio owns 4318.

**Exact reproduction:** Run doctor, then start.sh.

**Expected:** Final readiness verdict distinguishes blocking port conflict and gives exact recovery.

**Actual:** Doctor warns occupied port then prints Ready; start correctly refuses.

**Evidence:** [doctor-initial.log](audit-artifacts-2026-09-13/doctor-initial.log); [start-conflict.log](audit-artifacts-2026-09-13/start-conflict.log).

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Port warning does not affect final Ready at line 88.

**Source:** [vendoo-studio/scripts/doctor.sh:78](vendoo-studio/scripts/doctor.sh#L78).

**User impact / data-loss or publication risk:** Confusing installation recovery; no stale process silently reused in this audit.

**Recommended fix:** Final readiness verdict distinguishes blocking port conflict and gives exact recovery. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Occupied-port fixture produces non-ready verdict/exit and correct recovery command.

**Manual regression:** Run doctor beside an existing Studio process and verify final status is unambiguous.


#### D02 — Canonical skill and reference template disagree on listing rules

**Severity:** Medium. **Component:** Documentation problems. **Reproduction rate:** Multiple static conflicts.

**Preconditions:** Generation/validation consumes canonical skill and referenced template.

**Exact reproduction:** Compare price precision, title variants and description constraints.

**Expected:** One explicit coherent contract for every platform.

**Actual:** Skill requires whole dollars while template requires eBay/Etsy .99; description length/measurement placement and Etsy title differ.

**Evidence:** [approved-studio-snapshot.json](audit-artifacts-2026-09-13/approved-studio-snapshot.json); canonical source files.

**Console evidence:** See cited live console artifact where applicable; otherwise no finding-specific console record was captured. No absence-of-error claim is inferred.

**Network evidence:** HTTP statuses are stated above for API probes; live job requests are represented by the cited event/readback records. A complete HAR was not captured.

**Job-event evidence:** C08–C11, C21–C23 and fill-log findings use primary/ordinary-send final event artifacts. Isolated, UI-only and static findings did not require a real automation job.

**Likely root cause:** Referenced template lines 16, 34, 102–115 has incompatible requirements with main skill/user fixture format.

**Source:** [skills/list-this/SKILL.md:296](skills/list-this/SKILL.md#L296).

**User impact / data-loss or publication risk:** Cannot consistently validate or generate all outputs; fixes need a documented precedence decision.

**Recommended fix:** One explicit coherent contract for every platform. Address the cited cause; no fix was implemented during this audit.

**Automated regression:** Contract tests assert a single price/title/description policy across prompts, schema and extension.

**Manual regression:** Generate the same fixture through canonical skill and Studio; compare exact required formatting.

## Appendix A — independent strict-validation cases

Each case started from the approved fixture and changed one condition. These results are current-code validation, not proof that each invalid case was actually transmitted to the live extension. Accepted means the backend validator allowed it; UI focus/duplicate behavior was not exercised separately for every row.

| Case | Result | Errors / warnings or exception |
|---|---|---|
| baseline | ACCEPTED | {"errors": [], "warnings": []} |
| missing title | BLOCKED | {"errors": [{"field": "title", "message": "title: Field required"}, {"field": "title", "message": "title is required"}], "warnings": []} |
| missing description | BLOCKED | {"errors": [{"field": "description", "message": "description: Field required"}, {"field": "description", "message": "description is required"}], "warnings": []} |
| missing price | BLOCKED | {"errors": [{"field": "price", "message": "price: Field required"}, {"field": "price", "message": "price is required"}], "warnings": []} |
| missing brand | ACCEPTED | {"errors": [], "warnings": []} |
| missing size | ACCEPTED | {"errors": [], "warnings": []} |
| missing sku | ACCEPTED | {"errors": [], "warnings": []} |
| missing weight_lb | ACCEPTED | {"errors": [], "warnings": []} |
| missing weight_oz | ACCEPTED | {"errors": [], "warnings": []} |
| blank title | ACCEPTED | {"errors": [], "warnings": []} |
| empty title | BLOCKED | {"errors": [{"field": "title", "message": "title: String should have at least 1 character"}, {"field": "title", "message": "title is required"}], "warnings": []} |
| overlong title | ACCEPTED | {"errors": [], "warnings": []} |
| wrong title formula | ACCEPTED | {"errors": [], "warnings": []} |
| wrong description | ACCEPTED | {"errors": [], "warnings": []} |
| zero price | BLOCKED | {"errors": [{"field": "price", "message": "price: Input should be greater than 0"}, {"field": "price", "message": "price is required"}], "warnings": []} |
| negative price | BLOCKED | {"errors": [{"field": "price", "message": "price: Input should be greater than 0"}], "warnings": []} |
| invalid package | ACCEPTED | {"errors": [], "warnings": []} |
| nonterminal category | ACCEPTED | {"errors": [], "warnings": []} |
| department mismatch | ACCEPTED | {"errors": [], "warnings": []} |
| size mismatch | ACCEPTED | {"errors": [], "warnings": []} |
| missing ebay specifics | ACCEPTED | {"errors": [], "warnings": []} |
| wrong ebay keys | ACCEPTED | {"errors": [], "warnings": [{"field": "ebay_specifics.type", "message": "eBay field 'type' is recommended for search visibility"}, {"field": "ebay_specifics.department", "message": "eBay … |
| invalid season | ACCEPTED | {"errors": [], "warnings": []} |
| invalid Depop source | ACCEPTED | {"errors": [], "warnings": []} |
| invalid Depop age | ACCEPTED | {"errors": [], "warnings": []} |
| invalid Depop style | ACCEPTED | {"errors": [], "warnings": []} |
| four Depop styles | ACCEPTED | {"errors": [], "warnings": [{"field": "depop_specifics.style", "message": "Depop allows only 3 style tags"}]} |
| invalid material | ACCEPTED | {"errors": [], "warnings": []} |
| invalid occasion | ACCEPTED | {"errors": [], "warnings": []} |
| invalid parcel | ACCEPTED | {"errors": [], "warnings": []} |
| regular grouping | ACCEPTED | {"errors": [], "warnings": []} |
| invalid Etsy who | ACCEPTED | {"errors": [], "warnings": []} |
| invalid Etsy what | ACCEPTED | {"errors": [], "warnings": []} |
| invalid Etsy when | ACCEPTED | {"errors": [], "warnings": []} |
| ineligible modern Etsy | ACCEPTED | {"errors": [], "warnings": []} |
| unsupported care | ACCEPTED | {"errors": [], "warnings": []} |
| unsupported composition | ACCEPTED | {"errors": [], "warnings": []} |
| 14 Etsy tags | ACCEPTED | {"errors": [], "warnings": []} |
| 11 Etsy materials | ACCEPTED | {"errors": [], "warnings": []} |
| boolean false | ACCEPTED | {"errors": [], "warnings": []} |
| numeric zero | ACCEPTED | {"errors": [], "warnings": []} |
| unknown nested | ACCEPTED | {"errors": [], "warnings": []} |
| invalid ebay object type | EXCEPTION | AttributeError: 'str' object has no attribute 'get' |
| invalid depop object type | EXCEPTION | AttributeError: 'str' object has no attribute 'get' |
| missing photos | BLOCKED | {"errors": [{"field": "photos", "message": "At least one product photo is required"}], "warnings": []} |
| missing material evidence | ACCEPTED | {"errors": [], "warnings": []} |

## Appendix B — field-level evidence and retained artifacts

[Saved-field evidence appendix](audit-artifacts-2026-09-13/saved-field-evidence.md) enumerates General and every returned field in eBay, Poshmark, Mercari, Depop and Etsy, alongside the complete approved-key inventory. Raw dropdown IDs and unresolved labels remain explicitly unverified. The full sanitized API/form snapshot remains the authoritative detailed artifact.

Screenshots are representative, not a continuous recording. Exact-size screenshots supersede provisional native-window captures. The hidden-field menu screenshot was renamed `hidden-menu-working.png`: it showed a working menu, not clipping. Mercari's early blank brand/carrier capture is retained as a loading observation and superseded by `mercari-settled-after-save.json`.

Audit scripts only exercised disposable database state or collected read-only evidence. `oversized.jpg` is a 21 MB synthetic rejected-upload fixture, not a user photo. Original product photos were not copied into this artifact directory. Logs and JSON have account/address/policy fields redacted; no credentials are required to review them. Artifact hashes are listed in `artifact-manifest.json`.

## Appendix C — remaining acceptance work

The coverage gaps in section 14 remain open. Import, offline retry/cancel/autosave, extension disable/reload, missing-provider first run, provider response failures, restart reconciliation, Diagnose Page and every isolated pipeline stage were added during continuation. This report still must not be represented as execution of every requested live scenario: real logout/relogin, Chrome/process termination mid-job, every live selector/control fault, exhaustive per-field repair, full screen-reader/HAR/video coverage, and a separately eligible Etsy fixture remain incomplete. The next meaningful acceptance run requires correcting the documented workflow defects, then repeating the five-photo save/reopen comparison and all selected marketplace forms. The user's instruction prohibited fixes during this audit, so no implementation work was started.

PARTIAL: A Vendoo draft was created but one or more fields or marketplace forms were incomplete or incorrect; no marketplace listing was published.
