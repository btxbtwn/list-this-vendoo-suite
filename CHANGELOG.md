# Changelog

Every change to Anteroom, newest first. Anteroom bumps its patch version
on each merged pull request, so a version here is one change. The app reads this
file: Settings → General → About → What's new.

Entry format: `## <version> — <YYYY-MM-DD>` followed by bullets.

## 0.1.611 — 2026-10-31

- Behind the scenes, Chrome connection and draft-send handling now live together in a service, making future fixes easier to check without changing how listings work.

## 0.1.610 — 2026-10-31

- Try the hosted web workspace and iPhone drafts safely on local sample accounts, with no cloud account or keys. Automatic tests now check the hosted workspace and the packaged Mac app before release.

## 0.1.609 — 2026-10-31

- Pants and jeans no longer get a Size or Size Type on Sellwild, or a Size Type on Vinted, since those forms have no such fields. Listings that already had one are cleaned up, so the "This field is not provided by the selected marketplace form" warning goes away.
- The Sellwild tab no longer shows a "Reload Sellwild choices" link. Your address, discounts and packages still load on their own after you sign in.

## 0.1.608 — 2026-10-31

- The Poshmark and Depop forms on the web can now be edited, including opening their category pickers. Web requests also stay within the database connection limit.

## 0.1.607 — 2026-10-31

- Improve checks that catch data-handling mistakes before an app update.

## 0.1.606 — 2026-10-31

- The eBay, Etsy, Poshmark, Depop and Mercari tabs now show only their own category. They no longer show the category Vendoo saved, which could be out of date after you changed the general category. Drafts you already have keep the category each tab showed.

## 0.1.605 — 2026-10-31

- The project now lives at github.com/btxbtwn/anteroom. Updates, release downloads and help links point there; old links keep working.

## 0.1.604 — 2026-10-31

- Behind the scenes: new automatic checks catch type mistakes, code that nothing uses any more, and code in the wrong layer before a change ships. Nothing changes in the app.

## 0.1.603 — 2026-10-31

- On the web, Edit fields can now change the shared, eBay and Depop categories of several listings at once, picked from Anteroom's category lists, and drafts generated on the web get the same category matching as the Mac app.

## 0.1.602 — 2026-10-31

- A marketplace that said it needs a field, like Vinted asking for a category, stops saying so once you or chat change that field. Press List to check it again.

## 0.1.601 — 2026-10-31

- New sandbox mode for trying changes safely: `./sandbox.sh` runs Anteroom on sample listings with a stand-in AI, never goes online, and refuses to list, delist or update anything on a marketplace.
- Two copies of Anteroom can run side by side: the web port now follows `VENDOO_STUDIO_WEB_PORT` as the API port follows `VENDOO_STUDIO_PORT`.

## 0.1.600 — 2026-10-31

- Changing the general category now sets each marketplace tab's category from that marketplace's own list. When a marketplace has no match, its old category is cleared so you pick one there, instead of it keeping the category from before.

## 0.1.599 — 2026-10-31

- On the web, Regenerate rewrites a listing from its photos and item details again, and you can select several listings and regenerate them together, with an optional price drop first. Clear works on the web too.

## 0.1.598 — 2026-10-31

- On the web, select listings and choose Delete to remove unsent drafts in one go. You review the list first, and anything already sent, still generating, or changed since you reviewed it is left alone.

## 0.1.597 — 2026-10-31

- Etsy's "What is it?" is answered from the Etsy category when it is missing, so List no longer stops on it.
- Etsy List works again when When made is filled on the Etsy tab. It used to say When made was missing.

## 0.1.596 — 2026-10-30

- If an update breaks something, Settings → About → Previous versions lets you go back to an earlier build. When that build used an older database layout, Anteroom restores your backup from that time and keeps a backup of your current data.

## 0.1.595 — 2026-10-31

- Finish saving Etsy drafts with category details instead of stopping before the photos with an incomplete-listing message.

## 0.1.594 — 2026-10-31

- Vinted errors now tell you which field to adjust and why, including titles rejected for too many capital letters.

## 0.1.593 — 2026-10-31

- Show the marketplace photo-limit warning once instead of repeating it around the photos.

## 0.1.592 — 2026-10-30

- The listing agent now sees which marketplace fields are required and rechecks remaining required answers before finishing. It still leaves unsupported facts blank for review.
- Changing another marketplace's price no longer adds optional Etsy answers, including on vintage items. Empty optional Etsy fields no longer block a draft.

## 0.1.591 — 2026-10-30

- Review and save field, tag and label changes across multiple items on the web, with stale-review and queued-work checks before each save.

## 0.1.590 — 2026-10-30

- Importing a Depop listing keeps its price again. Depop stopped including the price on a listing's details, so Anteroom now reads it from your Depop shop list.

## 0.1.589 — 2026-10-30

- Etsy maker and manufacture-date answers now survive chat saves when their field names are normalized.

## 0.1.588 — 2026-10-30

- The listing agent can use photo-supported custom answers when a marketplace field allows text, instead of leaving required fields blank because its suggestions do not fit.

## 0.1.587 — 2026-10-30

- eBay offers now clearly show when offers for all current and future listings are enabled, instead of keeping the blue Enable button. Changing the discount or minimum offers Save offer settings.

## 0.1.586 — 2026-10-30

- See your inventory Suggestions on the web, including items needing review and stale listings to mark down. Items with generation or chat still queued stay out of the feed.

## 0.1.585 — 2026-10-30

- An offer round no longer says "between None% and None% off" when a marketplace's offer limits leave no discount to send on a listing; it says so plainly.

## 0.1.584 — 2026-10-30

- Select multiple items on the web to make separate draft copies or review and save price markdowns, with checks for changed listings and work still in progress.

## 0.1.583 — 2026-10-30

- Change your web app theme and sidebar listing names in General settings, read what changed in each release, and reload the current web version from About.

## 0.1.582 — 2026-10-30

- Open Listings settings on the web to manage templates, labels, shipping defaults and formulas, and review or merge duplicate items in your own inventory.

## 0.1.581 — 2026-10-30

- Keep marketplace choices, package and shipping defaults, listing formulas and hidden-field choices in your web account, with working save and restore controls.

## 0.1.580 — 2026-10-30

- Keep marketplace answers when editing prices, clear old corrections with a draft reset, and make listing generation and required-field checks more reliable. Preserve the packaged libraries needed to analyze photos.

## 0.1.579 — 2026-10-30

- Edit Poshmark and Depop drafts in the web app with the same form fields, category choices and saved values as desktop, without opening Chrome just to load the form.

## 0.1.578 — 2026-10-30

- Attach images to listing chat in the web app. Images stay private, remain with the conversation after reload, and are removed when you delete the draft.

## 0.1.577 — 2026-10-30

- Offer and share rounds now say why a marketplace refused a listing, in its own words, instead of only "Mercari refused the request."

## 0.1.576 — 2026-10-30

- Depop offers now go to a listing with a single eligible liker. Those were skipped with "Depop's send-offer preview changed".

## 0.1.575 — 2026-10-30

- Depop offer rounds now say "Nobody who liked this Depop listing can get an offer right now" for listings without likes, or whose likers cannot get an offer, instead of "HTTP 400" or "Anteroom needs an update".

## 0.1.574 — 2026-10-30

- Show Generate and listing chat in the web editor when the hosted draft worker is running, and recognize your connected AI provider.

## 0.1.573 — 2026-10-30

- Connect your own AI API keys in the web app’s Providers settings, choose models and listing order, and keep credentials encrypted in your account.

## 0.1.572 — 2026-10-30

- Depop offers to likers send again. Depop stopped including the price on its listing details, so every listing was skipped with "Depop's listing price changed"; Anteroom now reads the price from Depop's own offer screen.
- Poshmark offers to likers no longer fail with "Invalid shipping discount" on listings that already have a shipping discount. With no extra discount chosen, the offer keeps the listing's own, as Poshmark's offer form does.

## 0.1.571 — 2026-10-30

- Crop, rotate and adjust your photos in the web editor, preview changes before saving, and reset to the original.

## 0.1.570 — 2026-10-30

- Continue bringing desktop tools into the web workspace, with private account settings, photos, reports, CSV exports and independent draft copies.
- Keep cloud AI keys encrypted and draft work separate for each seller, including work that continues after a browser disconnects.

## 0.1.569 — 2026-10-30

- Depop keeps the size that its own form spells differently, so a 36 waist is shown and sent as 36" instead of leaving the size blank.

## 0.1.568 — 2026-10-30

- Make Retry save recover your unsaved edits when a listing changes in the background, and tell you which field needs review if both copies changed it.

## 0.1.567 — 2026-10-30

- Remove repeated yellow “Check this answer” reminders from optional marketplace fields.

## 0.1.566 — 2026-10-30

- Ask chat about a field or name it in your message: only the fields the agent is editing are temporarily locked, with an “Agent editing” label. Other fields stay editable, and your unrelated corrections are preserved when chat saves.

## 0.1.565 — 2026-10-30

- Let the listing assistant search large marketplace dropdowns on demand when writing or refining a draft.

## 0.1.564 — 2026-10-30

- Keep eBay size, size type, and waist answers when field names are normalized, and stop restarting category filling for those spelling changes.
- Keep listing fields editable while the agent works, so you can make manual corrections without stopping chat.

## 0.1.563 — 2026-10-30

- Vinted and Sellwild stay signed in after you quit Anteroom: the next time a listing needs their categories or account choices, Anteroom reuses your saved sign-in and loads them without asking you to sign in again. Signing out on the marketplace's own page still signs Anteroom out.

## 0.1.562 — 2026-10-30

- Refilling marketplace fields keeps answers already verified from your photos or notes. An empty or broken AI reply no longer wipes existing answers, and unchanged forms no longer create extra saves.

## 0.1.561 — 2026-10-30

- Open cloud inventory reliably after the server wakes from sleep.

## 0.1.560 — 2026-10-30

- Editing a listing no longer repeatedly restarts category filling or clears filled answers just because a marketplace form is waiting to refresh.

## 0.1.559 — 2026-10-30

- Open your cloud inventory in the same Anteroom workspace as the desktop app, with listing fields, private photos, notes, and version history.

## 0.1.558 — 2026-10-30

- Fix Mercari offer checks failing with HTTP 400 on every listing by supplying the required item ID type.

## 0.1.557 — 2026-10-30

- Listing chat can read every enabled marketplace form's current fields and complete choices, including optional fields, categories, brands and dependent options. Repairs save to that marketplace's own fields and explain when a connection is needed to load choices.

## 0.1.556 — 2026-10-30

- Analytics counts a sold item's sale once per unit again. When an item sold on one marketplace and the seller cleared its other listings, each marketplace that then read sold was counted as another sale, so the month's total read higher than the sales made (79 vs 55). Only reports within the item's unit count now count; every real order and Vendoo sale still does.

## 0.1.555 — 2026-10-30

- Check recent Poshmark and Depop likes about every minute while Anteroom is running, so new likers can receive offers sooner. Keep price minimums and pause controls, and check all offer rules and eBay eligibility every 15 minutes. Turn existing Poshmark and Depop offer rules back on after reviewing the faster checks.

## 0.1.554 — 2026-10-30

- Explain which Chrome Bridge to load when using the local and web apps, and how to restore local marketplace actions after testing a standalone web Bridge.

## 0.1.553 — 2026-10-30

- Analytics counts each sale once. A listing marked sold on another marketplace after the item already sold was counted as a second sale, so the month's sold total read higher than the sales you made. Rows already recorded that way stop counting; the sales ledger keeps them. A sale Anteroom verifies from an import now keeps the date it sold instead of the day the check ran.

## 0.1.552 — 2026-10-30

- Preview a cloud draft with Poshmark’s live fields and choices through your connected Chrome browser, using the same form as the Mac app.

## 0.1.551 — 2026-10-29

- Depop styles saved through chat stay selected instead of being replaced by another automatic field fill.


## 0.1.550 — 2026-10-29

- I can remove Depop Age, Source, and Style chips and choose replacements. Cleared selections stay empty across marketplace forms instead of bringing back the old answer.

## 0.1.549 — 2026-10-30

- Analytics counts current inventory by item again. A sold item with more than one sale, or one with stock left and a sale already recorded, was counted more than once, so the sold total in "Current inventory" read higher than the Sold tab in Inventory.

## 0.1.548 — 2026-10-30

- Connect the web app to Anteroom Bridge in desktop Chrome, approve the browser connection, and disconnect it when you sign out.

## 0.1.547 — 2026-10-30

- Set one optional minimum price for Poshmark, Mercari, and Depop offers across current and future listings. Existing offer rules pause for review before sending without individual minimums.

## 0.1.546 — 2026-10-29

- Vinted and Sellwild now recognise when I finish signing in and reload my choices automatically, instead of keeping the sign-in prompt on screen.


## 0.1.545 — 2026-10-30

- Find your online drafts in Inventory, edit their General listing fields, and add private photos that stay with your draft when you reopen it.

## 0.1.544 — 2026-10-30

- Sign in on the web to create, save, and reopen private drafts with a title and notes. Changes made on another device are protected from accidental overwrites.

## 0.1.543 — 2026-10-30

- Opening an item reads its own live listings, so a sale shows while you look at it instead of waiting for that shop's next check. Anteroom detects sales on the marketplaces themselves and no longer counts Vendoo's sale records, so a claim from an import is checked live instead of believed. Every sale Anteroom finds is attached to the item it read, and that listing is then left alone: it cannot be delisted, updated or listed again, and Delist the other marketplaces still skips it. A sale also outranks an earlier failed send, which no longer hides it.

## 0.1.542 — 2026-10-29

- Send eBay offers across all current and future listings with one discount and an optional minimum price.

## 0.1.541 — 2026-10-30

- Protect cloud database setup information and verify its encrypted connection before online sync is enabled.

## 0.1.540 — 2026-10-29

- Open listings and switch marketplace forms faster, keep editing while changes save, and switch inventory filters without loading every thread on screen.

## 0.1.539 — 2026-10-29

- Manage eBay automatic offers from Automations alongside the other marketplaces.

## 0.1.538 — 2026-10-30

- Keep each seller’s photos, listing history, sales links, and automation records tied to their own account as we prepare online sync.

## 0.1.537 — 2026-10-30

- Make stalled-send recovery checks reliable by testing background database work with separate connections, as the app does.

## 0.1.536 — 2026-10-29

- Start loading listing photo thumbnails when you hover, focus, or touch a listing, so they can appear sooner when you open it.

## 0.1.535 — 2026-10-30

- Prepare separate seller accounts so saved categories, copy requests, and marketplace actions do not block another seller using the same identifiers.

## 0.1.534 — 2026-10-29

- Updates install again: downloading one no longer stops with "The update's code signature is damaged or does not match Anteroom's signing identity".

## 0.1.533 — 2026-10-29

- Give Anteroom more time to open while a large database is backed up during startup.

## 0.1.532 — 2026-10-29

- Regeneration keeps your saved choices, including deliberately cleared fields, and preserves marketplace field names while preparing the draft.
- Generation records model-call timing and reported token usage, with cost estimates clearly labelled. Repairs use provider-supported structured responses, and live quality checks save only isolated local drafts.

## 0.1.531 — 2026-10-29

- Prepare Sellwild listings with Chrome closed: sign in inside Anteroom to load your shipping address, discounts, and default package, then reload those choices after signing in.

## 0.1.530 — 2026-10-29

- Listing edits reject stale saves, and direct marketplace actions keep the exact photos you approved even if you change them later.
- Correcting an inventory quantity before a sale removes the mistaken stock count. Reducing a quantity after a partial sale keeps the established stock history safe.
- Marketplace forms follow their supplied row widths and disable editing consistently while saving or generating. Typed answers stay in the editor during refreshes.
- Merging duplicate items creates a new listing revision and preserves the earlier listing history.
- Anteroom rejects requests from untrusted websites, masks secrets in terminal errors, and checks that updates match the installed app's signing identity.
- Database upgrades stop safely if Anteroom cannot save a recovery backup first. Marketplace sign-in tokens expire automatically in the relay, and CI checks Python dependencies and relay failures.
- Vinted category and brand choices can use a private sign-in window in the Anteroom Mac app without opening Chrome.

## 0.1.529 — 2026-10-29

- Added protections that keep hosted seller accounts from reading or changing another seller’s listings and shop history. Access across devices is still being built.

## 0.1.528 — 2026-10-29

- A saved marketplace form stops asking you to reload its fields when nothing about the listing changed. An answer the listing left empty, a setting switched off, and an untouched dropdown were each being read as a change, which held back drafts on eBay, Mercari, Poshmark and Depop.
- An empty answer is reported once. A marketplace's own check and its form no longer both explain the same missing price, description or condition, and a policy taken from your account says so instead of reading as an empty required field.

## 0.1.527 — 2026-10-29

- Listings, chats and page buttons prepare their next screen as you hover, focus or touch them, so opening a saved conversation can show it immediately. Listing search and selection redraw fewer rows, and opening an item no longer reads all its saved revisions.

## 0.1.526 — 2026-10-29

- Marketplace forms stop flagging fields that are already answered. A row the listing filled under another spelling, or that eBay fills from the listing's own brand, size, colour and department, no longer shows an error, so eBay, Poshmark, Mercari and Sellwild drafts that were ready to list stop being held back.
- The start bid, the return policy and fields a marketplace form no longer has are no longer treated as blocking. They are shown as a note instead, like the other details the marketplace fills in when you list.

## 0.1.525 — 2026-10-29

- Listing repairs keep unrelated fields and your saved choices intact. Chat can recall relevant older item details, and generation follows the same canonical rules throughout.
- Generation reports when fields are still incomplete instead of counting an unfinished draft as ready.

## 0.1.524 — 2026-10-29

- Prepared existing drafts, photos, jobs, sales and shop history for seller accounts by recording their owner, while keeping your Mac’s data intact. Signing in and sharing listings across devices are still to come.

## 0.1.523 — 2026-10-29

- Anteroom loads less code at startup, keeps listing search responsive while filtering, and reads inventory cover photos more efficiently.

## 0.1.522 — 2026-10-29

- eBay forms open when the saved condition ID and the condition name mean the same thing, instead of getting stuck asking you to reload their fields.

## 0.1.521 — 2026-10-29

- Listing generation reads every uploaded photo, refreshes its analysis when photos change, and keeps newer seller edits safe while background fields finish.

## 0.1.520 — 2026-10-29

- Opening a marketplace form checks its saved requirements in Anteroom without contacting Chrome or changing the listing’s categories. Live marketplace verification stays with the seller-confirmed List action.

## 0.1.519 — 2026-10-29

- Older drafts open their marketplace forms again. Forms saved before posting compared marketplace brand and condition stored the General answers, so they looked changed even when nothing had changed.

## 0.1.518 — 2026-10-29

- Mercari’s categories, brands, conditions and grouped sizes now load in Anteroom with Chrome closed. Shipping labels and current prices load directly from Mercari after you answer the package questions.

## 0.1.517 — 2026-10-29

- Inventory refreshes use less memory and load faster by reading quantities without loading every saved version of every listing.

## 0.1.516 — 2026-10-29

- Marketplace forms open again for drafts whose category path was saved before posting normalizes it. Saved forms no longer look stale, and their fields are not cleared by that normalization.

## 0.1.515 — 2026-10-29

- Added the first account foundation for using Anteroom across devices: a separate hosted API can verify a seller’s Supabase session. Sign-in screens and access to listings across devices are still to come.

## 0.1.514 — 2026-10-29

- ChatGPT can now generate listings with long rule sets without the “System messages are not allowed” error.

## 0.1.513 — 2026-10-29

- Creating a listing uses the marketplaces’ own forms instead of fetching Vendoo category fields or preparing Vendoo fields in the background. Vendoo preparation runs only when you choose Send.

## 0.1.512 — 2026-10-29

- ChatGPT generation now sends listing rules as developer messages, fixing the “System messages are not allowed” error.

## 0.1.511 — 2026-10-29

- Depop now includes the missing Tops categories, including T-shirts, with their department-specific sizes and fields available while Chrome is closed. Brand choices are available locally, and style, age and source choices use Depop’s own values.

## 0.1.510 — 2026-10-29

- Vinted's Category field now opens Vinted's category picker. It had been showing the shared category path as a text box, so the picker never appeared.

## 0.1.509 — 2026-10-29

- eBay minimum offer and auto-accept edits stay visible after you click out of the field.

## 0.1.508 — 2026-10-29

- Large listing requests no longer exceed ChatGPT’s instructions-string limit. Request errors now distinguish oversized context from sign-in problems.

## 0.1.507 — 2026-10-29

- Marketplace fields stop showing warnings from an older revision, and refreshed dropdown choices appear after category fields refill. Warnings stay with the field they describe.
- Saved Vinted sizes are no longer flagged just because a reference list omits them. The Draft count matches the listings visible in the working list.

## 0.1.506 — 2026-10-29

- Poshmark's categories and size groups load in Anteroom with Chrome closed. Saved shipping-discount choices are retained; unavailable account choices are identified rather than guessed.
- Captured Depop categories, fields and dropdown choices load directly in Anteroom with Chrome closed. Uncaptured categories stay incomplete rather than using guessed fields.

## 0.1.505 — 2026-10-29

- Manage saved labels in Settings → Inventory: add, delete, restore and choose colors. Remove a selected label with its ×, and find older inventory labels in the dropdown beyond the first twelve suggestions. Deleting a suggestion keeps labels assigned to items.

## 0.1.504 — 2026-10-29

- Reopen saved marketplace forms with Chrome closed, keeping their dropdown choices and layout. Changed categories still need fresh choices before listing.
- Vinted's Category field is now a picker: drill through or search Vinted's own category list instead of typing a path.

## 0.1.503 — 2026-10-29

- eBay listings no longer go out with the Condition blank while the form shows one. Wording like “Pre-Owned - Good” was understood by the row on screen but not when the listing was saved, so it sent no condition at all and warned “eBay needs condition, and it is empty” under a field that looked filled. What the form shows is now what is sent, and if eBay's list for that category has no matching grade, the warning says which wording could not be matched instead of claiming the field is empty.

## 0.1.502 — 2026-10-29

- Mercari's category picker now opens the subcategories under Pants and other parent categories, including when searching.

## 0.1.501 — 2026-10-29

- Mercari's Size picker now shows the size the listing will actually send. A tag that reads “S” where Mercari only lists “S (4-6)” left the Size box looking filled with a value Mercari has no id for, so listing refused it while the form seemed answered. The picker now shows Mercari's own “S (4-6)”, and leaving it untouched saves that size. A stale size left from another category still shows as a problem instead of being swapped for a different one.

## 0.1.500 — 2026-10-29

- Show each marketplace error once, with an Ask chat option to fix category and form issues without listing the item.

## 0.1.499 — 2026-10-29

- Listing forms pair shorter fields in two columns so you can review more at once. All sections stay visible, descriptions and photos keep the full row, and narrow editors use one column.

## 0.1.498 — 2026-10-29

- Removed the Unsent chips from listing rows and the filter bar; find pending edits under Filters → Unsent edits.

## 0.1.497 — 2026-10-29

- Search Vinted brands directly in the listing form and choose a matching brand.

## 0.1.496 — 2026-10-29

- Categories are required before listing. The listing agent uses the fields and choices from each loaded native form, checks item answers against photo or seller evidence, and keeps drafts incomplete when forms or required facts are missing.

## 0.1.495 — 2026-10-28

- Marketplace forms show readable warnings without CLI commands, including shipping, photo and listing requirements across every marketplace.

## 0.1.494 — 2026-10-28

- Depop listings that showed shipping filled in still failed to publish with “national shipping”. Two causes, both fixed. When Depop's parcel list named no price, the draft was saved without a national shipping cost, so Depop counted that as unanswered even though the package size was there; it now writes a cost every time, and free shipping is written as 0.00 rather than dropped as if it were blank. And a draft saved before that fix kept telling Depop it was missing shipping long after the form showed it; publishing now writes the draft once more and lets Depop recount before declining, instead of refusing an item whose shipping you already chose.
- Depop's photo warning now sits in its own Photos area, above the pictures, instead of under the description. List's line beside the button no longer repeats it, and the CLI command it carried is gone from both: it was a note to a terminal, not something to read on a phone. The same holds for any other field a marketplace's form shows: an answer about it is read under that field, and only the rest stay beside List.

## 0.1.493 — 2026-10-28

- Repricing an item used to leave its Best Offer prices behind, so the form held an auto-accept price above the offer minimum and eBay refused the listing with “This Offer is not available”. Auto-accept and Minimum now follow the new price, on eBay and in Poshmark's Smart Sell floor, and they clear once an item is too cheap to carry them. A Best Offer price you typed yourself is kept as it is, and an item you turned Best Offer off for stays off.
- A price is now always whole dollars, which is what the offer prices are worked out from.

## 0.1.492 — 2026-10-28

- List everywhere now leaves a marketplace out when its form still needs an answer. Mercari's shoebox question, shipping label, package weight, and ship-from ZIP are checked before it is offered, so Anteroom no longer starts a Mercari listing that its own form would refuse.
- Two copies of the Chrome extension used to take turns on the connection, closing each other every half second. That is what made a marketplace form fail to load with “Chrome could not read the marketplace form” and a listing check end as “Check did not finish.” Anteroom now keeps the copy that is running its own extension and tells the extra one to stand down, Settings → Connections says when more than one copy is loaded, and a form read that loses its reply is asked for once more before it fails. A connected extension also no longer reloads itself over and over after an Anteroom update, and the error names the Chrome call that failed.

## 0.1.491 — 2026-10-27

- Marking an item as listed now puts it back on the marketplace list even when Anteroom had already given up on the publish. Before, if a Depop publish took too long to confirm, Anteroom set the item back to a draft, and telling it you had listed it yourself afterwards left that draft in place, so the marketplace never showed the item as listed anywhere.

## 0.1.490 — 2026-10-27

- Sign in with ChatGPT now uses OpenAI's official sign-in for apps. Sign in once more in Settings → Providers: approve Anteroom in your browser and leave token sharing on, and listings keep running on your ChatGPT plan. Plan usage now shows in ChatGPT → Settings → Usage instead of in Anteroom.
- Chrome reconnected every half second while one listing was being checked, so the app sat loading and the check ended with “Check did not finish”. A reconnect used to repeat the whole start-up handshake each time — re-queueing interrupted sends and asking Chrome to check listings again — while the extension reset its retry delay on every attempt. Now only a Chrome that stays connected sets things going, a connection that keeps dropping waits longer each time, and a socket that closes early is written to the log instead of vanishing.

## 0.1.489 — 2026-10-27

Anteroom's backend can now run on Postgres as well as SQLite. Every query, JSON read, upsert and schema migration goes through one layer that speaks both, so the hosted API can share one database while this Mac keeps using its own file. Nothing about listing changes, and an existing SQLite database opens exactly as before.

## 0.1.488 — 2026-10-28

- On a marketplace tab, what List would still tell you about a field now appears under that field, as soon as the listing has a value there. Poshmark's color answer (“Poshmark does not list Navy, so that color is left off”) shows under Color, its title and description limits under those boxes, and its price answer under Price. The same notes stay beside List, which is what holds List.
- **Edit** beside one of those notes now opens that marketplace's form at the field the note names — Poshmark's color answer opens Poshmark's Color, its size answer opens its Size — instead of the General form. A refused Mercari List names its own fields (sizeId, categoryId, name), and those open Mercari's Size, Category and Title.
- Generating a listing now knows which colors Poshmark lists, so it writes the closest one instead of a shade Poshmark silently leaves off.

## 0.1.487 — 2026-10-28

- Vinted listing failed with “Reconnect Vinted in Anteroom first” even while you were signed in. Anteroom looked for Vinted’s security token in a form the page no longer uses, so every Vinted action stopped before it asked Vinted anything. It also never renewed the one-hour pass Vinted hands out, even though Chrome keeps your sign-in for a week. **List**, **Update**, **Delist**, Import and sale checks on Vinted now read the token, renew the hour in the background, and ask Vinted for English names so your saved category, condition, size, colour, brand and package size match. **Reconnect Vinted** now says whether it found your sign-in, and who as, instead of leaving the old message in place.

## 0.1.486 — 2026-10-27

- A listing that comes back empty now asks the model again with reasoning turned off. DeepSeek sometimes spent its whole reply thinking and stopped before writing anything, so chat said “Listing generation returned no text” and the draft stayed blank. The retry writes the listing, and if the model still answers with nothing the message says how much it thought and why it stopped instead of repeating that generic line.

## 0.1.484 — 2026-10-28

- The category picker now shows the whole path in the field instead of cutting it off at “Wo…”, and its panel stays on screen and scrolls rather than being clipped by the form. The panel shows where you are as a breadcrumb you can click, searches every category by any part of its path, and marks the saved category so you can see its siblings.

## 0.1.483 — 2026-10-27

- A Depop draft now carries the package size it needs to be posted. Anteroom quoted Depop's shipping when it published but not when it saved the draft, so a draft could be saved without the one field Depop requires, and List left you with a draft Depop never published. Saving and publishing now use the same quote, and a draft that comes back without it is named instead of saved.
- A Depop publish job Depop ends without posting now says so, in Depop's own words, and leaves the row on Draft so you can List again. A job Depop has accepted but not started yet is waited for instead of being called a failure, so a queued listing no longer turns into Unconfirmed.
- Depop takes a SKU once. A new draft whose SKU another listing already holds is saved again without it and says so; a draft that already stores that SKU asks you to clear it on Depop. Pasting your own Depop link works too: the address bar shows it ending in `/manage`, and Anteroom now accepts that and keeps the public address.

## 0.1.482 — 2026-10-28

- Items no longer show a marketplace as "Sold here" when nothing sold there. Vendoo records a sale date of 1970 for a marketplace listing that never sold, and Anteroom was reading it as a real sale: that marketplace could not be delisted, the item could not be listed again, and its relist warning never appeared. Those dates are now ignored, and a real sale date still counts the same as before.

## 0.1.481 — 2026-10-28

- The Mercari Shipping fields now offer to remember themselves: a bookmark beside **Ships from** and **Shipping label** saves that ZIP or carrier as the default for every new listing, and pressing the filled bookmark stops using it.

## 0.1.480 — 2026-10-28

- Hovering a listing no longer opens a marketplace status popover. The logos under each listing already show where it is live.

## 0.1.479 — 2026-10-28

- A live listing with edits you haven’t sent stays under Active and wears an **unsent** tag instead of appearing under Draft. **Filters → Unsent edits** still collects them, with a count beside Filters for the tab you’re viewing, and the Filters badge no longer counts the selected tab.

## 0.1.478 — 2026-10-28

- Category fields now read as one path, with an arrow between each level: Women → Jeans, or Women → Global & Traditional Wear → Kilts.
- Choosing a category opens the same department-and-group picker on every marketplace form, one level at a time, instead of a long dropdown. The saved category stays visible if the marketplace no longer offers it, so you can replace it rather than lose it.
- Poshmark’s Category and Subcategory keep their own control, with an arrow between them so the next choice reads as a step.

## 0.1.477 — 2026-10-28

- Listing forms are easier to read: fields stop at a comfortable width instead of stretching across a wide window, section headings stand out from field labels, labels and marketplace statuses are larger, and the description box has more room between lines.
- Fields that take several choices say how many they allow in the empty box ("Choose up to 3"), and the count appears once you pick something.
- The inventory list shows three suggestions with "Show all" for the rest, the search box reads "Search listings" instead of cutting off, the status tabs no longer cut off "Active", and the marketplace logos under each listing are larger.

## 0.1.476 — 2026-10-28

- The Depop tab now follows Depop’s sell page: the description placeholder, the 1,000-character counter and the hashtag counter, US$ on the price, your shipping address, and suggested package sizes. List sends the same package size Depop’s page would. Worldwide shipping’s price appears, with US$, only when you turn that offer on.
- The Sellwild tab shows the fee and what you earn, your discounts with none picked until you choose one, and packages grouped the way Sellwild groups them. A vehicle still shows Vehicle Shipping and no package. A discount you pick is applied after the listing is live.

## 0.1.475 — 2026-10-28

- OpenRouter now has its own mark and keeps the model names OpenRouter gives them, in Settings and the model picker.
- OpenRouter has a Reasoning setting with the levels the listing model supports. Default leaves the choice to OpenRouter.

## 0.1.474 — 2026-10-27

- The Poshmark tab now matches the rest of Poshmark’s create-listing page. Quantity is Single Item or Multi Item, separate from Size. Category and Subcategory sit side by side: the category starts with Women, Men, Kids, Home, Pets, or Electronics, and a chosen category reads like “Women Jeans.” Sizes can be US, AU, EU, or UK. Availability includes Drops, with a drop time within 7 days. Listing Price shows the Smart Sell badge, Discounted Shipping, and Your Earnings.

## 0.1.473 — 2026-10-28

- The eBay tab follows eBay's Create listing page. Item specifics stay in eBay's order, with Show more for the rest. You get a subtitle and custom label under title options, a second category, scheduling, this listing's own policies and item location, charity, and one custom item specific. An auction shows its duration and bids instead of an item price.

## 0.1.472 — 2026-10-27

- On the Mercari tab, package weight is one question, "How heavy will the package be?", with pounds and ounces side by side. Length, width and height stay hidden until you say the item will not fit in a shoebox, and you can skip them. Once the item has a price, Smart pricing shows as on, with a suggested lowest price.

## 0.1.471 — 2026-10-28

- Each flaw in a description is on its own line, so a list of flaws is easy to scan. A description formula you wrote yourself stays as you wrote it.

## 0.1.470 — 2026-10-28

- Depop, Mercari, Poshmark, Sellwild, and eBay now show this item's photos where that marketplace's own page does. You can reorder them and pick which ones that marketplace gets, up to its limit. Depop stays JPEG and PNG.

## 0.1.469 — 2026-10-28

- Category on the marketplace tabs starts with its own dropdown for the department (Men, Women, Kids and so on), then the group, then the item, one step at a time as on Depop, Poshmark and Mercari.

## 0.1.468 — 2026-10-28

- Depop offer previews recognize the currency in Depop's current listing data, so a US dollar listing is no longer skipped because its currency could not be read.

## 0.1.467 — 2026-10-28

- The Poshmark tab now matches Poshmark’s create-listing page for every category: the same headings and hints, categories in Poshmark’s order (with Global & Traditional Wear as its own group), the same size tabs and sizes, one Color field for up to two colors, and the price panel’s Listing Price, Automate Offers, Lowest Price, Original Price and Shipping Discount. Listing SKU, Cost Price and Other Info sit under Additional Details, and Cost Price can be changed here.

## 0.1.466 — 2026-10-28

- The Sellwild tab now shows your Shipping From address at the top of Item Shipping (and under Vehicle Shipping for vehicles), the same address Sellwild’s page shows and List uses. Change it in Sellwild’s Address Book. Package weight and size sit side by side in one row, as on Sellwild, and Depop’s Size and Quantity are narrow side by side, as on Depop.

## 0.1.465 — 2026-10-28

- With Prepaid label, the Mercari tab now asks what Mercari’s label picker asks: the package weight in pounds and ounces, whether it fits in a shoebox, and its length, width and height when it doesn’t. They start from Item Details, the labels offered follow them, and List sends what you set there.

## 0.1.464 — 2026-10-28

- When you pick a different category for a marketplace, on its tab or by asking chat, Anteroom fills that category’s new fields the same way it does after generating, choosing only from that marketplace’s own choices. Only the marketplace you changed is filled, and fields you set or locked are left alone.

## 0.1.463 — 2026-10-28

- The Depop tab has Depop’s “Boost your listing” switch, off unless you turn it on (Depop charges an extra 12% fee when a boosted item sells). Update sends it to the live listing. Depop drafts can’t hold Boost, so List posts the item and then turns Boost on with one update of that new listing.

## 0.1.462 — 2026-10-28

- A List everywhere button at the bottom of the marketplace list lists the item on every marketplace that's ready, after one confirmation that names them. Marketplaces still missing details are left out and named so you can finish them.

## 0.1.461 — 2026-10-28

- The listing form now takes the whole window, so fields are easier to read. The chat is a pop-up in the bottom-right corner: minimize it to a small button that still shows what it's working on and marks new replies, and press ⌘J to open or close it. It opens by itself when you ask about a field or start a new listing.

## 0.1.460 — 2026-10-27

- On multi-choice fields the hint and the number chosen share one line under the field (for example 1/4), and Clear is an × inside the field instead of a link underneath.
- A scheduled price drop counts its waiting period from the time the task ran, so the next step down comes when it should.

## 0.1.459 — 2026-10-27

- Mercari’s Size list is grouped under Mercari’s own headings (Standard, Petite, Inch and so on), as on Mercari.
- On the Sellwild tab you can type the package weight and box size, as on Sellwild’s page. They start from Item Details, and List sends what you set there.

## 0.1.458 — 2026-10-27

- The Mercari tab now matches Mercari’s own sell page: the same sections (Product info, Shipping, Pricing, Smart pricing), fields and wording in the same order, every category Mercari offers in its order — including a category’s “All …” choice — and sizes under Mercari’s size groups. Brand has “No brand / Not sure” as a choice, and you can set the ZIP an item ships from. Size type, the separate No brand switch and the package weight rows are gone from this tab.

## 0.1.457 — 2026-10-27

- The Sellwild tab now matches Sellwild’s own sell page: the same sections (Add a Title, Name Your Price, Add Details, Item Shipping), its field names, its category list in the same order, and its packages, with weight and box sides shown only for the packages that ask for them. Vehicles show Vehicle Information instead of packaging. Pets > Adoption, which Sellwild does not offer, is gone, and an Irregular Parcel now asks for the packed weight like it does on Sellwild.

## 0.1.456 — 2026-10-27

- After generating a listing, Anteroom now fills each marketplace’s category fields it can tell from the photos and details, such as Depop’s Type and Fit for jeans or eBay’s Rise, choosing only from that marketplace’s own choices. Fields you set or locked are left alone, anything it can’t tell stays empty, and chat lists what it filled.

## 0.1.455 — 2026-10-27

- The Depop tab is laid out like Depop’s sell page: the same headings (Description, Info, Enhance your listing, Item price, Shipping), Size and Quantity side by side, and Depop’s own hint under each field.

## 0.1.454 — 2026-10-27

- The Depop tab now matches Depop’s own sell page for every category: the same fields in the same order, with Depop’s names and choices. Retired categories and fields such as the empty “Sizing” row are gone, Color is one field that takes up to two colors, and the hashtags Anteroom adds show under Description instead of in a separate field.

## 0.1.453 — 2026-10-27

- The Sync button and the green Ready badge are gone from the listing toolbar. Nothing needs checking by hand: List and Delist report their own results, and a sale still delists the item everywhere else. When an eBay or Etsy sale is for an item with more than one in stock, Anteroom now reads what's left right away, so it knows whether to delist the rest. A List or Update that stalls is checked as soon as Anteroom gives up on it.

## 0.1.452 — 2026-10-27

- A listing's actions are easier to find. Regenerate, Record a sale and Delist everywhere sit together at the bottom of the marketplace list, with sync status and the More menu below them. History is at the end of the form, and the empty bar above the form is gone.
- Marketplaces say Listed instead of Live. Each marketplace's bar shows its name with View listing beside it, and Update only appears once you've changed the listing since it was last sent there.

## 0.1.451 — 2026-10-27

- eBay, Poshmark, Mercari, Depop and Sellwild tabs now show exactly the fields that marketplace’s own form has, in its order. Anteroom no longer adds its own Size, Size Grouping, price or offer rows to them, so pants and jeans no longer show Size twice on Depop, and Price sits where the marketplace puts it.

## 0.1.450 — 2026-10-27

- Changing a field on a marketplace form keeps you where you are. Saving no longer jumps back to a field you opened with an Edit button, and the box above the form no longer shrinks and grows back on each save, so the form stops moving under you.
- Edit buttons for a missing category now open that marketplace's own form at its category, instead of General.

## 0.1.449 — 2026-10-27

- The listing assistant no longer writes "Does Not Apply". A field that doesn't fit the item is left empty, and Anteroom remembers you don't need to fill it.

## 0.1.448 — 2026-10-27

- List, update and save drafts on several marketplaces at the same time instead of one after another. Bulk List and Update now work on up to three items at once. Two items on the same marketplace still take turns, and Delist still waits for listings to finish.

## 0.1.447 — 2026-10-27

- Clicking a listing no longer opens a tab. Anteroom shows one listing at a time, and the listing's name appears in the title bar. Use the **+** beside the listings search to start a new listing.

## 0.1.446 — 2026-10-27

- Marketplace forms are cleaner: the “This category’s fields are showing” line, the notes about where each marketplace’s choices come from, and the Refresh choices and Show all fields buttons are gone. A line only appears while a form loads or when it could not be loaded.

## 0.1.445 — 2026-10-27

- Depop offers now use its bulk send to eligible likers, for offers you approve and rules you turn on. Anteroom waits for Depop to finish, respects your floor and Depop's price limit, and stops without resending if the result is unclear. Rules stay off until you enable them. The earlier recording sent to only one buyer; this uses Depop's separate bulk flow.

## 0.1.444 — 2026-10-27

- Regenerate and the three-dot menu now sit beside History, Sync, and Ready in a single, tidier listing header.
- Listing forms and the left sidebar open wider by default, with a narrower chat panel. You can still drag the dividers to suit your screen.

## 0.1.443 — 2026-10-27

- Removed the “Unsent edits” tag from the listing header and the “unsent” tag from sidebar listings.

## 0.1.442 — 2026-10-27

- Nothing changes in the app. A check that Anteroom runs on every change, that a stuck send fails and the next one in line still goes out, no longer fails at random.

## 0.1.441 — 2026-10-27

- Listing forms stay on screen while you edit. Changing a price, brand, condition, format, or shipping choice no longer reloads the form. Choosing a category, or an update that sets the category, is what changes it. The form shows the fields every listing on that marketplace has, plus the fields that category needs, such as size and attributes. Turning on Depop worldwide shipping shows its fee without a reload, and switching eBay's format or Mercari's shipping method shows or hides those rows in place.
- Category on a listing form is a grouped dropdown. Pick a group, then keep picking until the last category in that branch.
- The listing assistant can choose a category too. It picks the last category in that branch, the same way the category list does, and the form updates to the fields that category needs.
- Each marketplace form has its own category list. The category on General fills the matching last category on those forms, and they then show the fields that category needs.

## 0.1.440 — 2026-10-27

- Offers to likers now work on Mercari, sent by you or by a rule you turn on. Anteroom asks Mercari whether the listing can take an offer and what range it allows, sends whole-dollar offers inside that range and never below your floor, sends each one once, and pauses the rule if Mercari's answer is lost, it limits requests, or you are signed out.

## 0.1.439 — 2026-10-27

- When Anteroom watches you send an offer by hand on Mercari or Depop, it now keeps only that site's own requests and skips its analytics, so a long session no longer fills up before the offer is sent.

## 0.1.438 — 2026-10-27

- General fills every marketplace form. A title, description, brand, size, or department you change on one marketplace stays on that marketplace, and eBay's Size and Department can be edited on the eBay form.

## 0.1.437 — 2026-10-27

- When Anteroom watches you send an offer or save a draft by hand to learn a marketplace's requests, it now keeps what it saw even if the request that started it is interrupted. Only one of these recordings runs at a time.

## 0.1.436 — 2026-10-27

- Settings → Listings → **Send to Vendoo** can be turned off. While it is off, Anteroom does not call Vendoo: nothing is sent, imported, opened in the draft browser, or synced. You list on each marketplace directly, and nothing publishes until you confirm it.
- Vendoo-only controls hide while it is off: linking a draft, opening a listing in Vendoo, discard, relist, duplicate Vendoo links, Vendoo label IDs, sync from Vendoo, Vendoo API logs, and the send-to-Vendoo setup. Labels, photos, chat, listing forms, history, and marketplace accounts stay. Turn the switch back on when you want Vendoo again.

## 0.1.435 — 2026-10-27

- Photos in a listing, pictures in chat, and covers in the sidebar are shown small, so Anteroom uses far less memory and the Mac spends less time catching up.
- A listing you are not looking at stops checking for updates until you come back to it.

## 0.1.434 — 2026-10-27

- Anteroom can now watch while you send one offer to likers by hand on Mercari or Depop, so it can learn how each site sends offers. It keeps only the shape of the requests, never prices, items or your account details. This is the step that lets Mercari and Depop offer rules turn on.

## 0.1.433 — 2026-10-26

- Labels are yours now, not Vendoo's. Items imported from Vendoo sometimes showed a code like `g8MHWF7K…` instead of the label's name. Settings → Listings → Inventory → **Vendoo label IDs** → **Convert to names** saves every label as its name, and each Vendoo import does the same for the items it brings in. A code Vendoo has no name for stays on the item and is listed there, so no label is lost.
- Analytics shows sales by label, with your label colors.
- Find items listed twice: Settings → Listings → **Similar items** lists pairs that share a photo or SKU, or have matching titles with the same brand and size. Open both to compare, keep one and merge the other into it (its marketplace links, sales and labels move over and it goes to Finished), or mark them as different. Nothing is deleted or delisted.

## 0.1.432 — 2026-10-27

- **Update…** now works on live Mercari, Vinted and Sellwild listings, both on an item and in the bulk **Update** action. Anteroom edits the listing that is already up instead of making you delist and relist, so it keeps its likes, views, listing age and photos. It changes only what you edited, never lists a draft or creates a second listing, and reads the listing back afterwards to make sure the change stuck. Sellwild may hold an edited listing for review.

## 0.1.431 — 2026-10-27

- Every marketplace form now shows its photos at the top: the photos that marketplace gets, in order, and how many it takes. Untick a photo, drag to reorder, or add photos for that marketplace only (a stock photo for eBay, a collage for Depop); **Reset to item photos** goes back. List, Save Draft and Update send that form's photos. Items you have not changed still send all their photos.
- Video is no longer a separate button at the bottom of the form. On eBay, Etsy and Poshmark, add a video in the same photos, by dropping or choosing the file the same way as a photo; each form says what that marketplace accepts. Depop, Mercari, Vinted and Sellwild take no video from their websites, so their forms offer none.

## 0.1.430 — 2026-10-26

- Automations has a new **Sharing and offers to likers** section. Set up a Poshmark sharing schedule: which listings, the order, how fast, the times of day and a daily cap of up to 6,000 shares. Every share and every skipped listing shows in the activity log.
- Make an offer rule for Poshmark likers: the discount, which listings it covers, a floor you set for each listing, listings to leave out, and how long or how many likes a listing needs first. Each round only offers to people who liked a listing since the last offer, and never below your floor.
- Nothing runs until you turn a schedule or rule on, and **Pause all** stops them. If Poshmark starts limiting you, or Anteroom cannot tell whether an offer or share went through, the rule pauses and that listing waits for you to check it; Anteroom never sends it again on its own.
- Mercari and Depop offer rules can be set up, but stay off until Anteroom has learned how those sites send offers.

## 0.1.429 — 2026-10-27

- Your Facebook Marketplace listings now show under Marketplaces, including the ones Vendoo listed there. Press **Check on Facebook** to see whether one is still live, pending or sold; Anteroom only looks, and nothing on Facebook changes.
- Turn on **Detect sales** for Facebook in Settings → Connections to have Anteroom notice when a Facebook listing is marked sold. It is off until you turn it on, and it reads a few listings at a time every 20 to 40 minutes, because Facebook watches closely for automated visits.
- Anteroom can't delete Facebook listings yet. Delete them on Facebook, then choose **Mark as not listed**. Delisting the other marketplaces after a sale leaves Facebook for you and says so.

## 0.1.428 — 2026-10-27

- Multiple-choice fields, such as Occasion, Theme, Season, and Features, show the selected values inside the field. Extra values wrap onto another line in that same field.

## 0.1.427 — 2026-10-26

- Share Poshmark listings to your followers, one or many at a time: select items in the sidebar and choose **Share / offers**. You review each item and confirm once; shares go out a few seconds apart and stop at the first limit Poshmark reports.
- Send a Poshmark offer to everyone who liked a listing. Set the lowest price you accept for each listing first: an offer below it is never sent, and Poshmark's own minimum discount is shown in the review. Choose a shipping discount, or none, for each offer.
- If Anteroom or Chrome stops before a share or offer is confirmed, it shows as needing a check and is never sent again on its own. Mercari, Depop, Etsy, Vinted and Sellwild tools are not added yet; what each marketplace offers is listed in the parity notes.

## 0.1.426 — 2026-10-26

- Edit fields for selected items now also changes condition, primary and secondary color, tags, and the shared, eBay and Depop categories. Categories are picked from the same searches the item editor uses, and you review every change before it is saved.
- **Marketplaces** for selected items gains **Update**: it writes each item's saved listing onto the listings already live on the eBay, Etsy, Poshmark and Depop you tick. You review and confirm first; items run one at a time, each marketplace once, and a failed update leaves the live listing as it was. Nothing is listed or taken down.
- **Mark as not listed** works on many items at once. Only Anteroom's record changes; the marketplace is not contacted.
- Delete selected items from Anteroom after reviewing them. Nothing is delisted, and an item still live on a marketplace is left out until you delist it or mark it not listed.
- Choose when a listing counts as stale (15 to 120 days) and give labels colors, under Settings → Listings → Inventory.

## 0.1.425 — 2026-10-26

- Updating a live Depop listing no longer fails with “Depop did not keep the updated price” when Depop's reply simply leaves the price out. After saving, Anteroom reads the listing again the way Depop's edit page does, waits a few seconds if Depop is slow to show the change, and only then reports which of the price, category or size Depop did not keep.

## 0.1.424 — 2026-10-26

- A sale Anteroom detects now turns the item Sold in Inventory and counts in Analytics, without waiting for Vendoo. An item with more than one unit stays Active and shows how many have sold, such as "1 of 3 sold". A sale Vendoo already recorded is counted once.
- Mark as sold now asks where it sold, when, and for how much, including shipping and fees, and saves it under Sales records. For a sale in person or anywhere else, choose **Other / in person**, or use **Record a sale** in the Marketplaces panel. Afterwards Anteroom offers to delist the item from your other marketplaces; nothing is delisted unless you confirm.

## 0.1.423 — 2026-10-26

- You can now import your active Poshmark, Mercari, Depop, Sellwild and Vinted listings into Anteroom from each marketplace's page, using your sign-in in Chrome. Anteroom shows what it found first, opens items you already have instead of copying them, and asks before linking a listing to an item that looks the same. Importing only reads the marketplace; nothing there is changed, published or delisted.

## 0.1.422 — 2026-10-26

- Add a listing video on eBay and Etsy, the same way as on Poshmark: upload it on that marketplace's form, then Save Draft or List. eBay takes one MP4 or MOV up to 150 MB and List waits until eBay has processed it; Etsy takes one video of 3 to 15 seconds. Anteroom checks that the marketplace kept the video, never uploads the same file twice, and will not list with a video the marketplace blocked or could not process. Clear video removes it.
- Depop, Mercari, Vinted and Sellwild don't accept listing videos from their websites, so their forms have no video picker.

## 0.1.421 — 2026-10-26

- Photos can now be edited in the listing editor: open a photo and press **Edit**. Crop to a square or another marketplace shape, rotate and straighten, adjust exposure, brightness and contrast, or remove the background and put white or any colour behind the item. Background removal runs on your Mac; the photo is not uploaded anywhere. Your original photo is always kept, and **Reset to original** brings it back. Marketplaces, Vendoo sends and Etsy drafts get the edited photo, and editing a photo means a pending automation approval or reviewed Vendoo send has to be reviewed again.

## 0.1.420 — 2026-10-26

- List one eBay item in several sizes or colors. Under Marketplaces → eBay, choose what the variations differ by (eBay offers the choices it allows for the category), then give each variation its own quantity, and optionally its own SKU, price and photos. Save draft keeps it private on eBay and checks what eBay saved; List publishes it as one listing. eBay sells variations at a fixed price without offers.
- Update changes the quantities, prices and photos of a live listing with variations, and Delist ends the whole listing. Selling one size no longer counts the item as sold out: Sync reads what is left of each variation.

## 0.1.419 — 2026-10-26

- Anteroom now refuses an update whose signature is missing or damaged, so an update can no longer lose access to your saved sign-ins. Releases are ready to be signed with an Apple Developer ID certificate; once that is set up, updates stop asking for your Mac password.

## 0.1.418 — 2026-10-26

- Depop drafts now keep everything Anteroom sends: category, size, condition, brand, photos, location and shipping. Anteroom no longer sends a blank SKU, which made Depop quietly keep only the description and price, and it waits until Depop has finished processing new photos before adding them.
- Changing a listing's Depop category now moves it everywhere Anteroom stores it, so the next update to the live listing uses the new category and its own sizes instead of the old ones. A size picked for the old category is cleared.
- Updating a live Depop listing sends the same fields Depop's own edit page sends. If Depop refuses, the item's error shows Depop's reply and which fields were sent, with addresses and sign-in details hidden.

## 0.1.417 — 2026-10-26

- Saving an eBay draft no longer stops after eBay saves the offer with “eBay did not confirm the listing”. Check finds an auction draft whose reply was lost, and saving again reuses it.

## 0.1.416 — 2026-10-26

- Items you listed directly on a marketplace no longer show **Unsent edits** just because Vendoo still has an older copy. The chip now means the live marketplace listings are behind: press **Update** under Marketplaces to clear it. Discard is hidden on those items, so it can no longer roll a regenerated listing back to Vendoo's version.

## 0.1.415 — 2026-10-26

- eBay listings are now made only from an item in Inventory, with List… under Marketplaces, the same as every other marketplace. The eBay page no longer has its own Create draft and Publish on eBay forms. Importing from eBay, updating inventory price and quantity, and editing a live listing are still there.

## 0.1.414 — 2026-10-26

- List on eBay as an auction. Choose the auction length eBay offers for the category, a starting bid, and an optional reserve and Buy It Now. Fixed price stays Good 'Til Cancelled, and auctions sell one item without offers.
- Save an eBay draft without listing it. eBay keeps it out of sight of buyers, Anteroom checks the format, duration and prices eBay saved, and List publishes that same draft.

## 0.1.413 — 2026-10-26

- Select items in the sidebar and choose List / delist to list, delist or relist them on the marketplaces you name. You review what happens to each item and confirm once; items then run one at a time, each marketplace once. An item already live is never taken down by List, a marketplace where it sold is left alone, and a failed item is shown instead of retried.

## 0.1.412 — 2026-10-26

- Save selected listing fields as reusable templates. Apply one with a before-and-after review, or create a separate local draft with its own SKU and quantity. Manage templates in Settings → Listings; photos, videos and marketplace links stay with the original item.

## 0.1.411 — 2026-10-26

- Upload, preview, select and clear a Poshmark listing video shorter than 15 seconds. Save Draft checks that Poshmark kept it, and List waits for video processing before publishing.
- Marketplace actions wait for your latest field edit to finish saving, so Save Draft uses the revision you just edited.

## 0.1.410 — 2026-10-26

- Listing again on Depop keeps the category, size, colour, brand, photos, measurements, and shipping on the draft you already saved.
- Moving a live Depop listing to another category sends the listing Depop already has, including its photos and shipping.
- When Depop refuses a listing, the message includes what Depop said.

## 0.1.409 — 2026-10-26

- Listing again on Depop fills the draft you already saved, including category, size, colour, brand, and photos.
- Choosing no brand on Mercari clears a brand that was already on the draft.
- Leaving SKU empty keeps it empty in Anteroom. eBay still needs its own inventory key, and that key is not saved as your SKU.

## 0.1.408 — 2026-10-26

- Add Poshmark sizes to an inventory list, including custom sizes, with a separate quantity and SKU for each. The rows fit the editor panel, and saved drafts check every size and SKU.
- Mercari accepts its own No Brand response instead of reporting a mismatch after you clear a brand.
- Check compares Mercari and Depop against the full revision sent, including shipping and size, and keeps the number of photos sent with the action.
- Direct listing progress names the marketplace and action instead of calling it a Vendoo draft. Poshmark updates check all saved fields, including inventory.

## 0.1.407 — 2026-10-26

- Scheduled listing, delisting and relisting now wait for your review of each item and named marketplace. Changed drafts, photos or links need a new review, and failed marketplace actions stay visible without automatic retries. List never takes down a live listing; choose Relist explicitly.

## 0.1.406 — 2026-10-26

- Save a private Poshmark draft, reuse it, and review shipping discounts, availability, cost, quantity, and private notes before listing. Later edits keep the revision already sent so Check verifies the right copy.
- Choose Mercari prepaid labels or ship on your own, with the correct shipping payer checked on the saved draft.
- Set Depop worldwide shipping separately from the item price, including free shipping or turning it off.
- Edit Sellwild category, condition, and USPS packaging in its form; its description is optional.
- Clear eBay automatic offer amounts without bringing them back, edit condition notes, and use native numeric limits and free-text choices.

## 0.1.405 — 2026-10-26

- eBay accepts Size when Size Type matches. A Medium in Regular is no longer blocked with “Choose Size for the selected parent aspects.”
- Mercari can be listed with no brand. Choose No brand on the Mercari form, clear the Mercari brand from the command line or the assistant, and the brand on General stays. A brand Mercari does not list is left off instead of stopping the listing.
- When Mercari has the same size in more than one group, such as several M (8-10), Anteroom uses the Mercari size type if you set one, and otherwise the size type on the item, such as Petite, Plus, or Tall. With no size type at all, it uses the regular or standard group. If it still cannot tell them apart, the message names the groups.
- Depop keeps the fields and photos on the draft, including after the eight-photo limit, and listing again finishes that draft instead of starting another. When more than one draft matches, Anteroom uses the draft it already saved, and otherwise the same draft each time.
- Changing the category on a live Depop listing updates the product type, colour, and the title Depop builds from them, and keeps every photo already on the listing. If this item has no measurements, the ones on Depop stay. If Depop gives the listing a new link, that link is kept.

## 0.1.404 — 2026-10-26

- Save private Mercari, Depop and Etsy drafts from the listing form without publishing. Draft links show which edits still need saving.
- Mercari categories, brands, sizes and shipping labels now come from Mercari, with current label prices, a choice of who pays shipping, and Smart Pricing with a floor price. Vendoo sign-in is no longer needed for direct Mercari listings. Offer settings are no longer shown as off without checking them.
- Reopening a listing keeps the choices you cleared and the quantity you entered. Send SKU and quantity to Depop, and edit Poshmark quantity, original price and SKU without generated defaults replacing your picks.

## 0.1.403 — 2026-10-26

- Marketplace form edits stay where you put them: Depop style, size, SKU, category, photos, and package dimensions no longer snap back. Each marketplace price follows the item price unless you set that marketplace's own price. Depop can be updated in place, including measurements from the item, and a jacket is no longer filed as a vest. Ship-from stays blank until you save your own location.
- Bottoms now use each marketplace's own sizes: waist and inseam, women's 0–24, and Petite, Plus, or Tall. eBay Best Offer can be turned on, with an auto-accept price and a minimum offer that has to sit below it and below the item price.
- Each marketplace form shows only the fields that marketplace uses for this item's category, department, and condition, and a field with a fixed list opens as that marketplace's own choices. Show all fields opens everything else. Hidden values stay saved.
- Checking men's or women's from the photos works from the command line on its own, and can write that department onto the draft.

## 0.1.402 — 2026-10-26

- Automations lets you schedule a one-time job or a daily or weekly one: delist, relist, regenerate, or drop the price by a dollar amount or a percent, with a floor. A repeating 10% steps down the original price (90%, then 80%, then 70%) and stops at the floor. A one-time drop stays on the first step. That choice lives on the task, so you can switch a task between each cycle and a one-time drop.
- If a relist fails on one marketplace, the others still go back up. The failed ones are tried again, and anything still down is marked “down, needs relist” in the run history and in `anteroom errors list`.
- A task that regenerates a listing waits for your approval before it publishes. Approve publishes it on the marketplaces that task names. You can turn that off for a task when you want the regenerated listing to publish on its own.
- A rule can wait until an item has been listed for a number of days. That date comes from the first successful publish or the Vendoo listing date, and the day a marketplace row was backfilled is used only when nothing earlier is on record. Preview shows the date and where it came from. Sold items are left alone, and each run is kept in the history. A dry run is marked as a dry run.
- You can ask the assistant to set one up and confirm it before it is saved. Nothing runs until you confirm the actions and the marketplaces by name.

## 0.1.401 — 2026-10-26

- Select inventory items and choose Copy items to review separate names, SKUs, quantities, photos and costs. See each result, stop after the current item, and continue or retry the remaining copies without creating duplicates when a reply is lost.

## 0.1.400 — 2026-10-26

- Copy an inventory item into a separate local draft, with a new SKU and quantity and optional photos or cost. Photos stay independent, and marketplace links and sales history stay with the original. Review the item’s details before listing the copy.

## 0.1.399 — 2026-10-26

- Select inventory items and choose Edit fields to review price, cost, quantity, title, description, brand, size or SKU changes together. Add, remove or replace labels in the same review; changed or busy items are skipped, and saved edits stay in Anteroom until you choose a marketplace action.

## 0.1.398 — 2026-10-26

- Record sales amounts, refunds, fees and costs directly in Analytics, with separate currency totals and a review reminder when an order changes. Download inventory and sales CSV files without Vendoo; blank amounts remain unknown.

## 0.1.397 — 2026-10-26

- eBay earnings and listing performance now recognize items imported or linked directly in Anteroom. See original selling fees alongside net proceeds, quantity-adjusted item costs and profit; missing or duplicate links explain what needs review.

## 0.1.396 — 2026-10-26

- List on Vinted saves a draft in the background, the same way as Depop and Mercari, then publishes it only after you confirm List. No Vinted tab opens. If Chrome loses the reply, Check result reads Vinted and does not create it again. You can paste the draft link.
- Detect sales for Vinted is in Settings → Connections with the other Chrome marketplaces. A sale there gets the same notice. Delist the other marketplaces still leaves the place it sold up.

## 0.1.395 — 2026-10-26

- Settings → Listings calls the marketplace checklist Where you list, and Settings → Connections calls the sign-ins Accounts.
- The ships-from ZIP and eBay’s inventory location point at each other. Search finds both from “zip”.
- The live Vendoo request log is marked Troubleshooting.

## 0.1.394 — 2026-10-26

- Sign in to Vinted from Settings → Connections, the same way as Depop and Sellwild. Anteroom shows whether that Chrome sign-in is there. The cookies stay in Chrome, and listing still waits until you confirm List on Vinted.
- Delist on Vinted deletes the listing through that Chrome sign-in, the same way as Depop, Poshmark, and Mercari. A listing that is already gone counts as deleted, and doing it again is safe. When something sells and Delist the other marketplaces is on, Vinted comes down with the others. The place it sold stays up.
- A Vinted listing uses Vinted's own category. The category Vendoo would fill is not typed into Vinted's form.

## 0.1.393 — 2026-10-26

- Direct listing forms now use the catalogs the marketplaces actually list with. Size groups update their size choices, Depop shows each category’s attributes, and Smart Pricing keeps your choice. Fields controlled by Item Details or Settings explain where to change them.

## 0.1.392 — 2026-10-26

- Connecting eBay from Settings now grants access to your shipping, payment, and return policies, so the eBay card no longer shows "eBay denied access" right after you sign in. If eBay still refuses, the card says why and offers a Reconnect eBay button.

## 0.1.391 — 2026-10-26

- Recover missing eBay and Etsy sales from Orders, including cancellations and refunds on older orders changed during your selected dates. Check pages sequentially, stop and resume, and keep existing links, dismissed alerts and local quantities intact.

## 0.1.390 — 2026-10-26

- Multi-unit sales no longer assume the whole item sold out. Sync verifies remaining stock, sale alerts show what remains or ask you to check, and partial or unverified multi-unit sales keep other listings intact.

## 0.1.389 — 2026-10-26

- Sync now checks linked eBay and Etsy listings directly. Open Marketplace details to see their status, price, available quantity and differences from Anteroom. Your local edits and live listings stay unchanged.

## 0.1.388 — 2026-10-26

- Import your active Etsy listings and photos directly into Anteroom from Etsy → Listings → Import from Etsy. Select a page or enter a listing ID; existing edits and photos stay intact, and live Etsy listings are left unchanged.

## 0.1.387 — 2026-10-26

- Import existing eBay listings and photos straight into Anteroom from eBay → Listings → Import from eBay. Select items from your active listings or enter a listing ID; existing items keep their edits and photos, and partial photo failures are shown. The import leaves live eBay listings unchanged.

## 0.1.386 — 2026-10-26

- Marketplace forms keep multiple selections, flag unavailable saved choices, show where dropdown choices came from, and let you refresh them. Clearing Material stays cleared after saving.
- Mercari draft edits keep their photos and use the current size and shipping location. Poshmark no longer reports a failed update when the price is unchanged, and older eBay descriptions can be revised without losing their text.
- Direct listings show Active even after an older Vendoo send failed. Listing checks catch duplicate or sold items, missing sizes, and Etsy eligibility before starting a send.

## 0.1.385 — 2026-10-26

- Listings can now be written by OpenAI, Anthropic, Google Gemini, xAI Grok, Mistral or OpenRouter using your own API key, added in Settings → Providers or the setup guide. OpenRouter can also connect by signing in. Each provider bills you per use, separately from a ChatGPT or Claude subscription, and your ChatGPT and Claude sign-ins keep working as before.

## 0.1.384 — 2026-10-26

- Match previously received sale alerts when you link an item, sync its marketplaces, or refresh Etsy alerts. Other-marketplace warnings now include Anteroom's direct listings and exclude listings already sold or removed, without relying on Vendoo.

## 0.1.383 — 2026-10-26

- Settings → Agents shows whether the anteroom command is installed, the address an agent should use, and copy-ready setup for Cursor, Claude Desktop, and Claude Code. Test connection checks that the command can reach this app.

## 0.1.382 — 2026-10-26

- `anteroom api request` can read the changelog and other ordinary pages again, and a failed command still prints `--json` when you asked for it.

## 0.1.381 — 2026-10-26

- Link existing marketplace listings with consistent URL checks and without tracking parameters. Anteroom catches links already attached to another item and leaves sales unmatched when duplicate inventory makes their owner unclear.

## 0.1.380 — 2026-10-26

- You can drive Anteroom from the terminal with the `anteroom` command. It can do what the app's API already allows, prints `--json` for an assistant, and will not delete, publish, or delist unless you pass `--confirm`.

## 0.1.379 — 2026-10-25

- Mercari listings now carry the brand, size and prepaid shipping label (buyer pays), and Anteroom checks Mercari's draft before posting. A category with sub-categories, like Boys coats & jackets, has to be narrowed down first.
- Depop kids' sizes use Depop's ages (XL 18/20 lists as 16 years, not Other). The jacket or dress type is filled in, the listing shows your city, and material is left blank unless the tag shows it.
- eBay descriptions keep their paragraphs, season keeps every season you chose, and Anteroom no longer guesses care instructions, neckline or other details it can't see. Your Best Offer amounts and store categories are used.
- Poshmark: Smart Pricing stays off when you turn it off, your cost is saved with the cents, and the Poshmark tab offers Poshmark's own conditions, colors and sub-categories.
- Sellwild picks a kids category for kids' items and recalculates its suggestion each time you list.
- Discard next to Unsent edits keeps everything Vendoo doesn't hold, warns when the listing is already live from Anteroom, and a sync that finds changes on both sides now asks instead of overwriting your edits.

## 0.1.378 — 2026-10-25

- eBay's Size is now always one of the eBay category's own choices, so a listing sized XXL goes to eBay as 2XL and OS as One Size instead of being left empty, and setting eBay's Size to 2XL no longer snaps back to XXL. The same size written another way (XXL, 2XL, 2X) is matched on every marketplace.
- Notes about a marketplace leaving a field empty now have Edit and Ask chat buttons. A required field that is simply empty now says so.

## 0.1.377 — 2026-10-25

- A listing you delisted everywhere from Anteroom now reads Draft in the sidebar, and its marketplace logos go away, even though Vendoo still calls it Active.

## 0.1.376 — 2026-10-25

- List on Vinted uploads the item on Vinted when you confirm it. Send does not list it, and it does not save a Vinted draft.

## 0.1.375 — 2026-10-25

- Depop listings use the description only. The title is no longer repeated at the top.

## 0.1.374 — 2026-10-25

- The Sync button on a listing now syncs your direct listings too: it settles unconfirmed results and checks Poshmark, Mercari, Depop and Sellwild for sales right away. Sales of items you listed directly are now noticed on every marketplace.

## 0.1.373 — 2026-10-25

- Turn off Send to Vendoo in Settings → Listings → Vendoo to hide the button under every listing when you list without Vendoo.

## 0.1.372 — 2026-10-25

- Inventory shows a listing as Active, with its marketplace icons, after Anteroom publishes it. Vendoo can still call that item a draft.

## 0.1.371 — 2026-10-25

- After Depop posts, View opens the public Depop page.

## 0.1.370 — 2026-10-25

- Listing on Depop no longer asks you to check Depop yourself when Depop has already answered. If the save is refused, press List again.

## 0.1.369 — 2026-10-25

- After the photos upload, eBay no longer answers with an inventory error. The extra bit on the photo address is left off, and the packed weight is sent as a number.

## 0.1.368 — 2026-10-25

- eBay photos are sent to eBay's photo address, so List no longer stops with "not found" before the listing exists.

## 0.1.367 — 2026-10-25

- If eBay saves the ship-from ZIP and then says it is unavailable, listing continues. If that location never lands, Anteroom says eBay is temporarily unavailable so you can press List again.

## 0.1.366 — 2026-10-25

- Before you press List, Anteroom holds it off when Poshmark does not offer that size, or when the Depop parcel is not one Depop ships.
- Regenerating a listing saves Poshmark's and Depop's own category on it. Send to Vendoo still uses Vendoo's categories.

## 0.1.365 — 2026-10-25

- Listing on eBay uses the ZIP saved under Settings → Connections → eBay as the inventory location when eBay does not have one yet.

## 0.1.364 — 2026-10-25

- Sellwild lists Pre-Owned Excellent as Like New and Pre-Owned Good as Good.
- A direct list uses Poshmark's or Depop's own category when Vendoo's id is out of date. Send to Vendoo still uses Vendoo's categories.
- Before you press List, Anteroom says when Poshmark will round the price, list one item, or leave a color off. It holds List off for a missing Depop parcel, a Mercari category that still has subcategories, and a required eBay or Etsy field it already knows.

## 0.1.363 — 2026-10-25

- Set eBay's inventory location under Settings → Connections → eBay. Edit inventory location opens that setting, and Anteroom writes the ZIP or place on the general form and on eBay.

## 0.1.362 — 2026-10-25

- Changing the tag size still updates Depop when Depop was using that same size.

## 0.1.361 — 2026-10-25

- Depop size stays on Other when you set it there, instead of snapping back to the tag size.

## 0.1.360 — 2026-10-25

- When Mercari, Depop, Poshmark, or Sellwild signs you out, Anteroom asks you to sign in. Sign in opens that shop in Chrome.

## 0.1.359 — 2026-10-25

- Etsy's when-made year ranges keep moving so vintage stays 20 years old, including after 2029.

## 0.1.358 — 2026-10-25

- Depop uses Other when a brand is missing or not on Depop's list.
- Generated descriptions stay within the shortest marketplace limit, so Mercari, Poshmark, and Depop can take the same description.

## 0.1.357 — 2026-10-25

- A boys size such as XL (18/20) stays on Poshmark's boys scale.
- If you delete a Depop draft, List creates a new one instead of looking for the missing draft.
- Grouped values such as Best Offer and Depop shipping are their own fields. A form no longer shows [object Object].
- Menus with a fixed list of choices can be searched, including Depop's product type.

## 0.1.356 — 2026-10-25

- eBay and Etsy categories for a direct listing come from each site's own category list. The eBay and Etsy sections of the editor show that category and its fields. Send to Vendoo still uses Vendoo's categories and field names.

## 0.1.355 — 2026-10-25

- You can turn on Delist the other marketplaces in Settings → Connections. When something sells, Anteroom takes it off the other places it is still listed. The marketplace it sold on is left alone. This stays off until you turn it on.

## 0.1.354 — 2026-10-25

- The listing status on a thread shows where the item is actually live, including listings you already had on a marketplace, instead of saying not listed for all of them.

## 0.1.353 — 2026-10-25

- Choosing an eBay shipping policy in Settings → Connections saves that choice. Payment, returns, and the ships-from location stay automatic when the account has only one of each.

## 0.1.352 — 2026-10-25

- Detect sales checks your whole shop, including closets with hundreds of listings. Depop and Mercari are read from your sales. Poshmark and Sellwild compare the live closet with what Anteroom still has listed. The shops take turns a few times an hour, with an uneven gap between checks. You hear once when something sells, and only for items Anteroom still shows as listed there.

## 0.1.351 — 2026-10-25

- Before List, the Marketplaces section shows what eBay, Etsy, and Sellwild still need, with Edit and Ask chat, and List stays off until those are filled.
- Etsy listings include tags, materials, the category's own properties, and the return policy you choose in Settings → Connections.
- eBay item specifics use eBay's exact field names for that category. When the account has more than one shipping, payment, or return policy, or more than one location, you choose which one new listings use in Settings → Connections.

## 0.1.350 — 2026-10-25

- Poshmark, Mercari, and Depop sizes, brands, and shipping now come from the options on your signed-in account. A size that does not belong in that category, such as an adult size on a kids' listing, stops the listing before anything is created.
- Mercari and Depop use the ZIP you set in Settings → Listings as the ships-from address.

## 0.1.349 — 2026-10-25

- Each marketplace form shows only its own fields, once each, under the names the marketplace uses. Fields from another marketplace no longer linger after switching tabs, and a marketplace's own category shows as its Category.

## 0.1.348 — 2026-10-25

- eBay now gets the condition you picked: New with imperfections, Pre-owned Excellent, Good and Fair each list as eBay's own clothing grade instead of all becoming "Good". If a category doesn't take that condition, Anteroom says so and lists nothing.
- Depop keeps the condition you picked, so Brand new and Like new no longer go missing or drop to Used - Good.
- Poshmark gets a whole-dollar price, rounded like Vendoo does, and a plain "New" is no longer dropped. An item with no condition stops before anything is listed.
- Etsy's "when made" ranges follow the year, so listings keep working after January 1.

## 0.1.347 — 2026-10-25

- List on a marketplace now runs in the background with its progress shown in the Marketplaces section, and Cancel stops it before it publishes. A queued Send to Vendoo waits until Chrome has finished, instead of failing because Chrome was still busy.
- What Anteroom knows about each marketplace listing is kept on its own, so Clear, Regenerate or an older open window can no longer erase it.
- When a result is unconfirmed, Anteroom checks it by itself after a lost reply, on startup and when Chrome reconnects. Nothing is ever listed by that check. If it still can't tell, look on the marketplace and choose “I checked it myself” or a Mark option.
- A refused eBay listing can be listed again without making a second one: the same item and offer are reused, eBay's own message is shown, and its general color, size and department now fill eBay's item specifics. Missing fields get Edit links and an Ask chat button.
- Etsy explains up front when an item isn't vintage, handmade or a craft supply, finds a draft whose reply was lost, retries an activation that didn't happen, and keeps its photos in step when you change them.

## 0.1.346 — 2026-10-25

- Listing directly on Poshmark, Mercari, Depop and Sellwild is sturdier: a slow or busy marketplace is asked again only when nothing could be listed twice, a stopped Poshmark listing cleans up its unlisted post, and Mercari no longer needs a reconnect when its sign-in refreshes.
- When a marketplace refuses, Anteroom says why in plain words and shows the marketplace's own message: signed out, a bot check, too many requests, or the exact fields it still needs (such as Depop's brand or parcel size).
- Depop descriptions are kept within Depop's 1,000-character limit.

## 0.1.345 — 2026-10-24

- Listing fields are grouped into sections — Pricing, Condition, Item, Size & fit, Color & material, Shipping, Inventory and More details — each showing how many are filled. Required fields come first.

## 0.1.344 — 2026-10-24

- Settings → Connections opens on Marketplaces. Each marketplace has Detect sales. Turn it off to stop new sale notices there. Nothing is taken down until you choose.

## 0.1.343 — 2026-10-24

- Delist everywhere ends the eBay listing. Mercari and Depop stay marked delisted when those sites have already taken the item down.

## 0.1.342 — 2026-10-24

- Poshmark original price is always 0.

## 0.1.341 — 2026-10-24

- On a live eBay, Etsy, or Poshmark listing, **Update…** writes the listing saved in Anteroom onto that listing, after you confirm. It changes the one that is already up.

## 0.1.340 — 2026-10-24

- Non-vintage Etsy items use a year range for when they were made. Made To Order is no longer selected for an item that already exists.

## 0.1.339 — 2026-10-24

- Send eBay offers from Marketplaces → eBay → Offers. Settings → Connections keeps the eBay sign-in for sale alerts.

## 0.1.338 — 2026-10-24

- Settings → Connections has a **Chrome sign-in** for Depop, Poshmark, Mercari, and Sellwild. Anteroom shows who is signed in and when that sign-in expires, and asks you to sign in again when it expires or is about to. The cookies and tokens stay in Chrome.

## 0.1.337 — 2026-10-24

- The marketplace list no longer includes JSON, and it no longer says "Not listed" on every row. A status only appears when a marketplace needs you, such as Unconfirmed or Not eligible.
- Send to Vendoo stays quiet until the listing can actually be sent, and says how many issues are in the way. Fix in chat handles those. Filling empty fields is a separate button.
- List… is the only step onto a marketplace, including eBay. One confirmation creates the live listing. There is no save-draft or publish step.

## 0.1.336 — 2026-10-24

- A listing now opens like Vendoo: the marketplaces run down the left, and the form for the one you select is on the right. **General** is the photos and the shared fields. Each marketplace form shows every field that listing needs — title, description, price, brand, condition, size, category, and that marketplace's own fields — with what's already filled in, so you can check it before listing. List, Publish, Delist and Mark as listed sit with that form. The Input and Forms tabs are gone. The listing panel starts wider so the form has room beside the list, and you can drag it wider.

## 0.1.335 — 2026-10-24

- Each marketplace in the **Marketplaces** section now has its own **⋯** menu: List or Publish, Delist, and Mark as listed, sold or not listed. Marking changes only what Anteroom records, never the marketplace, so you can fix a listing Anteroom got wrong. Mark as listed asks for the listing link; Anteroom then treats that listing as live there, can delist it, and matches eBay and Etsy sales to it. The delist checkboxes are gone; Delist everywhere stays when more than one listing is live.

## 0.1.334 — 2026-10-24

- Listing and delisting now live in one **Marketplaces** section at the top of a listing's Input tab. Each marketplace has one row with a clear status (Not listed, Draft saved, Live, Sold here, Deleted) and only the actions that apply, with delist checkboxes on live listings. Etsy and Sellwild settings, errors and the Etsy eligibility note appear in their own row instead of long explanations and banners. Sellwild's categories are searchable, and the Forms tab starts straight at the fields.
- Nothing to fill in to list: Sellwild's category and condition come from the listing itself (its Poshmark, Depop and general categories, title and condition), shown in the row with **Change** if you want another. Etsy uses default shipping and processing profiles you choose once in Settings → Connections, with each listing's own package weight and size. A sold item is no longer offered for listing elsewhere.

## 0.1.333 — 2026-10-25

- Etsy, Poshmark, Depop, and Sellwild no longer have a Marketing tab. Only eBay keeps one, since its marketing tools connect to eBay directly. Ad spend you already recorded still counts in Analytics.
- List on Poshmark in one step. On the listing, choose **List…** on Poshmark and confirm: Anteroom creates the live listing with its category, size, condition, brand, colors, style tags, original price and Smart Sell minimum, without a Poshmark draft and without opening a tab. A listing Poshmark refuses is removed so you can fix it and try again.

## 0.1.332 — 2026-10-24

- Delist an item from its marketplaces in **Live listings** on the listing. Pick marketplaces, or choose **Delist everywhere**, and confirm. Anteroom deletes the listing on Etsy, Poshmark, Mercari and Depop, ends it on eBay (eBay has no delete), and delists it on Sellwild. It works for items listed through Vendoo too, and never touches the marketplace where the item sold. No marketplace tab opens.
## 0.1.331 — 2026-10-25

- Poshmark, Depop, Sellwild and Etsy now look like the eBay tab: the same heading, tab bar, and cards, each in its own marketplace color. Poshmark, Depop and Sellwild get a Dashboard with your sales, revenue and profit for any dates, and a Marketing tab.

## 0.1.330 — 2026-10-24

- Publish to Sellwild without opening a tab. Pick a Sellwild category and condition in **Marketplace drafts** (Anteroom suggests both), save in Anteroom, then confirm **Publish…**. Anteroom creates the listing with your signed-in Sellwild account, uploads the photos and activates it, once. It needs a package weight and size, and a ship-from address saved on Sellwild.

## 0.1.329 — 2026-10-24

- Save drafts straight to Poshmark, Mercari and Depop from **Marketplace drafts** in a listing, without opening any marketplace tab. Anteroom uses your signed-in Chrome in the background, reads each saved draft back to check it, and only opens a tab when you connect or reconnect a marketplace. Publish to one marketplace with a separate confirmation; it is never queued or retried.
- Mercari drafts include the listing's Mercari category, condition, zip code and package weight, with buyer-paid shipping. Add a package weight before saving to Mercari; pick brand, size and shipping option on Mercari.
- Save Etsy drafts and photos through the official Etsy API, choosing your shipping and processing profiles, and review the saved draft before confirming publication.
- Keep Sellwild drafts in Anteroom, review the prepared form in Chrome, and publish only after a separate confirmation. Listings held by Sellwild show as in review.

## 0.1.328 — 2026-10-25

- Removed the Queue page from navigation. Approved Sends still wait their turn and save drafts in the background; progress stays visible on each listing.
- Replaced the separate Marketing tab with marketplace-specific tools, sale calendars, and ad history. Inventory discount suggestions are in Analytics.
- Added an Etsy dashboard under Marketplaces with live shop metrics, orders, shipping status, and listings. Etsy sales planning and ad imports are in its Marketing tab.

## 0.1.327 — 2026-10-24

- Choose eBay or Etsy from the Marketplaces hub. Keep eBay draft details when switching channels, and open Etsy sale alerts and Shop Manager from one place.

## 0.1.326 — 2026-10-24

- See eBay order proceeds and matched item costs using the permissions already available to Anteroom. Grant all workspace permissions together, and load payment disputes correctly.

## 0.1.325 — 2026-10-24

- Preview eBay offers in Settings → Connections, set a minimum price for each item, and choose to send now or enable automatic offers while Anteroom is running. Offers use live eBay prices, and uncertain sends pause for a Seller Hub check.
- Open the eBay workspace for earnings and item costs, traffic, buyer messages, orders, refunds, discounts, ads, listing drafts, and active comps. Review and confirm each account change; publishing remains a separate choice.
- Find eBay tasks more easily with a clearer dashboard, readable forms, named email audiences, and a separate review screen. Entered details stay in place when you change a listing selection or item specifics.

## 0.1.324 — 2026-10-24

- T3 Code is now credited in the README, and its copyright and license notice is included with the app.

## 0.1.323 — 2026-10-24

- Keep your ChatGPT sign-in across app updates and restarts, and stay signed in when a temporary connection or service error interrupts session renewal.

## 0.1.322 — 2026-10-24

- New: sale alerts. In Settings → Connections → Sale alerts, connect your eBay account (Etsy once Etsy approves Anteroom's app) and Anteroom hears about a sale the moment it happens, even before Vendoo does. Your Mac shows a notification, and the listing shows which other marketplaces it's still on, with a button to open it in Vendoo and delist it there. Vendoo still does all the listing and delisting.

## 0.1.321 — 2026-10-24

- The Chrome extension no longer runs on etsy.com. It never filled Etsy's own site, and Etsy listings still go through Vendoo's Etsy section exactly as before.

## 0.1.320 — 2026-10-24

- The Usage button at the bottom of the sidebar now opens its own Usage page, like Analytics and Marketing, instead of jumping into Settings. Click it again to go back. Usage is no longer a section in Settings.

## 0.1.319 — 2026-10-24

- Reading measurements from photos with Cursor no longer fails with "database is locked" when several listings are read at once.

## 0.1.318 — 2026-10-24

- The Inventory and Vendoo sync buttons are gone from the bottom of the sidebar. Sync from Vendoo now lives in Settings → Data (and still on Analytics).

## 0.1.317 — 2026-10-24

- Grailed categories like Menswear › Outerwear › Light Jackets are saved and reused again instead of being refused as "incompatible" in the logs.

## 0.1.316 — 2026-10-24

- A Usage button now sits along the bottom of the sidebar with the other buttons. It opens Settings → Usage, so you can check how much of your plan is left without digging through Settings.

## 0.1.315 — 2026-10-24

- Etsy only allows vintage (20+ years), handmade, craft supplies, and digital items, and it removes modern resale. Send to Vendoo now leaves the Etsy form empty for modern resale items, so Etsy never shows as ready for them in Vendoo, and the listing says "Not sent to Etsy: modern resale items aren't allowed there." Vintage, handmade, supply, and digital items go to Etsy as before.
- Relist reminders no longer ask you to relist a modern resale item on Etsy.
- Analytics has a new "Not allowed on Etsy" list: modern resale items still live on Etsy, each with a link to open it there, so you can delist them yourself before Etsy does. Anteroom never delists anything for you.
- Vintage items now reach Etsy with their real decade. Before, Anteroom sent every item to Vendoo's Etsy form as made in 2020–2026, so a 1990s piece looked brand new to Etsy.

## 0.1.314 — 2026-10-24

- Running several listings at once is much lighter on your Mac. Anteroom no longer re-reads its whole category catalog after every send or sync, opens faster after a restart, and stops re-shrinking the same photos when you regenerate.
- With Claude or Cursor, Anteroom keeps their helper programs running between steps instead of starting a fresh one for every step, so many listings can generate together without bogging down your Mac. With ChatGPT, Anteroom keeps its connection open, so each listing finishes a little sooner.

## 0.1.313 — 2026-10-24

- The app is now called Anteroom, with a new doorway icon. It updates itself as usual and moves to Anteroom.app in Applications. Your listings, photos and settings come along to the new Anteroom data folder, and the Chrome extension keeps working without being loaded again. If you pinned the app to the Dock, pin Anteroom again after the update.

## 0.1.312 — 2026-10-24

- In Inventory, your open listings now show as tabs in the top bar, so they no longer overlap the title and the listing starts right under the bar.

## 0.1.311 — 2026-10-24

- The top bar now blends into the window like T3 Code's: the listings sidebar, the main pane and the right panel each run to the top edge in their own colour, and the page title sits in the main pane.

## 0.1.310 — 2026-10-23

- Sizing checks no longer flag a listing just because its tag writes the size another way. A tag reading Large, LARGE (12/14), 2X, XXL or X-Large now matches L, 2XL or XL, and photos where no size could be read are no longer counted as a different size. The business assistant's sizing counts shrink to the listings that really disagree.

## 0.1.309 — 2026-10-22

- Studio stops asking for your Keychain password every time it opens. Updates used to leave files from older versions inside the app, so macOS no longer recognised it as the app you had allowed. Updates now replace the app whole. The update that brings this fix is still installed the old way, so you may be asked once more after it.

## 0.1.308 — 2026-10-22

- The business assistant now uses far less of your Claude plan on each question. It used to read every listing and every sourcing box each time. Now it reads a short summary of your shop: your totals, your best brands and categories, the listings that have sat longest, your latest sales and the 15 best boxes. When a question needs more, such as ranking every box or the details of one listing, it looks those up first. Its answers are as complete as before and usually start sooner.

## 0.1.307 — 2026-10-21

- On your phone, every page has one header with a menu button at the top left that opens all of Studio's pages. A listing now shows Chat and Listing as two tabs under its title, so the chat gets most of the screen.
- Inventory on your phone scrolls as one list. Select sits at the top, and in Select mode tapping a listing ticks it. Each listing's Rename and Delete are behind its ••• button.
- Typing on your iPhone no longer pushes the page away: the header stays put and the message box sits just above the keyboard. Return adds a new line; the send button sends.
- To reorder or delete a photo on your phone, tap it and use Earlier, Later or Delete in the photo viewer.
- Buttons, menus and rows on your phone are big enough to tap, text boxes no longer zoom the page, and the Queue, ad spend, Logs, Usage and setup guide fit the screen.

## 0.1.306 — 2026-10-21

- Ask the assistant whether a Sourcing box is worth buying and it now looks at the box's own photos, and frames from its video, on the store's page right then, before it answers. You get Buy, Maybe or Skip for each box, with the reasons: brands it could see on tags, condition, sizes, season and weight, how much of the box the photos actually show, and any red flags such as stock photos or a single photo for a big lot. It says which boxes it really saw photos for. A box whose photos would not load counts as not viewed, never as "looks fine". Nothing is downloaded to your Mac.
- Box links from the assistant are the real ones from the Sourcing tab. It no longer makes a link up from a box's title, and any link Studio did not give it is removed from the answer.
- When the assistant looks something up and nothing matches, or the lookup fails, it is told so and says so, instead of quietly guessing.

## 0.1.305 — 2026-10-21

- A question you send while the assistant is still answering is no longer lost: it waits under the answer marked Queued and sends as soon as the answer finishes. You can remove it before then.
- The assistant no longer gets stuck looking busy after a reply when Studio is busy saving something else in the background.
- The chat stays on the newest line while the assistant thinks and writes, on the phone too, and stays exactly where you left it when you scroll up to read. Listing chats get the same fix.
- Answers come back faster: the assistant reuses what it already read about your shop for a couple of minutes (refreshed the moment a listing, sale, box or sourcing check changes), and Claude reuses the shop details it already read for follow-up questions instead of reading them all again.
- "About your business" and the facts the assistant remembers moved to Settings → Assistant, where you can edit the note and remove any fact.
- The "Clear conversation" button is gone. Start a new chat for a fresh start, or delete a chat from the sidebar.

## 0.1.304 — 2026-10-21

- A listing no longer fails with "ebay_specifics.unitQuantity: Input should be a valid string" when the AI writes a number like Unit Quantity 1 without quotes. Numbers in eBay, Depop and Etsy specifics are now read as text.

## 0.1.303 — 2026-10-21

- The model picker in the chat box now works like T3 Code's: providers down the left with a Favorites star at the top, a "Search models..." box, each model with its provider underneath, and ⌘1–⌘9 to pick one. Star a model to keep it under Favorites on every Studio you use. Effort moved behind the "…" button and only lists what the chosen model supports.
- ChatGPT, Claude and Cursor now show T3 Code's logos everywhere, and Xiaomi MiMo's M is drawn to match.
- New Settings → Usage shows how much of each subscription is left and when it resets: ChatGPT's session and weekly limits, Claude's session, weekly and per-model limits, and Cursor's monthly pools. Xiaomi MiMo doesn't report usage, so it says so. Type /usage-limits in the chat box to see the current provider's.

## 0.1.302 — 2026-10-21

- The assistant now sees every box on the Sourcing tab, not only the buy list: each box's store, title, link, price, shipping, piece count, what's in it, resale estimate, projected profit and return, and how far it misses your minimum return when it does.
- When the buy list is empty, the assistant says why, for example how many boxes reach your minimum return and which check stopped the rest, and warns you when the box data is old or your settings changed since the last check.
- Ask the assistant to rank the boxes against what you sell: it sets each box beside your own sales of that kind of piece over the last year (how many, average price, margin, days to sell) and your sales by category.

## 0.1.301 — 2026-10-21

- Your listings stay on the left while you talk to the assistant. Its chats moved to a panel on the right, which you can hide from the top bar or resize. On a phone, the chats button at the top opens them.
- The left sidebar opens wide enough to show every button along the bottom. If you dragged it wider, it keeps your width.
- The buttons along the bottom follow your day: Assistant and Inventory first, then Vendoo sync, Sourcing and the Queue, then Analytics and Marketing, with Settings and updates last. Each one shows its name when you point at it.

## 0.1.300 — 2026-10-20

- MiMo’s icon is the M from Xiaomi’s logo, so you can tell it apart next to ChatGPT, Claude, and Cursor.

## 0.1.299 — 2026-10-20

- The business chat remembers facts about how you run the shop. They stay when you start a new chat, and it updates one when you correct it. About your business shows them, and you can remove one that is wrong.

## 0.1.298 — 2026-10-20

- The sync time on a listing stays on screen. When the header is full, it wraps onto the next line instead of being cut off.

## 0.1.297 — 2026-10-20

- The bottom status bar is gone. The version is in Settings → General → About, and whether the extension is connected is in Settings → Connections.

## 0.1.296 — 2026-10-20

- The thread list on the left is black, the same surface T3 Code uses.

## 0.1.295 — 2026-10-20

- The listing list no longer has a Settled section or a settle button. Sold listings stay under the Sold filter.
- The status bar no longer repeats the model. The model is chosen in the chat.

## 0.1.294 — 2026-10-20

- The listing panel no longer has a Fields tab. Input and Forms sit next to Open listing and Regenerate, and marketplace fields are edited on Forms. Hidden fields are still restored in Settings.
- Studio opens on the business assistant. Each of its conversations is a thread in the sidebar, separate from inventory.
- The model menu shows one current model from each family instead of every model the provider offers. The full list is still in Settings → Providers.
- The business assistant opens like its own chat: a new conversation in the middle, past chats in the sidebar, and Inventory is how you get back to listings.

## 0.1.293 — 2026-10-20

- Cursor generates listings faster. It keeps one connection open instead of starting a new one for every step, category picks and JSON fixes use the lightest reasoning, and sold-comps search stops after eight lookups.

## 0.1.292 — 2026-10-21

- Chat follows a reply while it is being written, then folds the work into a "Worked for…" line you can open. A button brings you back to the latest message.
- You can attach photos in chat, pick the model and effort from the message box, and the business assistant uses this same chat.

## 0.1.291 — 2026-10-21

- The rest of Studio matches the new look: sidebar, settings, providers, queue, analytics, marketing, sourcing, and the listing editor.
- Toasts, confirmations, empty screens, and loading placeholders use that same look.

## 0.1.290 — 2026-10-21

- Listings generate faster: sold comps, active listings, categories and each marketplace's fields now run side by side, and comp research starts from a quick first look at the photos instead of waiting for the full read.
- Studio keeps how long each step of a listing took, so slow steps are easy to spot.
- Brave search stops trying for the rest of the month once its quota runs out, runs alongside the other comp searches, and uses at most 4 searches per listing.

## 0.1.289 — 2026-10-21

- Fields for marketplaces you turned off in Settings, like Grailed and Shopify, no longer show up after you send to Vendoo.
- "Ask chat for fields" no longer counts package weight when the listing already has one, and no longer asks for a SKU or second color you left blank on purpose.

## 0.1.288 — 2026-10-21

- Fixing a listing's category from chat now sticks. Before, the "Category must be a terminal Vendoo path" error came back no matter how many times you asked.
- Categories read from a Vendoo draft keep their " > " steps instead of running the words together.

## 0.1.287 — 2026-10-20

- Boxes you bought now grade each box and store like a supplier: average sale, how many sold for $35 or more, how much sold within 30, 60 and 90 days of buying, and profit per $100 spent.
- Record how many pieces in a box weren't worth listing. Their cost is spread over the pieces that sell, so cost per piece and profit reflect what the sellable pieces really cost.
- Analytics shows a new Sales by price section: how your sales split across under $20, $20–$34, $35–$59 and $60 and up.

## 0.1.286 — 2026-10-20

- eBay and Poshmark no longer take lowball offers on their own. eBay accepts offers at $2 under your price, turns down anything more than $4 under, and sends the rest to you; Poshmark Smart Sell uses the same $4-under floor. Before, eBay auto-accepted 40% of the price and Poshmark went as low as $5.

## 0.1.285 — 2026-10-20

- Fixing a listing's category from chat now sticks. Studio was saving the Vendoo category with the arrows between levels missing, so "Category must be a terminal Vendoo path" kept coming back.

## 0.1.284 — 2026-10-20

- A mixed box (sold by the pound) now explains its sales list correctly: it is priced from the median of everything you sold in the last 90 days, and the list shows your most recent sales of any kind. Before, it said those sales came from a marketplace search for that kind of piece.

## 0.1.283 — 2026-10-19

- Suggestions now put the 60+ day listings worth relisting first: ones like what sold in your shop in the last 60 days (same brand or category), then ones in the season buyers are shopping for now, then the oldest. Out-of-season items sink to the bottom. Each card says why, for example "8 like it sold · In season".

## 0.1.282 — 2026-10-19

- Measurements read from photos now round to the nearest half inch, so you get whole numbers or .5 instead of .25 or .75.

## 0.1.281 — 2026-10-19

- Fewer "Python wants to use your confidential information" Keychain password prompts. Studio's own checks were reading your Keychain every time they ran; they now use a throwaway one and leave yours alone.

## 0.1.280 — 2026-10-18

- Opening, refreshing or updating a listing you already sent no longer hangs for 45 seconds before showing Vendoo's copy. Studio was throwing away Vendoo's answer for listings whose send had finished.
- If a Send to Vendoo is cut off partway (Chrome reconnects, or Studio restarts or closes the window), Studio now starts it again once by itself and picks up the same draft. You only need to click Send again if it is cut off a second time.

## 0.1.279 — 2026-10-16

- Fixed a test that sometimes failed at random because Sourcing kept checking suppliers in the background while the tests ran. Nothing changes in the app itself.

## 0.1.278 — 2026-10-16

- Behind the scenes, the chat panel is split into smaller parts so it is easier to fix and extend. Chat works exactly as before.

## 0.1.277 — 2026-10-16

- Behind the scenes, the listings sidebar is split into smaller parts so it is easier to fix and extend. It works exactly as before.

## 0.1.276 — 2026-10-16

- Sourcing now shows each supplier's five best boxes on every check, even when few pass. Boxes that pass every check come first, then the closest misses, and each one says what it falls short on.
- Thrift Vintage Fashion boxes that earn free shipping keep the sell-through they were picked with. Before, the buy list could show them below your return target.
- Your measured cost per piece no longer counts shipping your buyers paid for, and more than one box of a kind is allowed when your selling window is long enough to sell them.

## 0.1.275 — 2026-10-16

- Behind the scenes, the code behind the Fields panel is reorganized so it is easier to fix and extend. Fields work exactly as before.

## 0.1.274 — 2026-10-16

- Behind the scenes, the listings sidebar's code is reorganized so it is easier to fix and extend. The sidebar works exactly as before.

## 0.1.273 — 2026-10-16

- Behind the scenes, the chat panel's code is reorganized so it is easier to fix and extend. Chat works exactly as before.

## 0.1.272 — 2026-10-16

- Behind the scenes, the part of Studio that builds your Vendoo drafts is reorganized so it is easier to fix and extend. Drafts are saved exactly as before.

## 0.1.271 — 2026-10-16

- Analytics no longer says sales are missing details when Vendoo's Missing Sale Details filter is empty. Studio now flags the same sales Vendoo does, so every sale it lists has something you can fill in on Vendoo.

## 0.1.270 — 2026-10-16

- Open listing no longer sits on "Opening…". It was holding one of Studio's database connections while it waited for Chrome, so it stalled whenever Studio was already busy; it now lets go first.

## 0.1.269 — 2026-10-15

- iPhone HEIC photos dragged in from Finder or the Files app are now saved as JPEGs, so the AI can read them and their thumbnails show. Before, the AI received a file it couldn't open and found no details.

## 0.1.268 — 2026-10-15

- When the AI answers without describing your photos — for example because its model can't see images — the error now quotes what it said, so you know to pick a different photo model.

## 0.1.267 — 2026-10-15

- Settings → Logs has a new Errors list showing the warnings and errors Studio hit while open, with details you can expand. The log file now stamps each one with the time.
- When Cursor fails to read photos, the error now gives Cursor's reason instead of just a run ID.

## 0.1.266 — 2026-10-15

- When photos can't be read, the error now says why — for example an invalid API key or a plan out of usage — instead of only "Photo analysis failed."
- Adding just a Cursor (or any one) AI key is enough: Studio uses it for photos and listings even if ChatGPT is still set as Primary and isn't signed in.

## 0.1.265 — 2026-10-15

- Studio no longer freezes for several seconds when the next send in line starts while it is busy saving, and a send can no longer be started twice at once.

## 0.1.264 — 2026-10-15

- Settings has a new Help section with short step-by-step guides for creating listings, uploading a box, sending to Vendoo, regenerating, marking down stale listings, sourcing boxes, Analytics, connecting Chrome and backups.

## 0.1.263 — 2026-10-15

- A send or fill that stops responding no longer holds up your other listings. After 10 minutes of silence, or right away if Studio was closed mid-send, Studio stops it, marks it failed with a note, and starts the next send in line.

## 0.1.262 — 2026-10-15

- **Settings → Logs → Live requests** now shows everything about each Vendoo call. Click a request to see its full URL with the query string, the request and response headers, and both bodies, pretty-printed. Tokens, API keys, cookies, and upload signatures are still masked.

## 0.1.261 — 2026-10-15

- Mark down several stale listings at once: pick them in Suggestions or the sidebar, review a suggested lower price for each, change or skip any, and apply them together. The new prices stay in Studio until you press Update Vendoo on each listing.

## 0.1.260 — 2026-10-15

- **Read from photos** works in the installed app. It showed "Internal Server Error" for every listing because the app was missing part of the image library the yardstick reader needs. If it can't load, it now says so in plain words.

## 0.1.259 — 2026-10-15

- **Read from photos** is now in the Regenerate review window too, so listings you already saved can have their blank measurements filled from their yardstick photos before they're rewritten. Filled fields are outlined until you change them, and anything you typed stays.

## 0.1.258 — 2026-10-15

- Bulk upload has a **Read from photos** button. It reads the yardstick in each item's photos and fills the blank measurement fields, outlined so you can check them before creating the drafts. Measurements the photos can't settle (usually rise and sleeve) stay blank and are named under the item. Anything you typed stays as you typed it.

## 0.1.257 — 2026-10-15

- The browser responds faster to taps, typing and swipes on your phone, and Back and Forward buttons let you retrace your browsing.

## 0.1.256 — 2026-10-15

- On phones, the listing title and navigation now have room to fit, listing tabs keep their close buttons visible, and chat, settings and dialogs stay within the screen.

## 0.1.255 — 2026-10-14

- Studio stays quick with a large inventory. Refreshing the listing sidebar used to tie Studio up for over a second each time, so with a few listings open, Send to Vendoo could sit on "Updating…" and listings could hang on "Loading..." while everything waited its turn. The sidebar now refreshes about ten times faster.

## 0.1.254 — 2026-10-14

- Pressing Cancel on a send that had just finished no longer shows "Job is already completed" as an error on the listing, and no longer offers to send that message to chat as something to fix. The listing simply shows the finished send.

## 0.1.253 — 2026-10-14

- The sidebar's Not listed filter can now be pointed at a marketplace: turn it on, tick eBay, and you see everything that is not on eBay yet. Tick more than one to see what is missing from any of them, and combine it with labels, status and the other filters.

## 0.1.252 — 2026-10-13

- Studio no longer freezes on "Loading..." while it checks your Vendoo inventory in the background. Opening a listing during a sync could leave the chat, photos and every other panel waiting for minutes; they now load straight away.

## 0.1.251 — 2026-10-13

- The Assistant can now change listings for you. Ask it to mark down stale stock, fix costs, relabel a batch, move listings to a box, or reword a title, and it shows every change as before and after under its answer. Nothing is saved until you press Apply, and Dismiss throws the proposal away.
- Ask it to fix sizing. It now sees which listings have a different size on one marketplace form than another, a title without the size, or a size that disagrees with the tag in your photos. Setting the right size updates every form and the title together, and the proposal shows each form's old and new size.
- Applied changes are saved in Studio as a new revision of each listing, so you can restore the old one from the listing's history. A listing already on Vendoo keeps its old values there until you send it again; the Assistant still never sends or publishes anything.

## 0.1.250 — 2026-10-13

- The bulk upload window and the review window before a rewrite no longer close when you click outside them or press Escape. They close from the new x in the corner, or Cancel, so a stray click cannot throw away the measurements you typed.
- You can rotate photos in both windows: hover a photo and use the arrow in its corner, or click it to enlarge and rotate left or right there.
- You can remove a photo in both windows from the x in its corner. A listing always keeps its last photo.

## 0.1.249 — 2026-10-13

- A plain size like 28 now goes to Depop as 28, not 28". The inches option is only picked when the listing's size says inches (28", 28 in.), or when the marketplace has no plain 28 to pick.

## 0.1.248 — 2026-10-13

- Mercari gets the right waist size on jeans. A size 26 was landing on Mercari as 36 in.; it now lands on 26 in.

## 0.1.247 — 2026-10-13

- Depop no longer gets a made-up size when it does not offer the listing's size. A juniors 15 was landing on Depop as a 24" waist. Studio now leaves Depop's size for you to pick and tells you it could not match it.

## 0.1.246 — 2026-10-13

- Depop gets the size the listing says. A size 14 was landing on Depop as a 12 (and a 12 as a 10, an 8 as a 6, and so on) because Depop numbers its sizes behind the scenes and Studio was reading the listing's size as that number instead of as the size shown in the dropdown.

## 0.1.245 — 2026-10-13

- Send to Vendoo no longer fails with "Read draft version returned 404" when Vendoo takes a moment to save a new draft. Studio now waits for the draft to appear, and if it still has not, says so and picks up the same draft on the next Send instead of making a second one.
- When a linked Vendoo draft is gone, the error now says that in plain words instead of showing a database path.

## 0.1.244 — 2026-10-13

- A regenerated listing is no longer replaced by the old Vendoo copy the next time Studio checks Vendoo. This was putting back the old condition (Poshmark showed Like New, Depop Used - Excellent), the old brand and description, and dropping fields the regenerate had filled, like Facebook's Shorts Length.
- Facebook now has Allow Offers turned on, with the Minimum price set to half the price.

## 0.1.243 — 2026-10-13

- Photos can be rotated. Hover a photo and click ↻ to turn it right, or open it and use ↺ / ↻. The saved photo itself turns, so Vendoo, the marketplaces and listing generation all get it the right way up.

## 0.1.242 — 2026-10-12

- Analytics ranges now read as This week, This month, This year, Last 7, 30 and 90 days, Last 12 months and All time, and a new Custom range lets you pick any From and To dates. Ad spend follows the custom dates too.

## 0.1.241 — 2026-10-12

- Marketing's profit-after-ads card now says what it is: your profit across every marketplace, less your ad spend, with both figures shown. Each marketplace's ad card also shows that marketplace's own profit after its ads.

## 0.1.240 — 2026-10-12

- Analytics can now show sales for the week to date (from Monday), month to date and year to date, alongside the rolling 7, 30 and 90 day views.

## 0.1.239 — 2026-10-12

- Marketing → Ads can take Etsy's stats CSV: download it from Etsy Ads and press Upload Etsy Ads CSV instead of typing the figures. Each day with activity becomes an entry, and uploading a newer export replaces those days.

## 0.1.238 — 2026-10-11

- Sourcing now sets itself up from your sales. Your cost per sold piece (what shipping out your pieces really costs you) and how long you sell for (how long your pieces take to sell) follow your own history, next to your sell-through and fees, so you can open Sourcing and see recommended boxes without touching a setting. Type your own number in More options to take one over.
- The "Most to pay per piece" limit is gone. Sourcing no longer leaves boxes out for costing more per piece than a number you set; the return target and the lower-sales test still decide.

## 0.1.237 — 2026-10-11

- Update Vendoo no longer hangs on "Reading the Vendoo draft…". Checking Vendoo, pulling a draft and opening a listing's fields were holding on to Studio's database connections while they waited for Chrome, so a few slow checks left everything else waiting; they now let go first.

## 0.1.236 — 2026-10-11

- Listings no longer sit on "Loading..." for half a minute. Open live previews and price-drop searches were holding on to all of Studio's database connections, so everything else had to wait; they now let go straight away.

## 0.1.235 — 2026-10-12

- Sourcing's selling fees now follow your own sales. Once you have 30 recorded sales in the past year, the fee rate is what those sales actually paid, and it updates itself on every check. Typing a rate yourself switches this off; tick "From your recent sales" to turn it back on.
- The share of pieces you plan to sell now follows the sell-through rate Analytics shows for your last 12 months, once you have 30 sales. Typing a percentage yourself switches this off.
- Sourcing has a new "Most to pay per piece" limit under More options. A box is left out when its price plus shipping, divided by the pieces you can sell, is above it. Leave it empty for no limit.
- Sourcing's estimates are now checked against what you actually sell for. When your own sales of a kind of piece ran lower than the marketplace listings (yours: about half), marketplace prices are scaled down to match, and the page says so. Prices taken from your own sales are never scaled.
- Cost per piece is now charged on the pieces you plan to sell, in the plan and in the lower-sales test alike. Before, the plan charged it on every usable piece and the test only on sold ones, so the two disagreed. Break-even sales follow the same rule.
- Mixed-clothing and accessories boxes, which can't be searched piece by piece, are now priced from what your own sales of any kind sold for in the last 90 days.
- Each kind of piece uses its own sell-through from your sales and listings (blended toward your overall rate until there are 10 pieces), and Studio can recommend more than one box of a kind while the planned sales fit your monthly pace less the pieces you already have listed. Boxes of a kind you already hold plenty of are labelled as such.
- Sourcing researches more kinds of box per check (60) and starts with the kinds that unlock the most boxes.

## 0.1.234 — 2026-10-12

- Regenerating from the sidebar now opens a review first: each listing's photos (drag to reorder), SKU, COG, labels and measurements, filled in from what is saved, so you can check and fix them before anything is rewritten.

## 0.1.233 — 2026-10-12

- A listing's age now counts from its oldest live marketplace, so bulk-listing to one marketplace no longer makes items that are 60+ days old on the others look new in the stale filters, sorting and suggestions.

## 0.1.232 — 2026-10-12

- Skirts now have their own measurements (waist, hip, length) in Item Details and in the bulk upload measurement grid, and a folder with "skirt" in its name starts on Skirt.

## 0.1.231 — 2026-10-12

- Discard unsent edits from the editor header to put a listing back to exactly what Vendoo has, for example after regenerating by mistake.

## 0.1.230 — 2026-10-12

- Suggestions now flag an active listing as stale only once it has been up for 60 days or more. Listings between 30 and 59 days old no longer show up in the Suggestions list.

## 0.1.229 — 2026-10-11

- The browser now works from your phone. The Vendoo draft shows in a phone-sized layout that fills the screen instead of a shrunken desktop page, and you drive it with your finger: tap to press, drag to scroll.
- A new **Keyboard** button in the browser opens your phone's keyboard so you can type into the field you tapped.

## 0.1.228 — 2026-10-11

- Studio opens much faster on a phone or a slow connection. Everything it sends is now compressed, which cuts the first load and pages like Sourcing to roughly a quarter of the size.
- Opening Sourcing, Analytics, Marketing, the Assistant or Settings no longer shows an empty screen while the page arrives: it says "Loading…", and the pages are fetched ahead of time so a tap usually opens them straight away.
- Fixed Studio on a Mac re-checking every piece of the interface with the server each time it opened, instead of keeping what it already had.
- Sourcing finds sold prices again. It was getting none, because the AI search it relied on is blocked by eBay and Mercari. Prices now come from your own sales first, then eBay sold listings read through your connected Chrome, then Poshmark sold listings. Each box shows which of those its price came from.
- Sourcing asks for three things up front: budget, ZIP and minimum return. The selling window, your selling assumptions and Raghouse VIP moved under "More options", with shorter labels.

## 0.1.227 — 2026-10-10

- Sourcing leaves out reported sales that don't match the box: a different garment, a bundle or lot, or new with tags no longer count toward a box's resale estimate. Saved research is rechecked the same way.

## 0.1.226 — 2026-10-10

- The Assistant no longer fails with "Load failed" when your phone locks, you switch apps, or the connection drops while it is answering. Studio keeps writing the answer on its own, and the page reconnects and picks it up, including after you leave the Assistant and come back.
- Your question no longer shows twice while the Assistant is answering.
- Stop now stops the answer in Studio and keeps what was written so far.

## 0.1.225 — 2026-10-10

- The Assistant now knows more about each listing: its size, condition, colour, labels, SKU and which marketplaces it is listed on, so you can ask things like "which sizes sell fastest?" or "what is only on eBay?".
- It sees every time you changed an asking price in Studio, so it can tell you whether your price cuts are moving stock.
- New "About your business" note under the Assistant's message box. Write your goals, the profit you want per item, what you will not source, and it is kept in mind on every question.
- Listings the Assistant names are now links: click one to open it.
- The Assistant can look things up before it answers, including listing descriptions, each marketplace's fields, and listings that did not fit in a very large shop. You see "Looking up…" while it does. It still only reads.

## 0.1.224 — 2026-10-10

- After an update, a browser that had Studio open (your phone over Tailscale, for example) could keep showing the old interface against the new version, which is why PaperCrane was missing from the supplier cards. The page shell is now re-checked on every load, and an interface that is behind the backend reloads itself once.

## 0.1.223 — 2026-10-10

- New Assistant page: a chat about your business as a whole, separate from any listing's chat. Ask things like "which brands make me the most profit?", "what has sat longest and what should I do with it?" or "which boxes paid off?". Each question is answered from everything Studio holds right now: every listing, your sales and profit, the boxes you bought, the buy list, ad spend, sale events and sourcing checks.
- The Assistant only reads. It cannot change a listing or a price, and it never lists, delists or sends anything.

## 0.1.222 — 2026-10-10

- Sourcing now scouts PaperCrane (papercranewholesale.com), a marketplace of vetted US vintage sellers, alongside Raghouse and Thrift Vintage Fashion: every active Cream (A) and Standard (B) lot, with shipping estimated from the seller's state and card processing included, bought from the lot's own page.

## 0.1.221 — 2026-10-09

- Sourcing recommendations were impossible to get: the lower-sales test charged your per-piece operating costs on every piece in a box even in a scenario where half of them never sell, which ruled out every box in both stores, including ones with a 500% expected return. The test still assumes only half your planned sales at the lowest price seen, but now charges operating costs on those pieces only.
- When nothing qualifies, Sourcing now says how many boxes each check ruled out, so you can see what to change.

## 0.1.220 — 2026-10-09

- Fixes the Sourcing page failing with “Request failed: 500” after updating to 0.1.219: the buy list saved by the previous version is now discarded and rebuilt instead of being served to a page that cannot read it.
- Shipping estimates learn from your orders: record a box from the buy list, correct its shipping once the store charges it, and after two orders that store's estimates follow what it really charges. Thrift Vintage Fashion was still at the UPS list price.
- Sourcing tells you what Raghouse VIP would add to your buy list, so you can see whether the $64 a month pays for itself before joining.
- Boxes on sale show their discount next to the piece count.

## 0.1.219 — 2026-10-09

- Sourcing now prices boxes by the kind of piece inside them (“vintage graphic t-shirts”, “hawaiian shirts”) instead of by each box’s exact title, so research covers the whole catalog and far more boxes get a resale estimate. Your own recorded sales count as evidence for a kind of box, alongside what the AI finds sold on the web.
- The Sourcing page lists every box both stores have in stock, not just the top 80, and loads a box’s sales evidence when you open it. Your own sales open the listing in Studio.
- Studio posts a Mac notification when a box joins your buy list between checks.

## 0.1.218 — 2026-10-09

- Sourcing skips every Raghouse Recycle box and every Thrift Vintage Fashion A/B, B, B/C and C grade lot, so the "Include damaged and rework grades" setting is gone. Thrift Vintage Fashion brand mixes sold by weight, such as the J. Crew and American Eagle boxes, now show up with a piece count estimated from their shipping weight.

## 0.1.217 — 2026-10-09

- The sale calendar in Marketing now covers Sellwild. Plan a Sellwild sale or record one you ran, and its Sellwild sales, results, and best-days pattern show up next to eBay, Depop, and Etsy.

## 0.1.216 — 2026-10-09

- Facebook drafts now get their Package weight from the item's weight, and the Shipping carrier you picked on an earlier Facebook form. Color and size fields Facebook shows as optional are filled from the listing too.
- Vinted drafts now get Shoulder Width and Length from the measurements you type (pit to pit and length), and the Package Size you picked for a similar-weight item before. Until you've picked a carrier or package size once by hand in Vendoo, Studio leaves it for you and lists it as unfilled.
- Sellwild can now be filled from Studio, not just crosslisted from Vendoo. Turn it on in Settings → Listings, and Send fills its category, condition, package weight and size, and any category fields like the other marketplaces.

## 0.1.215 — 2026-10-09

- The bar at the top of the window is slimmer, so listings get more room.

## 0.1.214 — 2026-10-09

- Short-sleeve and unisex t-shirts no longer land in Casual Button-Down Shirts (or Pants & Shorts). Category picking now double-checks each marketplace's choice is the same kind of item, and searches again when none of the options fit.

## 0.1.213 — 2026-10-09

- Input, Forms and Fields and the browser button now sit in each listing's header beside Open listing and Regenerate, instead of up in the window's title bar.

## 0.1.212 — 2026-10-09

- Settings → Providers now opens with which AI is in use, above the Primary, Fallback and Photo analysis choices, so you can see what's running before you change it.

## 0.1.211 — 2026-10-09

- New Marketing section in the sidebar. The sale calendar, Discount deeper and the Ads tracker moved there from Analytics, so Analytics is just your sales and inventory. Pick the period for your ad totals right in the Ads section.

## 0.1.210 — 2026-10-09

- Open listing and Regenerate now sit at the top of each listing instead of above the tabs, so it's clear which listing they act on.

## 0.1.209 — 2026-10-09

- Choose Claude's photo model, listing model and reasoning in Settings → Providers. Each provider now keeps its own model choices in its own section, so you can pick the photo model for whichever AI reads your photos.
- Sign in with Claude now opens a small terminal right in Studio running Claude Code's sign-in, so you can see what it's asking and paste the code without leaving the app.

## 0.1.208 — 2026-10-09

- Analytics has a new Ads section for Poshmark Promoted Closet and Etsy Ads. Copy the spend from each dashboard for a week or a month, plus the clicks, orders, and sales it credits to the ads if you want them. Analytics then shows what you spent in the period, your profit after ads, return on ad spend, cost per click, and how much of each marketplace's sales went to ads.

## 0.1.207 — 2026-10-09

- You can now pick a separate AI for reading photos. Settings → Listing AI → Photo analysis chooses who reads your product photos (for example ChatGPT), while the Primary provider still writes the listing and answers chat. If the photo provider isn't set up, the listing AI reads the photos instead.

## 0.1.206 — 2026-10-09

- Sign in with your Claude account. Settings → Providers → Claude signs in through Claude Code with your Pro or Max plan, the way T3 Code does, and Claude can then write listings, read photos and look up sold comps. Choose it as Primary or Fallback under Listing AI. Needs Claude Code installed on this Mac.

## 0.1.205 — 2026-10-08

- Chat no longer hangs when several listings are busy at once. A message now shows its progress right away, even while Studio is still reading photos and researching prices, and a failed photo read ends the reply with an error you can retry instead of leaving it stuck. When Brave Search runs out of quota, price research stops retrying it for an hour, or until you save or test the key again.

## 0.1.204 — 2026-10-09

- When Cursor writes your listings, Settings → Models → Reasoning now lets you choose how hard the listing model thinks. The levels come from the model itself; higher takes longer and uses more Cursor usage.

## 0.1.203 — 2026-10-09

- Bulk uploads now happen in one window: put the photos in order, set the box, COG and labels, and type each item's SKU and measurements together before anything is created. Click a photo to enlarge it and read the tape, then choose Create and generate or Create drafts only.

## 0.1.202 — 2026-10-09

- Studio now fills in Grailed, Vinted and Facebook Marketplace, not just eBay, Etsy, Poshmark, Mercari and Depop. Turn them on in Settings → Marketplaces and each draft gets its category, condition and fields for them, with your brand as the Grailed designer.

## 0.1.201 — 2026-10-08

- Listings you imported from Vendoo before the unsent chip covered imports now get it too. Regenerating or editing one marks it unsent until you press Update Vendoo, and opening it no longer pulls Vendoo's older copy over your changes.

## 0.1.200 — 2026-10-08

- Sale suggestions now include a percentage off: the deepest discount, up to 30%, where every listing with a cost still makes your minimum profit. Plans cover all your listings on the marketplace, so there's nothing to pick, and fees and shipping fill in from your past year of sales. The plan lists any listings that would fall below your minimum or have no cost.

## 0.1.199 — 2026-10-08

- Sale suggestions now look back over the last year of sales instead of six months, so every season counts once and a real best day shows up sooner.

## 0.1.198 — 2026-10-08

- Until your sales show a clear best day, sale suggestions recommend a 7-day sale starting today. It covers every day and keeps your weekday pattern accurate while sales build, and the card switches to specific days once a real pattern shows up.

## 0.1.197 — 2026-10-08

- The "Shipping and buyer response" box is gone from the Input tab. You no longer see forms for packed weight or marketplace view counts, and listings generate the same as before.

## 0.1.196 — 2026-10-08

- Sale suggestions now pick however many days your sales history supports — one day, a weekend, or longer — instead of always two, and say whether the pattern is strong or may be chance. The Try button shows the full date range.

## 0.1.195 — 2026-10-08

- A listing with unsent edits now also shows under the Draft tab, so everything waiting on Update Vendoo is in one place. It still shows under Active while it is live.

## 0.1.194 — 2026-10-08

- A draft imported from Vendoo now shows the blue unsent chip as soon as you edit it, even before Studio has checked Vendoo, and that first check no longer overwrites your edit.

## 0.1.193 — 2026-10-07

- On a phone, the top bar no longer crams its buttons together: Queue is an icon like the others, and Workspace, Listing and Browser sit on their own row with full labels.

## 0.1.192 — 2026-10-07

- A listing you rename in the sidebar keeps that name when it saves, updates or regenerates.
- Settings → General → Listing names can show each listing by its SKU instead of its title.
- Sidebar search now finds listings by their labels too, alongside title and SKU.

## 0.1.191 — 2026-10-07

- Save Fabric Type as a supported Vendoo dropdown choice and keep petite eBay sizes paired correctly, including PL for petite large.

## 0.1.190 — 2026-10-07

- Follow clearer, numbered instructions for relisting after regenerating, with easier-to-read text and an “I've relisted” button to clear the reminder.

## 0.1.189 — 2026-10-07

- See all boxes Studio checked immediately, including when none are recommended. Supplier choices show how many boxes were found, and an empty recommendation explains when recent sold evidence is missing.

## 0.1.188 — 2026-10-07

- Plan wholesale purchases for when you expect to sell: adjust shipping and prep time, research upcoming seasonal themes, and use your recorded sales from the same calendar windows as context. Qualifying boxes that match the selling window get priority, with the same budget, recent-sales and return checks.

## 0.1.187 — 2026-10-07

- Send to Vendoo and Update Vendoo start from one click, without a preview dialog or automatically opening the browser pane. Follow progress in the editor and open Browse draft whenever you want to view it.

## 0.1.186 — 2026-10-07

- Let generation learn from your deliberate listing edits and preserve the Vendoo listing when a sale is first observed.
- Record measured packed shipping and dated marketplace views, impressions, offers and returns under Input → Shipping and buyer response, so future listings can use reliable examples.

## 0.1.185 — 2026-10-05

- Plan eBay, Depop, and Etsy sales on a calendar, try windows suggested by your sales history, check estimated item profits, and compare recorded event results with the same weekdays before the sale.

## 0.1.184 — 2026-10-05

- Generate listings with relevant recorded sales and similar unsold inventory in mind, while keeping your chosen price and current marketplace comps in view.
- Preserve photo evidence and uncertainty, and supply required fields and allowed choices earlier so generated listings need fewer corrections.

## 0.1.183 — 2026-10-05

- Source clothing with recent sold examples, current competition, adjustable selling costs, break-even sales, and a lower-sales profit check. Boxes with weak evidence or repair-heavy grades stay out of recommendations by default.

## 0.1.182 — 2026-10-05

- See when Analytics last synced with Vendoo, resync your data from the Analytics tab, and review reminders for sold items with missing sales details.

## 0.1.181 — 2026-10-04

- Stop repeated Ask chat repairs from clearing required listing values, keep unknown original prices blank without validation errors, and use the saved brand and department when repairing titles and eBay fields.

## 0.1.180 — 2026-10-05

- See your sell-through rate in Analytics and switch to a 7-day view with daily sales and a comparison to the previous week.

## 0.1.179 — 2026-10-04

- Keep jacket Outer Shell Material, Style, and other category details when saving Vendoo drafts. Fill applicable eBay optional fields, repair unsupported dropdown answers, and continue to later fields when earlier ones cannot be answered.

## 0.1.178 — 2026-10-04

- Bulk uploads now generate up to three listings at once. The queue shows progress for each listing, and stopping a batch lets active listings finish while the remaining drafts stay ungenerated.

## 0.1.177 — 2026-10-04

- Confirming Regenerate no longer stays on Saving when Studio reports being offline. A stalled price save, reset, or Open listing request shows an error so you can recover without restarting Studio.

## 0.1.176 — 2026-10-04

- Read Analytics more comfortably with wider sections, roomier totals, and a taller chart that keeps month labels visible instead of squeezing them together.

## 0.1.175 — 2026-10-04

- Switch freely between Input, Forms, and Fields after opening an imported Vendoo listing.

## 0.1.174 — 2026-10-04

- Switch sales charts between revenue, sales, and profit; see profit margins; rank marketplaces, categories, and brands by what matters to you; and review inventory cost and your oldest active listings in a clearer dashboard.

## 0.1.173 — 2026-10-04

- Analytics has a Discount deeper list: listings up 60 days or more, with how far to mark each one down in the next sale (35–40%) without dropping below what it cost you after fees.
- Add the Depop, eBay and Etsy sale events you join under Analytics → Sale events. Studio counts the sales that came in during each one, compares them with the weeks before and after, and labels those sales in Recent sales.

## 0.1.172 — 2026-10-04

- Ask chat remembers optional fields it deliberately leaves blank, including answers already saved in chat, so they stop coming back as missing.

## 0.1.171 — 2026-10-04

- Fields marked as not applicable stay cleared and no longer count toward Ask chat.

## 0.1.170 — 2026-10-04

- Ask chat now considers required fields, gaps reported when your Vendoo draft was created, and the latest saved-draft field checks to help finish missing values.

## 0.1.169 — 2026-10-04

- Etsy's When Made field now uses an educated date-range estimate when the exact production date is unknown, so missing dates no longer block a draft.

## 0.1.168 — 2026-10-04

- Backups take about a sixth of the disk space: each database snapshot is now compressed, and older uncompressed snapshots still restore.

## 0.1.167 — 2026-10-04

- The Fix errors and Ask chat buttons stay in view: the per-field fix list now sits below them and starts collapsed.

## 0.1.166 — 2026-10-04

- Generate and repair listings with GPT-6.1 Sol without the unsupported reasoning effort error.

## 0.1.165 — 2026-10-04

- Reach Fix errors and Ask chat for fields without scrolling through individual fields; expand error and marketplace field details only when you need them.

## 0.1.164 — 2026-10-04

- Rearrange each listing's photos in the bulk upload dialog before the drafts are created. Drag a photo to move it; the first one becomes the cover.

## 0.1.163 — 2026-10-04

- Studio uses much less CPU while it sits open. It only checks for updates every second or two while something is running (a send, a generation, a ChatGPT sign-in), slows down while it's behind another window, and catches up the moment you switch back.

## 0.1.162 — 2026-10-04

- Studio no longer makes up a SKU. A listing only gets a SKU when you type one in Item Details or the measurements popup; otherwise the SKU stays blank.

## 0.1.161 — 2026-10-04

- Check whether something is worth buying while you're in the store. Under Sourcing → Scout an item, take a photo of the item and its tag and type the asking price if there is one. Studio identifies it, looks up what it has sold for, and tells you Buy it, Maybe or Pass, or the most worth paying. It also works on your phone over Tailscale.
- Press **I bought it** to start a draft from the same photos, with the price you paid as its cost of goods. Every check is kept, and once a bought item sells you can see how close Studio's estimate was.

## 0.1.160 — 2026-10-04

- Keep track of the boxes you buy. Press **I bought this** on a buy-list box, or add one under Sourcing → Boxes you bought, and correct the price, shipping and piece count once you've paid. Choose the box when you bulk upload its photos, or later in Item Details.
- Each box shows what it cost with shipping, what its sales brought back after fees, how much of it has sold and how long pieces take to sell, with Raghouse and Thrift Vintage Fashion compared side by side.
- A listing from a box with no cost of goods typed uses the box's cost per piece, in Analytics and as Vendoo's Cost of Goods when you send.
- Once five pieces from a store's bought boxes have sold, the buy list compares what they sold for with what Studio estimated, and scales that store's resale estimates to match. The Sourcing page tells you how far off the estimates were.

## 0.1.159 — 2026-10-04

- Descriptions only mention flaws when an item has them. A flawless item no longer gets a "Flaws: none noted" line.

## 0.1.158 — 2026-10-04

- Update Vendoo now says "Reading the Vendoo draft…" while it reads the draft, instead of "Resolving marketplace categories…" for the whole wait.
- A Vendoo sync and an Update Vendoo on the same listing no longer run at the same time. The update waits for a sync that's already reading the draft, and no new sync starts until the update finishes.

## 0.1.157 — 2026-10-04

- Regenerate now keeps your measurements and flaws in the new description. Measurements written one per line all come over, not just the first, and the new description always shows your flaws and exact measurements instead of "See photos" or "none noted".

## 0.1.156 — 2026-10-04

- Descriptions no longer include doubts like "photo estimates" or "color is uncertain". Anything Studio couldn't confirm stays in its chat reply to you, and buyers never see it.

## 0.1.155 — 2026-10-04

- Update Vendoo no longer tells you to wait for generation when nothing is running, and a listing stuck on In Progress clears itself.

## 0.1.154 — 2026-10-04

- The Review Vendoo changes preview opens faster: Studio reads the current draft, the category fields and your labels at the same time instead of one after another.

## 0.1.153 — 2026-10-04

- The scrollbar under the open listing tabs is now a thin line that only shows when you hover over the tabs.

## 0.1.152 — 2026-10-03

- Jump straight to fields that need fixing, grouped by marketplace. Send progress shows completed photo uploads and elapsed time.
- Review the exact draft changes before approving Send or Update. Approval keeps the reviewed version, and a changed Vendoo draft requires another review.
- Compare earlier listing versions and restore one from History without changing anything in Vendoo.

## 0.1.151 — 2026-10-04

- You can type a SKU before a listing generates: there's a SKU box beside each item in the measurements popup after a bulk upload, and one in Item Details. Studio keeps the SKU you typed instead of making up its own, and if you change the SKU on a listing, Regenerate keeps your new one.

## 0.1.150 — 2026-10-04

- A listing no longer stays stuck generating forever when Cursor goes quiet after writing it. After five minutes of silence you now see a Retry message instead of an endless "thinking".

## 0.1.149 — 2026-10-04

- Start a new listing with the + at the end of your open listing tabs. The extra New listing button in the sidebar is gone.

## 0.1.148 — 2026-10-04

- After you start Regenerate on selected listings, the checkboxes go away right away instead of staying stuck until the run ends. Any listings that fail come back selected so you can retry them.

## 0.1.147 — 2026-10-04

- Keep multiple listings open in tabs, switch between them without losing your place, and close tabs without deleting listings.

## 0.1.146 — 2026-10-04

- Boys' and girls' pants no longer stop generation with "Could not find verified poshmark category candidates". Poshmark files kids' pants under Kids → Bottoms, and Studio now looks there.

## 0.1.145 — 2026-10-01

- Sending or updating a Vendoo draft verifies its saved fields directly, avoiding false Depop quantity and location errors.

## 0.1.144 — 2026-09-30

- Keep sizes such as IT 42 and One Size from repeating in listing titles. Reopening a listing removes repeated sizes, and correctly formatted titles pass validation.

## 0.1.143 — 2026-09-30

- Retry interrupted Vendoo sends without creating duplicate drafts or uploading the same photos again. Updates verify the saved fields before showing as synced and detect edits made in Vendoo during a save.
- Send drafts faster with concurrent category lookups, refreshed category options, and automatic retries for temporary read failures. Send timings are recorded in job events.

## 0.1.142 — 2026-09-30

- Compare sales with the previous period and open inventory age groups to review their listings. Analytics now shows missing sale prices and costs clearly, includes recorded $0 costs in profit, and excludes future-dated sales.

## 0.1.141 — 2026-09-30

- Compare combined, Raghouse-only, and Thrift Vintage Fashion buy lists for your sourcing budget, with shipping, budget remaining, and resale research links.

## 0.1.140 — 2026-09-30

- Find Duplicate Check in Settings → Listings. Queue is now the leftmost sidebar icon, and the Update button stays fully visible in a narrow sidebar.

## 0.1.139 — 2026-09-30

- Studio retries update downloads while a new Mac release is being uploaded. If the download remains unavailable, it tells you when to try again.

## 0.1.138 — 2026-09-29

- Send and Update reuse marketplace fields prepared during generation, and new sends upload three photos at a time so you spend less time waiting.
- See drafts being generated, batch rewrites, and Vendoo sends in Queue. Send to Vendoo adds your approved draft to the queue so you can keep working.

## 0.1.137 — 2026-09-30

- Check for Studio listings that share a Vendoo link from the listings sidebar, open each one to review it, and prevent linking a Vendoo item already used by another listing.

## 0.1.136 — 2026-09-30

- Listing generation searches sold items and active competition separately, looks for more evidence when results are thin, and avoids counting the same item twice or pricing from ended listings and unclear accepted offers.

## 0.1.135 — 2026-09-29

- When you regenerate several listings, you can drop the price first. Keep the current prices, take 10%, 15%, or 20% off each, or use each listing's own suggestion. The rewrite uses the new price. Nothing changes on Vendoo until you send.

## 0.1.134 — 2026-09-29

- A men's T-shirt category that came back stuck together, without the > between each level, is saved as the real men's T-shirts path.

## 0.1.133 — 2026-09-29

- Size 0 stays 0 on the marketplace forms. It no longer gets filled as 00.

## 0.1.132 — 2026-09-28

- Raghouse shipping on the buy list is FedEx, scaled to a checkout you paid. A 29 lb box to 70115 was estimated at $64 and FedEx charged $33.95.

## 0.1.131 — 2026-09-28

- After a bulk upload, Studio asks for measurements for the whole box on one screen. Each row shows that item's photos (use the arrows, or click to enlarge, to find the one with the tape). Type pit-to-pit, length and sleeve, or waist, rise, inseam and leg opening for pants, and press Tab or Enter to move to the next box. Leave a row blank, or choose **Continue without measurements**. Studio then generates every draft one by one and stops at a draft. Nothing is sent to Vendoo.
- Folders named jeans, pants or shorts start as Pants on the measurements screen.
- A bulk Regenerate keeps going when you collapse the sidebar.

## 0.1.130 — 2026-09-27

- The sidebar control for rewriting several listings is now **Select**. Check the ones you want in Suggestions or in the list, and Studio rewrites them one by one. Measurements, flaws, cost, labels, notes, and the price stay. Nothing changes on Vendoo until you send.

## 0.1.129 — 2026-09-27

- You can rewrite several listings at once. In the sidebar, choose **Regenerate**, check the listings, and Studio rewrites them one by one from their photos and item details. Measurements, flaws, cost, labels, notes, and the price stay. Nothing changes on Vendoo until you send.

## 0.1.128 — 2026-09-27

- Sold comps no longer include listings that are still for sale. A "1 sold" count on a multi-quantity listing, an installment amount ("4 payments of $11.17") or a shipping charge ("$5.50 Standard Shipping") is no longer read as a sale, and a brand only matches when its words are in the listing's own title.

## 0.1.127 — 2026-09-27

- **Regenerate** no longer starts a sold comps search on its own. Click **Search sold comps** in the price dialog when you want one.

## 0.1.126 — 2026-09-27

- **Regenerate** no longer gets stuck on "Clearing chat and generated fields…". Clearing no longer waits on Chrome for your label names, and the rewrite starts as soon as the listing is cleared.

## 0.1.125 — 2026-09-27

- **Open listing** no longer hangs on "Opening…" until you quit Studio. When Chrome is slow, Studio stops waiting on it sooner, and if the Chrome extension doesn't open the listing within a few seconds, Studio opens it in Chrome itself.

## 0.1.124 — 2026-09-27

- **Unsent edits** now clears on listings that got stuck with it even though nothing was changed. Studio compares what the listing says with what Vendoo last had, so tidying sizes and dropdowns no longer counts as an edit.

## 0.1.123 — 2026-09-27

- The Sourcing page really does reach Raghouse and Thrift Vintage Fashion now. The last fix only covered part of the app, so the stores' certificates were still being rejected.

## 0.1.122 — 2026-09-27

- A listing no longer shows **Unsent edits** just because Studio pulled Vendoo's copy and you opened it. The chip now means you changed something that Vendoo doesn't have yet.

## 0.1.121 — 2026-09-27

- Sold comps no longer take a price from a listing's title. A seller who writes "$58" in the title of a top now selling for $23.20 used to show up as a $58 sale; a price written in the title is now ignored.

## 0.1.120 — 2026-09-27

- The Sourcing page can reach Raghouse and Thrift Vintage Fashion again. The Mac app was rejecting their security certificates, so every update came back with no boxes.

## 0.1.119 — 2026-09-27

- Similar listings still for sale now cap your price. When three or more are live, the new listing is priced at or below their median asking price unless yours is clearly better, and price-drop suggestions follow the same cap. That still works when only one or two sold listings turned up.

## 0.1.118 — 2026-09-27

- New Sourcing page (the box icon beside Analytics) keeps a buy list of wholesale clothing boxes ready. Every 6 hours Studio checks Raghouse and Thrift Vintage Fashion, looks up what the pieces resell for with your listing AI's web search, and picks the boxes expected to at least double your money within your budget. Each store gets an Open cart button with the boxes already in it; you check the cart and pay. Studio never buys anything.
- Set the ZIP the boxes ship to, and switch back to a recent ZIP in one tap. Shipping is estimated from each store's warehouse to that ZIP.

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
