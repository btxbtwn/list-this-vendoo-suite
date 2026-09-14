# Fix implementation report

Audited commit: `acfd1c24d90f7a803f1167f8ad2f10770a0e6b79` on `main`.
This report is uncommitted working-tree documentation. No pull, commit, push, merge, rebase, reset, stash, or PR was performed.

## Safety

- Automation never published. No List / Publish / Crosslist / Sell controls were clicked.
- Existing audit draft **unchanged:** `tYhkw1rewBBuMnSmjpzt`.
- Repair draft: **`wu1vtewR8b2L8TRJObry`**  
  `https://web.vendoo.co/app/item/wu1vtewR8b2L8TRJObry`
- Studio bound to `127.0.0.1`. Active automation jobs after final checks: **0**.
- Recovery evidence job **`5bc915dbf366`** remains **`cancelled`**.

## Acceptance scope (supported workflow)

The user does **not** create digital listings. **Etsy digital-listing persistence is out of scope** for acceptance and must not keep the implementation verdict PARTIAL.

Supported Etsy policy for this product:

- Block the modern Notations blouse (and equivalent modern mass-produced resale) as **not Etsy eligible**.
- Live Etsy end-to-end is only meaningful for **eligible physical** items: verified vintage, handmade, or craft supply.
- Never invent eligibility (do not fabricate vintage age, handmade status, or craft-supply facts).
- Do **not** modify code to work around Vendoo’s digital-listing behavior.

## Acceptance gaps closed

### 1) Bulk leftover refill — PASS
- Disposable draft only: `wu1vtewR8b2L8TRJObry`.
- Controlled leftover: **Notes** = `AUDIT-BULK-REFILL-2026-09-14`.
- Companion completed job `46f0807b6fc6` used for fill-fields (cancelled job left untouched).
- Live AX reopen shows Notes value; collateral unchanged (5 photos, Mercari Blouse, Depop Preloved/Modern/XL/Parcel Small).
- All marketplaces **NOT LISTED**. No second draft.

### 2) Unsupported marketplaces — PASS
- Facebook / Grailed / Whatnot / Shopify cannot stay selected in Settings.
- `PUT /api/settings/marketplaces` with unsupported IDs → **400** before job creation.
- Job snapshot `platforms` stamps fillable markets only.

### 3) Modern Notations blouse Etsy ineligibility — PASS
- Approved blouse snapshot validates with error: *“This modern mass-produced item is not Etsy eligible…”* when Etsy is selected.
- Focused tests: `test_modern_blouse_is_not_etsy_eligible`, `test_modern_blouse_fails_etsy_without_etsy_specifics` **passed**.
- Eligibility was not invented for the blouse.

### 4) Eligible physical Etsy live end-to-end — BLOCKED (missing test data, not a code defect)
- No independently verified **physical** Etsy-eligible fixture (vintage / handmade / craft supply) with photos and eligibility evidence is available in Studio conversations or audit/fix artifacts.
- Available listings are modern apparel (Notations blouse and similar) or the out-of-scope digital draft.
- Therefore live Etsy fill/save/reopen for an eligible **physical** item was **not executed**.
- This is a **test-data / coverage gap**, not an open product defect for the supported physical-listing workflow.
- To unblock later: supply a real eligible physical item (verified vintage, handmade, or craft supply) with photos; do not invent facts.

### 5) Final terminal verification — PASS
- Audit-only `POST .../retry?resume_from=auditing_depop` on `46f0807b6fc6` → **`completed`**.
- Active automation jobs: **0**. Cancelled `5bc915dbf366` still **cancelled**.
- Independent reopen of repair draft `wu1vtewR8b2L8TRJObry`: **NOT LISTED**.

### 6) Final checks — PASS

| Check | Result |
|---|---|
| Focused Etsy-related pytest | **passed** (incl. modern blouse ineligibility) |
| Full backend `pytest -q` | **361 passed**, 0 failed, 0 skipped (5 warnings), 7.30s |
| `npm ci && npm run build` | Passed |
| `node --check` extension JS | Passed |
| `manifest.json` + dropdown JSON | Valid |
| gitleaks | No leaks |
| Extension source vs managed copy | **files_in_sync**, expected build `af23dd216a950f29…` |

## Independent blocking-review remediation — code PASS

The independent review against `acfd1c24d90f7a803f1167f8ad2f10770a0e6b79` found three High, four Medium, and four Low issues. All material findings and the four Low findings are now repaired in the working tree.

| Review finding | Resolution | Regression evidence |
|---|---|---|
| Dispatch/retry used live Settings marketplaces | Dispatch and registry selectors now use only `job.listing_snapshot.platforms`; schema probes stamp their platforms at creation. | Snapshot `ebay,poshmark` remains `ebay,poshmark` even when the Settings helper is mocked differently. |
| Remote import allowed DNS rebinding | Each URL and redirect resolves once, all addresses must be public, the request connects to a validated IP with the original Host/SNI, proxy environment use is disabled, and connections close between hosts. | Public-to-loopback rebinding stays pinned to the public IP; redirects to loopback fail before a second request. |
| Category resolution mutated the approved job snapshot and could touch a live form | Category resolution writes a listing revision and notes only. Before the live picker opens, the extension waits for the form and requires explicit draft/not-listed evidence for the marketplaces stamped into the approved snapshot. | Async snapshot test plus executable extension test prove the snapshot is unchanged and `SEARCH_CATEGORIES` cannot run before `CHECK_DRAFT_SAFETY` succeeds. |
| Invalid dropdowns were reported as generic failures | Extension, backend, markdown, and Fields UI now carry `invalid`; Ask Chat receives `invalid-dropdown`. | Fill-log persistence and source-contract tests pass. |
| Etsy `Live Listing` passed when nav status was absent | The exception now requires an explicit draft/not-listed nav status. | Dynamic JavaScript test proves live and missing statuses fail closed while `NOT LISTED` passes. |
| Existing live items could be saved before verification | Existing-item jobs, retries/resumes, schema probes, category search, and leftover refills run a draft-safety preflight before photo upload, picker interaction, fill, or save. Empty and missing marketplace status evidence fails closed. | Executable resume-selection, category-search ordering, pipeline-order, and dynamic publication-state tests pass. |
| Reconnect converted leftover refill into `job.start` | Interrupted `filling_fields` jobs become failed with a direct Fields recovery action; patch payloads are recorded before dispatch; generic Retry cannot restart them as a full job. | Repository and route regressions pass. |
| Four Low findings | Approved revision IDs now point at the normalized revision; route IDs `new`, `edit`, and `create` are not reusable drafts; dropdown validation requires exact/base-option matches; the extension rejects any `job.start` whose `publish` flag is not explicitly false. | Focused dispatch, route, validation, and extension-contract tests pass. |

The follow-up blocking review exposed two remaining live-item mutation paths and a duplicate Python test-class name. The resume selector now retains `checking_draft_safety`; category search now runs `WAIT_FOR_FORM` and `CHECK_DRAFT_SAFETY` before `SEARCH_CATEGORIES`; and the second class was renamed so all four previously shadowed tests collect. `pytest --collect-only` now lists both safety classes and all **35** tests in `test_audit_fixes.py`.

Latest objective verification: **361 pytest passed**, frontend build passed with the existing chunk-size warning, **13** extension JavaScript files passed `node --check`, both JSON files parsed, `git diff --check` passed, and gitleaks found no leaks in approximately 41.11 MB.

The Studio-managed extension copy was synchronized to expected build `af23dd216a950f2921ef473bda555844229a8f5055b82208d1b1280cd41fdf37`; `files_in_sync` is true. Everyday Chrome is currently disconnected, so a live handshake/reload of this build is not claimed. No automation job was created, no Vendoo draft was opened for editing, and there are zero queued, awaiting-extension, or dispatched jobs.

### Independent follow-up review — PASS

A separate read-only adversarial review found **no Critical, High, or Medium findings**. It executed the real resume selector, category-search ordering, draft-status checker, and route-ID helpers; confirmed all 35 audit-fix tests collect; and independently reran the full verification suite with **361 pytest passed**. The reviewer created no job, opened no draft, and observed zero active jobs.

Two non-blocking cleanup opportunities remain: the checked-in resume regression test supplies a hand-built step list instead of composing `buildJobSteps` with `selectJobSteps`, and job persistence may temporarily retain route IDs before dispatch/completion sanitizes them. Executable integrated review confirmed neither creates a live mutation path.

## Post-acceptance code review

A final source review found and repaired additional defects before handoff:

- WebSocket origin checks accepted loopback lookalikes, and HTTP CORS allowed remote marketplace origins. Origin checks now require an exact configured local origin; live verification allows `http://127.0.0.1:5173` and rejects Vendoo plus `127.0.0.1.evil.example`.
- Remote image import buffered the full response before enforcing its size limit and permitted cleartext HTTP. Downloads now require HTTPS, validate every redirect, and enforce the limit while streaming.
- Etsy validation did not require `who_made`, `what_is`, and `when_made`. All three are now required for selected Etsy listings.
- Rapid seller-detail saves could arrive out of order, and stale notes could overwrite newer notes. The frontend now serializes saves and sends only seller-detail fields.
- Leftover refill mutated the approved job snapshot, and retry could replace it with the latest revision. Approved snapshots now remain immutable; refill creates a listing revision, and retry uses the original snapshot and stamped marketplaces.
- Refill dispatch left a concurrency window, and extension `fill_fields` could displace another active job. Studio records the refill as active before dispatch, and both Studio and the extension reject overlapping work.
- Publication-state parsing missed common `LIVE`, `ACTIVE`, and `PUBLISHED` labels. Saved-draft audits now recognize those states as publication failures.
- The packaged-update extractor validated ZIP paths only after macOS `ditto` had already written them. Traversal and symlink entries are now rejected before extraction.

The local backend serves the reviewed code on `127.0.0.1:4318`. The repository Studio-managed extension copy is synchronized at build `af23dd216a950f29…`. Everyday Chrome is disconnected, so the current source build has not been verified by a live extension handshake. Active automation jobs remain **0**.

The former mandatory ChatGPT Web review rule was removed at the user's direction. Independent review can now be performed by a separate local agent without ChatGPT Web or CloakBrowser. Local source review and objective verification remain green.

## Code changes retained (supported workflow)

- Unsupported markets stripped/rejected before Send; Settings UI never selects them.
- Validation blocks modern mass-produced Etsy selection; leaves vintage / handmade / craft-supply paths for eligible physical items.
- Extension: clear stale `activeJob` before leftover `fill_fields`.
- **No code changes** were made to work around Vendoo digital Listing Type / Who Made persistence.

## Out of scope — Etsy digital isolation (retained evidence only)

Digital listing persistence is **not** an acceptance requirement. Evidence is retained so the Vendoo limitation is documented without affecting the implementation verdict.

- Disposable digital draft (kept, not deleted): **`JUMA4gTeF2bTd4Z9f5M6`**  
  `https://web.vendoo.co/app/item/JUMA4gTeF2bTd4Z9f5M6`
- Manual everyday-Chrome isolation (extension not used to set values): Save confirmed (**Last Saved / Less than one minute ago**) with Digital Item + I did visible; after navigate-away reopen and hard reload both reverted to Physical Item / Another company or person.
- No digital-file upload control appeared; shipping/processing remained visible.
- Artifacts: `fix-artifacts-2026-09-13/etsy-digital-fixture/manual-isolation-verdict.json` and related reopen/screenshot files.
- Classification: **external Vendoo/account limitation**, out of scope for the user’s supported workflow. No fake-success workaround.

## Finding ledger (delta)

| ID | Status | Counts toward verdict? |
|---|---|---|
| Bulk leftover refill | **Live-proven PASS** | Yes |
| Unsupported markets pre-dispatch | **Fixed + verified PASS** | Yes |
| Modern blouse Etsy gate | **Verified PASS** | Yes |
| Terminal audit-only | **Verified PASS** | Yes |
| Eligible physical Etsy live E2E | **Blocked — missing eligible test data** | No (coverage gap, not code defect) |
| Etsy digital persistence | **Out of scope** (Vendoo limitation evidence retained) | No |

## Conclusion

**PASS**

Verdict is based on the user’s supported **physical-listing** workflow: bulk leftover refill, unsupported-marketplace blocking, modern-blouse Etsy ineligibility, successful terminal audit with nothing published, and verification suite green.

Etsy **digital** persistence is out of scope and does not make this PARTIAL.

Eligible **physical** Etsy live end-to-end remains a **missing test-data** coverage gap (no verified vintage / handmade / craft-supply fixture supplied). That gap is recorded separately and is not treated as an open code defect.
