# How Vendoo lists, and what we should copy

Findings from reading Vendoo Crosslist Extension v3.1.10 and the `web.vendoo.co`
app bundle, 2026-09-18. Recovered source is in `research/` (gitignored — this
repo is public and that code is Vendoo's).

This exists because of the AGENTS.md principle: *study how established products
solve the problem before designing a solution.* Vendoo has been doing this for
years across a dozen marketplaces. Their architecture answers questions we are
currently answering worse.

---

## 1. What Vendoo actually does

### The extension is not where the logic lives

Vendoo's extension contains almost no marketplace knowledge. It is a generic
remote-controlled executor. All selectors, endpoints, headers and payload shapes
arrive from Vendoo's server at runtime.

The control loop (`source/src/serviceWorker/queue/`):

1. `chrome.alarms` fires every 5 minutes
2. `POST https://api.vendoo.co/api/rest/v1/auto/pull` with a device id → server returns `instructions[]`
3. execute each instruction in a tab
4. `POST /api/rest/v1/auto/notify` with the result

The entire server command set is seven verbs:

```
EXEC_PAGE_SCRIPT  WEB_REQUEST  GET_COOKIES  INTERCEPT_REQUEST_BODY
EVENT_SUBSCRIBE   TRACE        PING
```

and `EXEC_PAGE_SCRIPT` carries a twelve-primitive action language:

```
click  setInput  fireEvent  hover  wait  waitForElement
uploadImages  getFromStorage  sendRequest  renderModal  removeModal
mercariList   ← the only marketplace-specific action in the codebase
```

**This is the single most important thing to copy.** When Poshmark renames a
field, Vendoo edits a server config. No extension rebuild, no Chrome Web Store
review, no user update. Our extension hardcodes selectors per marketplace in
`vendoo-extension/content-scripts/*.js`, so every marketplace change is a
release. Theirs is data; ours is code.

### Three listing strategies, not one

**a. Private API replay** — Poshmark, Depop, Mercari, Grailed, Vinted, Kidizen,
Tradesy, Vestiaire, Facebook.

The extension opens a tab on the marketplace origin and calls that site's own
internal API using the user's logged-in session. `dist/corsRules.json` uses
`declarativeNetRequest` to rewrite `Origin` and `Referer` to the real
create-listing page and force `Access-Control-Allow-Origin: *` on responses, so
the browser permits the call.

| | Endpoint | Auth | Create flow |
|---|---|---|---|
| Poshmark | `poshmark.com/vm-rest` | `jwt` cookie | `POST /users/{id}/posts` → media scratch upload → `POST /posts/{id}/status/published` |
| Depop | `webapi.depop.com/api` | `access_token` cookie | `POST /v1/products/` |
| Mercari | `mercari.com/v1/api` (GraphQL) | `x-csrf-token` + Bearer from page | `uploadTempListingPhotos` → `createListing` |

Mercari also has an Android-app impersonation path against
`api-double.mercariapp.com/v1` (`x-platform: android`, `x-app-release: 7.95.1`,
protobuf), presumably a fallback.

GraphQL persisted-query hashes are server-delivered, spread into the request
body from a `config` object, with a source comment saying they should be pulled
from Firebase. Mercari rotates those hashes; Vendoo follows without shipping a
build.

**b. DOM automation** — Etsy. No Etsy API endpoint appears anywhere in the 5.4 MB
bundle. Etsy is driven entirely by server-sent `click`/`setInput`/`uploadImages`
/`waitForElement` actions against the seller UI.

**c. The official API** — eBay only.
`source/marketplaces/src/ebay/api/constants.ts` has a real OAuth2 client id,
`identity/v1/oauth2/token`, the Trading API at `ws/api.dll`, and full production
scopes (`sell.inventory`, `sell.account`, `sell.fulfillment`, `sell.marketing`).
The OAuth flow runs server-side. eBay listings are created by Vendoo's backend
holding a partner token — the browser is not involved. The codebase has an
`isAPIMarketplace()` predicate that forks on exactly this.

### Vendoo's own API

The `web.vendoo.co` app (Vite build, unminified paths readable) talks to
`api.web.vendoo.co` over a conventional REST API:

```
GET   /api/item/{itemId}?useMarketplaceImages&isMultiQuantityItemsEnabled&userId
GET   /api/item/items-by-listing-ids
POST  /api/item/{itemId}/list          body: { marketplaces: [...], flags, ...opts }
POST  /api/item/{itemId}/delist
POST  /api/rest/v1/import/items        body: { marketplaceId, marketplaceUserId, itemIds: [...] }
POST  /api/rest/v1/import/items_normalized
                                       body: { marketplaceId, marketplaceUserId, items: [normalized] }
PUT   /api/rest/v1/item/{itemId}/merge
POST  /api/rest/v1/item/{itemId}/status
```

Auth is Firebase session cookies (`credentials: 'include'`), the same session a
signed-in browser already holds. We already call `GET /api/item/{id}` in
`vendoo-extension/background/vendoo-item.js`, which proves the session approach
works from a content script.

`items_normalized` is the important one: it accepts fully-formed item objects
rather than marketplace ids to scrape. It is how Vendoo's own importer creates
items in bulk.

### Bulk import never touches the Vendoo form

Worth stating plainly, because it is the strongest argument for Plan A: when
Vendoo imports your existing Poshmark closet, nothing types into a Vendoo form.
`bulkImport({chunk, marketplaceUserID})` forks three ways:

1. **API marketplaces (eBay)** — `POST /api/rest/v1/import/items` with
   `{marketplaceId, marketplaceUserId, itemIds}`. Vendoo's backend calls eBay,
   normalizes, writes. The browser is not involved.
2. **MSVC** — Poshmark behind a flag, delegated to a microservice as
   `{msvcImportBody: {itemIds, marketplaceAccount: {id, marketplace}}}`.
3. **Extension marketplaces** — per item: fetch from the marketplace's private
   API (`getItem`), convert with a per-marketplace `toVendoo()` mapper, collect
   into an array; then **one** `POST /api/rest/v1/import/items_normalized` for
   the whole chunk.

Per-item normalization is:

```js
const raw        = await handler.getItem({item, connection});
const vendooItem = await handler.toVendoo({marketplaceItemData: raw.marketplaceItem});
vendooItem.generalDetails.images = await uploadImagesFromURL({images: vendooItem.generalDetails.images});
return vendooItem;
```

Three details we should copy rather than rediscover:

- **Images live at `generalDetails.images`**, not a top-level key, and every URL
  goes through `POST /api/static/upload` first so the stored item points at
  Vendoo's storage and not a marketplace CDN.
- **A hard 1500 ms wait between item fetches**, and `assertNotImportedItem`
  dedupes *before* fetching, not after.
- The importer UI caps at `queueLimit: 5`, `selectedItemsLimit: 10`.

`toVendoo()` is ordinary per-marketplace mapping code. Our
`vendoo_api.vendoo_item_from_listing()` is the same function with our generated
listing standing in where `getItem` would be.

---

## 2. Plan A — drive Vendoo through its own API

**Problem today.** `vendoo-extension/content-scripts/vendoo.js` types into
Vendoo's React form: 50–500 ms sleeps, two retries, dropdown option matching,
parallel-fill heuristics. Every field is a chance to mis-select a category,
silently drop a tag, or race a re-render. That is the accuracy ceiling we keep
hitting.

**Fix.** Stop filling the form. `POST /api/rest/v1/import/items_normalized` with
the item we already have, from a content script on `web.vendoo.co` so the
Firebase session cookie rides along. No selectors, no sleeps, no dropdown
matching — the values we computed are the values stored.

This does not break the AGENTS.md invariant. It creates Vendoo items; it does
not call `/api/item/{id}/list`, so nothing reaches a marketplace and a human
still reviews and publishes in Vendoo.

**The open risk.** `items_normalized` is built for items that came *from* a
marketplace: its body carries `marketplaceId` and `marketplaceUserId`, and
Vendoo's `MARKETPLACES` list is

```
API:       ebay etsy whatnot sellhound sellwild vestiaireApi shopify
EXTENSION: mercari grailed poshmark facebook depop tradesy kidizen vestiaire vinted
```

`"vendoo"` is not in it — it is the default `origin` Vendoo's new-item factory
stamps on an item created in the app. So the import endpoint may reject a
net-new item, and manually-created items may be written straight to Firestore by
the web app rather than through REST, which would explain why no plain
`POST /api/item` create endpoint appears in the bundle.

The probe answers this in one call. If import rejects `origin: "vendoo"`, the
fallback is the shape Vendoo's own factory builds, which we already mirror in
`vendoo_api.wrap_item()`:

```js
{origin: "vendoo", version: 10, status: {notSaved: true}, type: "item",
 userID: "", itemID: "", labels: [], generalDetails: {...}, listings: {...}}
```

**The other unknown** is the exact normalized item schema. It is discoverable
without guessing: `GET /api/item/{id}` returns items in that shape, and
`vendoo-item.js` already names the top-level keys —

```
generalDetails  listings  images  statuses  overrides
marketplaceSpecifics  categorySpecifics
```

**Steps.**

1. **Schema probe.** Add a Studio job that reads N existing items of the user's
   own via `GET /api/item/{id}`, unions their shapes, and writes an observed
   schema into the existing catalog index (`vendoo_studio.services.catalog_index`
   already materializes observed schemas — this is a new source, not a new
   subsystem).
2. **Serializer.** Map our listing model to that schema. This is the real work
   and it is ordinary mapping code, testable offline against captured fixtures.
3. **Writer.** New extension action that POSTs to `items_normalized` and returns
   the created item ids. Round-trip verify with `GET /api/item/{id}` and diff
   against what we sent — an accuracy check the form path can never give us.
4. **Keep the form path** behind a flag until the diff is clean on real items.

**Expected result.** Category and dropdown selection stop being fuzzy matching
problems. Fill time drops from seconds-per-field to one request per batch.
Failures become HTTP errors with messages instead of "element not found".

---

## 3. Plan B — list to marketplaces directly

Recreating what Vendoo does for Poshmark / Depop / Mercari / Etsy, cutting
Vendoo out.

**Architecture — copy theirs, do not invent.** The lesson from their codebase is
that the fragile parts must be data, not code:

- A generic action language (their twelve primitives) executed by a thin extension.
- Per-marketplace request recipes as **config**, served by Studio's local server,
  not hardcoded in content scripts.
- A session/token extractor per marketplace (cookie name, storage key, CSRF header).
- `declarativeNetRequest` rules for `Origin`/`Referer`/CORS, per their `corsRules.json`.
- Round-trip verification after every create.

**Per marketplace.**

| | Approach | Draft state? |
|---|---|---|
| eBay | Official API, OAuth2, `sell.inventory` bulk endpoints (25/call) — the only clean path; do this server-side in Studio | Yes, unpublished offers |
| Etsy | Official API v3, `createDraftListing`, one call per listing | Yes, native drafts |
| Poshmark | `vm-rest` replay: create post → upload media → *stop before* `status/published` | Yes, if we don't publish |
| Depop | `webapi.depop.com` replay | Draft support needs verifying |
| Mercari | GraphQL `createListing` replay | **No — `createListing` goes live immediately** |

**eBay and Etsy should not be reverse-engineered at all.** Both have real APIs we
can sign up for, and Vendoo itself uses the official API for eBay rather than
scraping it. That is a strong signal. Etsy needs a Personal App approved, then
Commercial Access if other sellers ever use this.

**The honest cost.** Vendoo's whole design — server-delivered selectors,
server-delivered GraphQL hashes, an Android fallback, a twelve-verb action
language — exists because these private APIs break constantly and they cannot
afford a Web Store review on the critical path. Driving Vendoo means we inherit
their break-fixing for free. Going direct means we own it, for four
marketplaces, permanently. That is the trade, and it is not primarily a
technical one.

**Two things to settle before building this.**

1. **The invariant.** AGENTS.md says automation must never publish; it stops at
   saved drafts. Mercari's `createListing` has no draft state — it publishes.
   Poshmark drafts only exist if we deliberately skip the publish call. Going
   direct on Mercari means either changing the invariant or not supporting
   Mercari.
2. **Terms of service.** Poshmark, Mercari and Depop all prohibit automated
   access. Today the marketplaces only ever see Vendoo, and Vendoo carries that
   risk. Going direct moves the risk onto our users' accounts.

---

## 3b. What is built (2026-09-18)

Both paths now have a first layer in the tree.

**Plan A — Vendoo API**
- `services/vendoo_api.py`: endpoint map, `observe_item_schema`, inverse
  serializer `vendoo_item_from_listing`, `wrap_item` (new-item envelope),
  `diff_roundtrip`.
- `vendoo-extension/background/vendoo-api.js`: `get_item`, `upload_images`,
  `import_normalized`, `category_search` from a signed-in tab.
- Not yet wired: the Studio job that runs the probe and persists the observed
  schema. That is where a live session is required.

**Plan B — direct marketplace listing** (`docs/marketplace-recipes.md`)
- `vendoo-extension/background/marketplace-request.js`: the one generic
  primitive — a cookie-bearing request with `form-data` / `blob` /
  `form-urlencoded` transforms, plus a `cookies` op. Zero marketplace logic.
- `vendoo-extension/corsRules.json` + manifest: `declarativeNetRequest`
  Origin/Referer rewrites per marketplace, limited to `xmlhttprequest`.
- `services/marketplace_bridge.py`: `marketplace.request` / `marketplace.result`
  round trip over the existing extension WebSocket.
- `services/marketplace_recipes/{poshmark,depop,mercari}.py`: pure request and
  body builders plus an orchestrator each. Marketplace codes (condition,
  colour, size, category ids) are consumed from `<marketplace>_specifics`
  pre-resolved; any bare label is returned as an `UnresolvedField`, never
  guessed.
- **Publish gate.** Poshmark lists as a real draft and skips
  `status/published` unless `publish=True`. Depop and Mercari have no draft
  state, so their `list_item` raises `PublishNotAllowed` unless the job opts
  in explicitly. This implements "decide later" on the invariant without
  blocking the build.
- Not yet wired: a Studio route/job that chooses a marketplace and calls
  `list_item`; category/condition/size id resolvers per marketplace (the
  Vendoo `/api/category/search` path from Plan A is the obvious source);
  Mercari persisted-query capture.

## 4. Recommended order

1. **Plan A now.** It is a strict accuracy improvement, conflicts with nothing,
   and is mostly ordinary mapping code.
2. **eBay and Etsy official APIs next**, server-side in Studio. Real APIs, real
   drafts, no ToS exposure, and eBay's bulk endpoints are genuinely good.
3. **Poshmark / Depop / Mercari replay last, if at all** — and only after the
   invariant and ToS questions above are answered deliberately.
