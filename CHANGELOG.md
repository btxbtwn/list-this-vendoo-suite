# Changelog

Every change to List This Studio, newest first. Studio bumps its patch version
on each merged pull request, so a version here is one change. The app reads this
file: Settings → General → About → What's new.

Entry format: `## <version> — <YYYY-MM-DD>` followed by bullets.

## 0.1.83 — 2026-09-23

- Strip special characters from Etsy tags before Send so Etsy no longer rejects them

## 0.1.82 — 2026-09-23

- Hide the green status-bar dot next to the model logo when everything is fine; show red only when the listing model is not configured

## 0.1.81 — 2026-09-23

- Replies now fade in paragraph by paragraph as they arrive, instead of popping
- Quote the Evidence and Sold comps cards, not just the assistant's reply
- Quotes now sit inline in the message box, right where you drop them, and keep their place in the message you send
- A quote you cite becomes a chip in your sent message: click it to jump back to the source, which pulses so you can find it
- Add a comment to a quote from its chip and send it along with the quote

## 0.1.80 — 2026-09-23

- After Send, Ask chat targets fields that are empty on the Vendoo draft and missing from listing JSON

## 0.1.78 — 2026-09-23

- Quote assistant text in the chat composer with the new Cite button

## 0.1.77 — 2026-09-22

- Fail CI when a version bump ships without a changelog entry

## 0.1.76 — 2026-09-22

- Add this changelog, and read it in the app under Settings → General → About → What's new

## 0.1.75 — 2026-09-22

- Fix missing fields and shipping defaults

## 0.1.74 — 2026-09-21

- Fix Studio 0.1.74 release version

## 0.1.73 — 2026-09-21

- Improve sold comps web research accuracy

## 0.1.72 — 2026-09-21

- Normalize listing colors to Vendoo dropdowns

## 0.1.71 — 2026-09-21

- Fix Mac release publishing and check portable module names

## 0.1.70 — 2026-09-21

- Reject wrong-department category candidates

## 0.1.69 — 2026-09-21

- Keep account policy fields out of Ask chat

## 0.1.68 — 2026-09-21

- Fix stuck-at-0% app update download progress

## 0.1.67 — 2026-09-21

- Infer marketplace chip fields from known dropdown options

## 0.1.66 — 2026-09-21

- Smooth app-update download spinner

## 0.1.65 — 2026-09-21

- Consolidate chat Working for duration status

## 0.1.64 — 2026-09-21

- Show listing AI provider logos in Settings and status bar

## 0.1.63 — 2026-09-21

- Show app update progress; distinguish Vendoo sync

## 0.1.62 — 2026-09-21

- Merge duplicate Ask chat buttons into one

## 0.1.61 — 2026-09-21

- Show Update Vendoo loading progress like first Send

## 0.1.60 — 2026-09-21

- Prefer Vendoo content on sync; keep Studio on status-only

## 0.1.59 — 2026-09-21

- Learn category schemas from synced Vendoo drafts

## 0.1.58 — 2026-09-21

- Fix Mercari No Brand fallback and blank Shipping Label

## 0.1.57 — 2026-09-21

- Reorder sidebar footer controls

## 0.1.56 — 2026-09-21

- Match update download flow to T3 Code

## 0.1.55 — 2026-09-21

- Capture every folder in a multi-folder drop

## 0.1.54 — 2026-09-21

- Add shared details to bulk photo uploads

## 0.1.53 — 2026-09-21

- Show every merged PR in Studio updates

## 0.1.52 — 2026-09-21

- Read photos out of dropped folders via the file-entry API

## 0.1.51 — 2026-09-21

- Create a separate draft for each dropped photo folder

## 0.1.50 — 2026-09-21

- File unisex listings under men

## 0.1.49 — 2026-09-20

- Map every garment family, and men's, onto real marketplace leaves

## 0.1.48 — 2026-09-20

- Bump Studio to 0.1.48

## 0.1.47 — 2026-09-20

- Keep the tops mappers off dresses and other garments

## 0.1.46 — 2026-09-20

- Pick the T-shirts leaf on Etsy, Mercari and Depop

## 0.1.45 — 2026-09-20

- Stop aborting when the window leaves a fullscreen Space

## 0.1.44 — 2026-09-20

- Stop mapping button-up blouses to Etsy Tunics

## 0.1.43 — 2026-09-20

- Infer Depop style tags from listing cues

## 0.1.42 — 2026-09-20

- Fill Etsy primary color when Multicolor is unavailable

## 0.1.41 — 2026-09-20

- Queue chat follow-ups and disable Send while generating

## 0.1.40 — 2026-09-20

- Clear stuck Listing badges after send finishes

## 0.1.39 — 2026-09-20

- Rewrite invalid Poshmark condition code good to ug

## 0.1.38 — 2026-09-20

- Send Poshmark and Mercari the condition codes Vendoo owns

## 0.1.37 — 2026-09-20

- Push the regenerated package onto every marketplace form

## 0.1.36 — 2026-09-20

- Make the Suggestions shelf scrollable

## 0.1.35 — 2026-09-20

- Reset marketplace forms on Update Vendoo after Regenerate

## 0.1.34 — 2026-09-20

- Keep Vendoo label names when Chrome misses list_labels

## 0.1.33 — 2026-09-20

- Clean up the listing inspector panel

## 0.1.31 — 2026-09-20

- Align titlebar listing chrome with the inspector

## 0.1.30 — 2026-09-20

- Widen listing inspector to fit titlebar chrome

## 0.1.29 — 2026-09-20

- Say expanded, not pressed, on the listing actions menu

## 0.1.28 — 2026-09-20

- Move the listing chrome into the window titlebar

## 0.1.27 — 2026-09-20

- Show the Regenerate chooser above the listing inspector

## 0.1.26 — 2026-09-20

- Keep Vendoo inventory labels in sync automatically

## 0.1.25 — 2026-09-20

- Push regenerated listing fields onto each marketplace on Vendoo save

## 0.1.24 — 2026-09-20

- Show stale listing age in days

## 0.1.23 — 2026-09-20

- Suggest listings to generate, fix, or refresh

## 0.1.22 — 2026-09-20

- Add price-drop chooser to Regenerate

## 0.1.21 — 2026-09-20

- Flush Studio chrome like T3 Code and drop duplicate Settings

## 0.1.20 — 2026-09-20

- Keep Studio titlebar clear in macOS Full Screen

## 0.1.19 — 2026-09-20

- One aligned window titlebar like T3 Code

## 0.1.18 — 2026-09-20

- Match T3 Code traffic lights and enable native Full Screen

## 0.1.17 — 2026-09-20

- Avoid GitHub API rate limits on Studio update checks

## 0.1.16 — 2026-09-20

- Keep the seller's own facts through a Regenerate

## 0.1.15 — 2026-09-20

- Badge imported listings without waiting for a cached draft

## 0.1.14 — 2026-09-19

- Report a listing's status instead of letting it be set

## 0.1.13 — 2026-09-19

- Build Vendoo's photo URLs from the image records it stores

## 0.1.12 — 2026-09-19

- Import the whole Vendoo inventory in one run

## 0.1.11 — 2026-09-19

- Send Vendoo label ids, not names, so Item Details labels show on the form

## 0.1.10 — 2026-09-19

- Fold shorts into pants measurements

## 0.1.9 — 2026-09-19

- Send Item Details COG and Notes to Vendoo

## 0.1.8 — 2026-09-19

- Refresh sidebar Vendoo status after a pull, and drop Read draft

## 0.1.7 — 2026-09-19

- Send Depop style tags to Vendoo as option codes

## 0.1.6 — 2026-09-19

- Show official marketplace logos on thread Vendoo status

## 0.1.5 — 2026-09-19

- Prompt to pull when Vendoo is saved

## 0.1.4 — 2026-09-19

- Align error-card fill with Ask chat for N fields

## 0.1.3 — 2026-09-19

- Fix sold comps vanishing when Brave finishes before ChatGPT

## 0.1.2 — 2026-09-19

- Send to Vendoo through the API only, and stop generation form-filling

## 0.1.1 — 2026-09-18

- Bump Studio version on every PR
