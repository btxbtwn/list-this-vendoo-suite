# Audit evidence

Read [FULL_SYSTEM_AUDIT.md](../FULL_SYSTEM_AUDIT.md) first. The verified draft is item `tYhkw1rewBBuMnSmjpzt`; no marketplace publication was observed.

- `approved-studio-snapshot.json`: approval revision before full draft update.
- `final-saved-draft.json` and `saved-field-evidence.md`: independent saved API/form comparison; account fields redacted.
- `final-*-events.json`, `final-*-fill-log.json`: ordered job events and final ledger. Earlier `job-*.json` files are historical observations, not final state.
- `validation-matrix.json`, `isolated-probes.json`, `concurrency-probes.json`: current-code tests in isolated disposable state. Exit 0 means probes executed; it does not mean the product passed them.
- `automated-results.json`, `backend-*.log`, `extension-skill-checks.json`: exact build/test outcomes. Backend suite had 307 passed and 1 failed.
- `*-verified.png`, `mobile-*.png`, `tablet-editor-820x1180.png`: measured viewports. `hidden-menu-working.png` shows a working menu.
- `mercari-after-save.json`: early loading observation, superseded by `mercari-settled-after-save.json`; the settled brand and carrier were correct.
- `global-hidden-*.json`: global hide and restoration; final hidden lists empty.
- `final-marketplaces.json`: all nine selected; five supported by the send pipeline.
- `final-state.json`: zero active automation jobs; primary conversation's stale In Progress status after cancellation.
- `artifact-manifest.json`: sizes and SHA-256 hashes at delivery. `start-main.log` belongs to the running server and can continue growing after that checkpoint.

The `.py` files are audit harnesses, not application fixes. Some report-generation scripts append sections; do not rerun them blindly against the finished report. `oversized.jpg` is synthetic rejected-upload data. Provisional screenshots with ambiguous dimensions were removed; original seller photos and user data were preserved.

Coverage gaps and unexecuted scenarios are explicit in the report. This evidence must not be presented as a successful complete listing acceptance test.
