# Changelog

Every change to List This Studio, newest first. Studio bumps its patch version
on each merged pull request, so a version here is one change. The app reads this
file: Settings → General → About → What's new.

Entry format: `## <version> — <YYYY-MM-DD>` followed by bullets.

## 0.1.117 — 2026-09-27

- The **Unsent edits** chip stays until you press Update Vendoo. Opening a listing no longer clears it when the edits never reached Vendoo.

## 0.1.116 — 2026-09-27

- Sold comps now come only from the model you use for listings (Settings → Listing AI). If its web search fails, times out or finds no sales, Brave Search takes over.
- Cursor's sold comps search no longer times out empty. After about a minute Studio stops its searching and asks it for what it has already found, so its listings show up instead of "timed out".

## 0.1.115 — 2026-09-27

- Suggestions stop showing "Fix listing fields" for a listing once it's been fixed through chat, repair, regenerate or a Vendoo sync, not only through the editor.

## 0.1.114 — 2026-09-27

- Settings has a Logs page that shows live API calls between Studio and Vendoo. Tokens and request bodies stay off the page.

## 0.1.113 — 2026-09-27

- Sold comps now come from every model you have connected — ChatGPT, Cursor and MiMo each search the web with their own search, and their results are combined. Brave only runs when they find fewer than three sales or can't search.
- The Regenerate dialog shows comps as they arrive: each source says whether it is still searching, how many sold and live listings it found, or why it failed.
- Sold comps now include a Live listings section — similar items still for sale, with their asking prices. They are there to show what you're competing with and never change the suggested price.

## 0.1.112 — 2026-09-27

- Sold comps no longer count a seller's live listings as sales. A shop's shipping price ("$15 shipping at checkout") and its "items sold" count were being read as a sold price, so items still for sale at $3.99 showed as $15 comps.

## 0.1.111 — 2026-09-27

- Send to Vendoo and Update Vendoo no longer get stuck when the model stops answering while it fills category fields. After two minutes the listing goes to Vendoo with the fields that were filled, and the ones still empty are listed so you can fill them.

## 0.1.110 — 2026-09-27

- Regenerate no longer sits on "Researching sold comps…" before you can pick a price. The suggestion from your price history and past sales shows right away and Confirm works immediately; live sold comps load underneath and update the suggestion when they arrive, unless you've already chosen a price.

## 0.1.109 — 2026-09-27

- Open listing no longer sticks on "Opening…". Studio stopped stacking up Vendoo checks every time you opened a listing or came back to the window, which could leave Open listing and other actions waiting behind them while Chrome was slow.

## 0.1.108 — 2026-09-27

- Sold comps no longer treat a retail price in the title as the sale price. A listing titled "$44" that is actually $18 is not shown as a $44 sale, and a seller's "items sold" count is not treated as that listing having sold.

## 0.1.107 — 2026-09-27

- A listing no longer stays busy after "Listing generated." when Cursor stops answering. Studio gives up after 5 minutes of silence and frees the listing, and Stop now ends a stalled Cursor request right away.

## 0.1.106 — 2026-09-27

- Send no longer says Chrome is busy when nothing else is running. A send that already stopped, or this listing's own send, no longer blocks the next one.

## 0.1.105 — 2026-09-27

- Opening a listing no longer sits on "Loading..." while Studio is busy. The inventory list is about half the size it was and refreshes every 10 seconds instead of every 2 when no Vendoo send is running.

## 0.1.104 — 2026-09-27

- Regenerate finishes instead of sitting on "Clearing chat and generated fields…". A category-index rebuild no longer freezes Studio, and listings already sent to Vendoo clear.

## 0.1.103 — 2026-09-27

- Settings is split into General, Listings, Providers, Connections and Data. Marketplaces, shipping, hidden fields and formulas are under Listings; backups, the data folder and the database are under Data; Brave Search is with the other providers.

## 0.1.102 — 2026-09-27

- Listings open faster. Studio now asks Vendoo about every marketplace's fields at once and stops waiting after 10 seconds, instead of checking one marketplace at a time for up to four minutes each.

## 0.1.101 — 2026-09-27

- Update Vendoo and Relist now move the Vendoo form's "Last Saved" date, the way saving in Vendoo does, so you can see the update landed instead of the form still reading the last save made in Vendoo

## 0.1.100 — 2026-09-27

- Sold comps search the way a buyer would, with brand, printed character, item type, department and size (e.g. "Peanuts Snoopy and Woodstock T-shirt women's XS") instead of the whole photo description, so graphic tees and other detailed items find comps again
- Photo analysis now notes the character, band, team or logo printed on an item, and a comp titled only by that character ("Snoopy Woodstock tee") still counts

## 0.1.99 — 2026-09-27

- Sold comps no longer read foreign prices like HK$1990 or AU $19.90 as US dollars, and $1,250 reads as $1,250 instead of $1

## 0.1.98 — 2026-09-27

- The marketplace links on a listing are now logos, so the line under the title no longer wraps

## 0.1.97 — 2026-09-27

- Each listing now links straight to its live eBay, Poshmark, Mercari and other marketplace pages, next to the Vendoo link. Links show up after the next Vendoo sync.

## 0.1.96 — 2026-09-27

- Analytics profit now takes off marketplace fees and the shipping labels you paid, the same way Vendoo works it out. Re-import from Vendoo to pull in the fees for sales you already have

## 0.1.95 — 2026-09-27

- Generating a listing shows its work in the chat as it happens: each step, the photo analysis thinking, every web search, and the evidence and sold comps cards as they land
- The "Working for" timer moved from above the message box into the chat

## 0.1.94 — 2026-09-27

- Analytics shows what sold, what's still listed, and how long it took

## 0.1.93 — 2026-09-26

- Men's pants and jeans size as the waist (34) instead of 34x34, so the size dropdown fills
- Condition is set to a real Vendoo value, and defaults to Pre-Owned - Good when it was left blank

## 0.1.92 — 2026-09-26

- A jersey-knit women's t-shirt stays under T-shirts on Depop. Sports jerseys still use the Jerseys category.

## 0.1.91 — 2026-09-26

- Mercari Smart Pricing stays off, so a draft no longer asks for a floor price

## 0.1.90 — 2026-09-25

- Cropped jackets map to jackets on Poshmark, Mercari, Depop, and Etsy instead of crop tops

## 0.1.89 — 2026-09-23

- Sending a chat prompt no longer turns the Studio window black

## 0.1.88 — 2026-09-23

- Chat prompts no longer stall while Studio builds the full category index; listing rules load right away

## 0.1.87 — 2026-09-23

- Keep Vendoo marketplace status in a small per-listing cache instead of storing whole draft copies in job history, so sync cannot refill the disk
- Cap how many backup snapshots Studio keeps by size and count, refuse to back up when free disk is less than twice the database, and show a clear warning in Settings
- Settings → About now reports the largest database tables and can prune leftover job events; Studio vacuums on quit so freed space returns to the disk

## 0.1.85 — 2026-09-23

- Sending a prompt on a listing no longer fails with "database is locked" while a Vendoo label sync is running
- A sent prompt now stamps the listing's activity time correctly, so it keeps its place in the sidebar's recent order

## 0.1.84 — 2026-09-23

- Stop caching every Vendoo sync as a new job event (that ballooned the database and crashed Studio); keep one draft per job and prune leftover backup clones more aggressively

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
