# Changelog

Every change to List This Studio, newest first. Studio bumps its patch version
on each merged pull request, so a version here is one change. The app reads this
file: Settings → General → About → What's new.

Entry format: `## <version> — <YYYY-MM-DD>` followed by bullets.

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
