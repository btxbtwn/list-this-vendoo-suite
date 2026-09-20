// Create and read Vendoo items the way Vendoo's own form does, from Studio.
//
// Vendoo's create-item form never fills anything: it uploads photos through
// the inventory microservice, mints a Firestore id, and calls the "items"
// Cloud Function with {type: "createItem", payload: {item}}. These helpers give
// Studio that same path, so a generated listing is stored as data with every
// marketplace section exactly as computed. See docs/vendoo-listing-architecture.md.
//
// Auth is the user's Firebase session. The ID token lives in localStorage on
// web.vendoo.co (read once in the page's MAIN world); every other call runs
// from the service worker with a Bearer header, no cookies needed.
//
// Listing and delisting go through Vendoo's own backend, which holds the
// seller's marketplace connections — no marketplace tab is ever opened. Both
// are reachable only from a Studio route the seller triggers by hand.

const VENDOO_API_BASE = 'https://api.web.vendoo.co';
const VENDOO_MSVC_BASE = 'https://us.vendoo.co';
const VENDOO_FUNCTIONS_BASE = 'https://us-central1-vendoo-prod-7948f.cloudfunctions.net';
const VENDOO_FIRESTORE_BASE = 'https://firestore.googleapis.com/v1/projects/vendoo-prod-7948f/databases/(default)/documents';
const VENDOO_TOKEN_REFRESH_URL = 'https://securetoken.googleapis.com/v1/token';
const VENDOO_APP_URL = 'https://web.vendoo.co/app/';
const VENDOO_TOKEN_MIN_TTL_MS = 5 * 60 * 1000;
// Where the signed-in session is kept between calls. Reading it from a page
// needs a web.vendoo.co tab; refreshing it needs only the refresh token, so
// caching that is what lets Studio work with Vendoo closed.
const VENDOO_SESSION_KEY = 'vendoo_session';
const VENDOO_REQUEST_TIMEOUT_MS = 60000;

// Firestore auto-ids: 20 chars from this alphabet. Vendoo mints the item id
// client-side with collection.doc().id before calling createItem.
const FIRESTORE_ID_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';

function vendooFirestoreId() {
  const bytes = new Uint8Array(20);
  crypto.getRandomValues(bytes);
  let out = '';
  for (const byte of bytes) out += FIRESTORE_ID_ALPHABET[byte % FIRESTORE_ID_ALPHABET.length];
  return out;
}

// Runs in the page: the only thing we need from web.vendoo.co is the Firebase
// session. Self-contained on purpose (executeScript serializes it).
// Vendoo persists auth in IndexedDB (firebaseLocalStorageDb); older builds also
// used localStorage. Check both so a signed-in tab is never reported as logged out.
async function readVendooSessionInPage() {
  const fromUser = (raw, key) => {
    if (!raw || !raw.uid) return null;
    const sts = raw.stsTokenManager || {};
    return {
      ok: true,
      uid: String(raw.uid),
      email: raw.email || null,
      api_key: raw.apiKey || (key ? String(key).split(':')[2] : null) || null,
      access_token: sts.accessToken || null,
      refresh_token: sts.refreshToken || null,
      expiration_time: Number(sts.expirationTime) || 0,
    };
  };

  const withTimeout = (promise, ms, label) => Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
    }),
  ]);

  // Live Firebase app on the page (fastest, avoids IndexedDB locks).
  // Wait briefly for auth restore — a just-opened /app/ shell often has no
  // currentUser until Firebase finishes reading its persistence layer.
  try {
    const auth = window.firebase?.auth?.();
    if (auth) {
      let user = auth.currentUser;
      if (!user) {
        user = await withTimeout(new Promise((resolve) => {
          const unsub = auth.onAuthStateChanged((u) => {
            unsub();
            resolve(u);
          });
        }), 5000, 'firebase.onAuthStateChanged');
      }
      if (user?.uid) {
        const access_token = await user.getIdToken();
        const refresh_token = user.refreshToken || null;
        return {
          ok: true,
          uid: String(user.uid),
          email: user.email || null,
          api_key: auth.app?.options?.apiKey || null,
          access_token,
          refresh_token,
          expiration_time: Date.now() + 55 * 60 * 1000,
        };
      }
    }
  } catch (err) {
    /* fall through */
  }

  try {
    for (const key of Object.keys(localStorage)) {
      if (!key.startsWith('firebase:authUser:')) continue;
      const session = fromUser(JSON.parse(localStorage.getItem(key) || 'null'), key);
      if (session) return session;
    }
  } catch (err) {
    /* fall through to IndexedDB */
  }

  try {
    const db = await withTimeout(new Promise((resolve, reject) => {
      const req = indexedDB.open('firebaseLocalStorageDb');
      req.onerror = () => reject(req.error || new Error('indexedDB open failed'));
      req.onblocked = () => reject(new Error('indexedDB open blocked'));
      req.onsuccess = () => resolve(req.result);
    }), 8000, 'indexedDB.open');
    if (![...db.objectStoreNames].includes('firebaseLocalStorage')) {
      db.close();
      return { ok: false, error: 'Not signed in to Vendoo in this Chrome profile' };
    }
    // Prefer a cursor over getAll — this store can be large enough that getAll hangs.
    const rows = await withTimeout(new Promise((resolve, reject) => {
      const tx = db.transaction('firebaseLocalStorage', 'readonly');
      const store = tx.objectStore('firebaseLocalStorage');
      const req = store.openCursor();
      const found = [];
      req.onerror = () => reject(req.error || new Error('indexedDB cursor failed'));
      req.onsuccess = () => {
        const cursor = req.result;
        if (!cursor) {
          resolve(found);
          return;
        }
        const row = cursor.value;
        const key = String(row?.fbase_key || cursor.key || '');
        if (key.startsWith('firebase:authUser:')) {
          found.push(row);
          resolve(found);
          return;
        }
        cursor.continue();
      };
    }), 8000, 'indexedDB.cursor');
    db.close();
    for (const row of rows) {
      const key = String(row?.fbase_key || '');
      if (!key.startsWith('firebase:authUser:')) continue;
      const value = row?.value;
      const raw = typeof value === 'string' ? JSON.parse(value) : value;
      const session = fromUser(raw, key);
      if (session) return session;
    }
  } catch (err) {
    return { ok: false, error: `Could not read the Vendoo session: ${err.message}` };
  }
  return { ok: false, error: 'Not signed in to Vendoo in this Chrome profile' };
}

async function closeBlockingVendooItemTabs() {
  // Crashed /item/ error pages (Elzzlzss etc.) share the origin and can leave
  // IndexedDB blocked for every other Vendoo tab in the profile.
  const tabs = await chrome.tabs.query({ url: ['https://web.vendoo.co/app/item/*', 'https://app.vendoo.co/app/item/*'] });
  for (const tab of tabs) {
    if (!tab.id) continue;
    try {
      await chrome.tabs.remove(tab.id);
    } catch (err) {
      /* tab already gone */
    }
  }
}

async function findOrOpenVendooTab() {
  await closeBlockingVendooItemTabs();
  // Always open a fresh app shell for auth reads after clearing item tabs.
  const opened = await openVisibleVendooWindow(VENDOO_APP_URL, null, { foreground: true });
  if (!opened.tabId) throw new Error('Could not open a Vendoo tab');
  await waitForTabComplete(opened.tabId, 30000);
  await new Promise((resolve) => setTimeout(resolve, 2500));
  return opened.tabId;
}

async function loadCachedVendooSession() {
  try {
    const stored = await chrome.storage.local.get(VENDOO_SESSION_KEY);
    const session = stored?.[VENDOO_SESSION_KEY];
    return session && session.uid && session.refresh_token ? session : null;
  } catch (err) {
    return null;
  }
}

async function cacheVendooSession(session) {
  if (!session?.uid || !session?.refresh_token) return session;
  try {
    await chrome.storage.local.set({ [VENDOO_SESSION_KEY]: session });
  } catch (err) {
    /* a cache that will not write is not worth failing the call over */
  }
  return session;
}

async function clearCachedVendooSession() {
  try {
    await chrome.storage.local.remove(VENDOO_SESSION_KEY);
  } catch (err) {
    /* nothing to do */
  }
}

async function readVendooSession() {
  const tabId = await findOrOpenVendooTab();
  let lastError = 'No Vendoo session in the page';
  for (let attempt = 0; attempt < 3; attempt++) {
    const [execution] = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: readVendooSessionInPage,
    });
    const session = execution?.result;
    if (session?.ok) return session;
    lastError = session?.error || lastError;
    // Firebase may still be restoring auth from IndexedDB after a hard reload.
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  throw new Error(lastError);
}

async function refreshVendooToken(session) {
  if (!session.refresh_token || !session.api_key) return session;
  const res = await fetch(`${VENDOO_TOKEN_REFRESH_URL}?key=${encodeURIComponent(session.api_key)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: session.refresh_token }),
  });
  if (!res.ok) throw new Error(`Vendoo session refresh returned ${res.status}`);
  const data = await res.json();
  return {
    ...session,
    access_token: data.id_token,
    refresh_token: data.refresh_token || session.refresh_token,
    expiration_time: Date.now() + Number(data.expires_in || 3600) * 1000,
  };
}

function tokenIsFresh(session) {
  return Boolean(session?.access_token)
    && (session.expiration_time - Date.now()) >= VENDOO_TOKEN_MIN_TTL_MS;
}

// A signed-in session, without opening Vendoo when it can be helped.
//
// The cached refresh token mints ID tokens on its own, so once this Chrome
// profile has signed in to Vendoo, creating, editing, listing and delisting
// all run with no Vendoo tab anywhere. A tab is read only to bootstrap the
// first session, or when the refresh token stops working — the seller having
// signed out, or Firebase having revoked it.
async function freshVendooSession() {
  const cached = await loadCachedVendooSession();
  if (tokenIsFresh(cached)) return cached;
  if (cached) {
    try {
      return await cacheVendooSession(await refreshVendooToken(cached));
    } catch (err) {
      // Refusing to refresh means this session is done; fall back to the page.
      await clearCachedVendooSession();
    }
  }

  let session = await readVendooSession();
  if (!tokenIsFresh(session)) {
    session = await refreshVendooToken(session);
  }
  if (!session.access_token) throw new Error('Vendoo session has no ID token; sign in to Vendoo again');
  return cacheVendooSession(session);
}

async function vendooFetch(url, { method = 'GET', token, json, body, headers = {}, responseType = 'json', timeoutMs } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs || VENDOO_REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method,
      credentials: 'include',
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : body,
    });
    let data = null;
    if (responseType === 'json') {
      const text = await res.text();
      try { data = JSON.parse(text); } catch (err) { data = text; }
    }
    return { ok: res.ok, status: res.status, data };
  } finally {
    clearTimeout(timer);
  }
}

function vendooError(prefix, result) {
  const detail = result?.data && typeof result.data === 'object'
    ? (result.data.error?.message || result.data.message || JSON.stringify(result.data).slice(0, 300))
    : String(result?.data || '').slice(0, 300);
  return `${prefix} returned ${result?.status}${detail ? `: ${detail}` : ''}`;
}

// Photos: ask the inventory service for a signed PUT, send the bytes, and keep
// the storage path. The item then references {version: 3, id: imagePath}.
async function uploadVendooPhoto(session, photo) {
  const extension = String(photo.extension || 'jpg').toLowerCase();
  const slot = await vendooFetch(`${VENDOO_MSVC_BASE}/inventory/v1/images/url`, {
    method: 'POST', token: session.access_token, json: { fileExtension: extension },
  });
  if (!slot.ok || !slot.data?.url || !slot.data?.imagePath) throw new Error(vendooError('Vendoo image slot', slot));
  const source = await fetch(photo.url);
  if (!source.ok) throw new Error(`Fetching photo ${photo.id || photo.url} returned ${source.status}`);
  const bytes = await source.blob();
  const put = await vendooFetch(slot.data.url, {
    method: 'PUT',
    body: bytes,
    headers: { 'Content-Type': photo.mime_type || bytes.type || 'image/jpeg' },
    responseType: 'none',
    timeoutMs: 120000,
  });
  if (!put.ok) throw new Error(vendooError('Vendoo image upload', put));
  return {
    version: 3,
    id: slot.data.imagePath,
    originalMaxDimension: Number(photo.max_dimension) || 0,
  };
}

async function readVendooSubscriptionVersion(session) {
  // The form passes the subscription version alongside createItem; it lives on
  // the user's subscription document.
  const doc = await vendooFetch(
    `${VENDOO_FIRESTORE_BASE}/users/${encodeURIComponent(session.uid)}/subscription/details`,
    { token: session.access_token },
  );
  const fields = doc.ok && doc.data && doc.data.fields ? doc.data.fields : null;
  const version = fields && (fields.version?.stringValue || fields.version?.integerValue || fields.current?.mapValue?.fields?.version?.stringValue);
  return version != null ? String(version) : null;
}

async function createVendooItem(session, item, subscriptionVersion) {
  const call = await vendooFetch(`${VENDOO_FUNCTIONS_BASE}/items`, {
    method: 'POST',
    token: session.access_token,
    json: { data: { type: 'createItem', payload: { item, subscriptionVersion } } },
    timeoutMs: 90000,
  });
  if (!call.ok || (call.data && call.data.error)) throw new Error(vendooError('Vendoo createItem', call));
  return call.data?.result ?? call.data;
}

async function getVendooItem(session, itemId) {
  const params = new URLSearchParams({
    useMarketplaceImages: 'true',
    isMultiQuantityItemsEnabled: 'true',
    userId: session.uid,
  });
  const res = await vendooFetch(`${VENDOO_API_BASE}/api/item/${encodeURIComponent(itemId)}?${params}`, {
    token: session.access_token,
  });
  if (!res.ok) throw new Error(vendooError(`GET /api/item/${itemId}`, res));
  const data = res.data;
  return (data && (data.item || data.data)) || data;
}

// Every field one category leaf renders, for any marketplace. This is what
// Vendoo's own forms call after a category is chosen, so it covers the
// category-dependent optional fields too. Each entry carries
// rules.fieldOptions (minValues -> required, maxValues -> multi-select,
// selectionMode -> dropdown vs free text) and its coded options.
//
// ``p`` is the ancestor id chain and the extras are spread as query params,
// both taken from overrides.categoryV2 — the reason that object has to be
// stored whole.
async function getVendooCategorySpecifics(session, call) {
  const parts = [];
  const path = Array.isArray(call.path) ? call.path.filter((id) => String(id || '').trim()) : [];
  if (path.length) parts.push(`p=${encodeURIComponent(path.join(','))}`);
  const extras = call.extras && typeof call.extras === 'object' ? call.extras : {};
  for (const [key, value] of Object.entries(extras)) {
    if (value === undefined || value === null || value === '') continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  const query = parts.length ? `?${parts.join('&')}` : '';
  const marketplace = encodeURIComponent(call.marketplace_id || 'ebay');
  const category = encodeURIComponent(call.category_id);
  const res = await vendooFetch(
    `${VENDOO_API_BASE}/api/category/specifics/${marketplace}/category/${category}${query}`,
    { token: session.access_token },
  );
  if (!res.ok) throw new Error(vendooError(`GET category specifics ${call.category_id}`, res));
  return { specifics: res.data };
}

// The size vocabulary one category offers: ``values`` are the sizes and
// ``scales`` the size types, both as {label, value} with the coded value the
// form stores. The general form is marketplace ``vendoo``.
async function queryVendooSizes(session, call) {
  const res = await vendooFetch(`${VENDOO_API_BASE}/api/rest/v1/size/query`, {
    method: 'POST',
    token: session.access_token,
    json: { categoryId: call.category_id, marketplace: call.marketplace_id || 'vendoo' },
  });
  if (!res.ok) throw new Error(vendooError(`size query ${call.category_id}`, res));
  return { sizes: res.data };
}

// Vendoo's own mapping from a general category to a marketplace's. Its forms
// use this, so one good general choice settles every marketplace instead of
// each being guessed separately. ``reverse`` goes the other way.
async function mapVendooCategory(session, call) {
  const general = call.general_category || {};
  const path = Array.isArray(general.path) ? general.path : [];
  const displayPath = Array.isArray(general.displayPath) ? general.displayPath : [];
  const source = call.source_marketplace_id || 'vendoo';
  const country = call.country_code || 'US';
  // Shape the mapper expects (Vendoo's fromV2Category).
  const generalCategory = {
    id: general.id,
    doc_id: [source, general.id].join(':'),
    marketplace_id: source,
    parent_category_id: path.slice(0, -1).pop() || '__root',
    all_category_label: displayPath,
    last_subcategory_label: general.displayName || '',
    completion_text: displayPath.join(' '),
    most_relevant_text: general.displayName || '',
    parent_category_id_path: path.slice(0, -1),
    searchable_text: path.slice(0, -1),
    is_leaf: Boolean(general.isLeaf),
    has_children: Boolean(general.hasChildren),
    country_code: country,
    status: 'active',
  };
  const params = new URLSearchParams({
    user_id: session.uid,
    marketplace_id: call.marketplace_id,
    general_category_marketplace_id: source,
    country_code: country,
    // axios JSON-encodes nested params; match that.
    general_category: JSON.stringify(generalCategory),
  });
  const route = call.reverse ? 'reverse' : 'mapper';
  const res = await vendooFetch(`${VENDOO_API_BASE}/api/category/${route}?${params}`, {
    token: session.access_token,
  });
  if (!res.ok) throw new Error(vendooError(`category ${route} ${call.marketplace_id}`, res));
  return { match: res.data?.match || null, recommendations: res.data?.recommendations || [] };
}

// Vendoo lists server-side for marketplaces it has an API connection to, and
// through its own extension for the rest. Either way this one call does it.
async function listVendooItem(session, call) {
  const marketplaces = Array.isArray(call.marketplaces) ? call.marketplaces.filter(Boolean) : [];
  if (!marketplaces.length) throw new Error('Listing needs at least one marketplace');
  const res = await vendooFetch(`${VENDOO_API_BASE}/api/item/${encodeURIComponent(call.item_id)}/list`, {
    method: 'POST',
    token: session.access_token,
    json: { marketplaces, flags: call.flags || {} },
    timeoutMs: 180000,
  });
  if (!res.ok) throw new Error(vendooError(`list ${call.item_id}`, res));
  return { result: res.data };
}

async function delistVendooItem(session, call) {
  const marketplaces = Array.isArray(call.marketplaces) ? call.marketplaces.filter(Boolean) : [];
  if (!marketplaces.length) throw new Error('Delisting needs at least one marketplace');
  const res = await vendooFetch(`${VENDOO_API_BASE}/api/item/${encodeURIComponent(call.item_id)}/delist`, {
    method: 'POST',
    token: session.access_token,
    json: { marketplaces, userId: session.uid },
    timeoutMs: 180000,
  });
  if (!res.ok) throw new Error(vendooError(`delist ${call.item_id}`, res));
  return { result: res.data };
}

// Firestore's REST shape for one value. Vendoo stores numbers as strings, so
// only the types its documents actually carry are handled.
function firestoreValue(value) {
  if (value === null || value === undefined) return { nullValue: null };
  if (typeof value === 'boolean') return { booleanValue: value };
  if (typeof value === 'number') {
    return Number.isInteger(value) ? { integerValue: String(value) } : { doubleValue: value };
  }
  if (Array.isArray(value)) {
    return { arrayValue: { values: value.map(firestoreValue) } };
  }
  if (typeof value === 'object') {
    const fields = {};
    for (const [key, inner] of Object.entries(value)) fields[key] = firestoreValue(inner);
    return { mapValue: { fields } };
  }
  return { stringValue: String(value) };
}

// The inverse of ``firestoreValue``: Vendoo's inventory lives in Firestore, so
// one paged listing of users/{uid}/items returns every item document whole and
// there is no need for an /api/item call per listing.
function firestorePlain(value) {
  if (!value || typeof value !== 'object') return null;
  if ('nullValue' in value) return null;
  if ('booleanValue' in value) return Boolean(value.booleanValue);
  if ('integerValue' in value) return Number(value.integerValue);
  if ('doubleValue' in value) return Number(value.doubleValue);
  if ('timestampValue' in value) return String(value.timestampValue);
  if ('stringValue' in value) return String(value.stringValue);
  if ('bytesValue' in value) return String(value.bytesValue);
  if ('referenceValue' in value) return String(value.referenceValue);
  if ('geoPointValue' in value) return value.geoPointValue;
  if ('arrayValue' in value) return (value.arrayValue?.values || []).map(firestorePlain);
  if ('mapValue' in value) return firestoreFields(value.mapValue?.fields);
  return null;
}

function firestoreFields(fields) {
  const out = {};
  for (const [key, value] of Object.entries(fields || {})) out[key] = firestorePlain(value);
  return out;
}

function firestoreItem(doc) {
  const id = String(doc?.name || '').split('/').pop();
  if (!id) return null;
  return { ...firestoreFields(doc?.fields), id, itemID: id };
}

// One page of the seller's inventory. Studio drives the paging so it can import
// each page as it arrives instead of holding the whole inventory in one message;
// ``ids_only`` masks the documents down to their ids for a cheap first count.
async function listVendooItems(session, call) {
  const pageSize = Math.min(Math.max(Number(call.page_size) || 50, 1), 300);
  const params = new URLSearchParams({ pageSize: String(pageSize) });
  if (call.page_token) params.set('pageToken', String(call.page_token));
  if (call.ids_only) params.append('mask.fieldPaths', 'id');
  const url = `${VENDOO_FIRESTORE_BASE}/users/${encodeURIComponent(session.uid)}/items?${params}`;
  const res = await vendooFetch(url, { token: session.access_token, timeoutMs: 60000 });
  if (!res.ok) throw new Error(vendooError('list items', res));
  const items = (res.data?.documents || []).map(firestoreItem).filter(Boolean);
  return { items, next_page_token: res.data?.nextPageToken || '' };
}

// A field path segment is quoted unless it is a plain identifier — category
// aspect keys like ``53159_Size Type`` carry spaces and start with a digit.
function firestorePathSegment(segment) {
  return /^[A-Za-z_][A-Za-z_0-9]*$/.test(segment) ? segment : `\`${segment.replace(/`/g, '\\`')}\``;
}

function firestoreFieldPath(path) {
  return String(path).split('.').map(firestorePathSegment).join('.');
}

// Edit an item the way Vendoo's own form does: a Firestore update of just the
// fields that changed, so nothing else in the document is disturbed.
async function updateVendooItem(session, call) {
  const updates = call.updates && typeof call.updates === 'object' ? call.updates : {};
  const paths = Object.keys(updates);
  if (!paths.length) return { updated: [] };

  // Firestore wants the value nested under the path's first segment, with the
  // full path in the mask.
  const fields = {};
  for (const [path, value] of Object.entries(updates)) {
    const [head, ...rest] = String(path).split('.');
    if (!rest.length) {
      fields[head] = firestoreValue(value);
      continue;
    }
    let node = fields[head] || (fields[head] = { mapValue: { fields: {} } });
    for (let i = 0; i < rest.length - 1; i += 1) {
      const part = rest[i];
      const parent = node.mapValue.fields;
      node = parent[part] || (parent[part] = { mapValue: { fields: {} } });
    }
    node.mapValue.fields[rest[rest.length - 1]] = firestoreValue(value);
  }

  const params = new URLSearchParams();
  for (const path of paths) params.append('updateMask.fieldPaths', firestoreFieldPath(path));
  const url = `${VENDOO_FIRESTORE_BASE}/users/${encodeURIComponent(session.uid)}`
    + `/items/${encodeURIComponent(call.item_id)}?${params}`;
  const res = await vendooFetch(url, {
    method: 'PATCH',
    token: session.access_token,
    json: { fields },
  });
  if (!res.ok) throw new Error(vendooError(`update ${call.item_id}`, res));
  return { updated: paths };
}

// An item's ``labels`` are ids into users/{uid}/labels, not names — the form
// shows only chips whose id it finds there. Match names the way Vendoo does
// (trimmed, case-insensitive) and create any that are missing, as picking
// "Create" in the label box would. An id passed in (a pulled item) is kept.
const VENDOO_LABEL_COLOR = '#4852e8';

async function listVendooLabels(session) {
  const base = `${VENDOO_FIRESTORE_BASE}/users/${encodeURIComponent(session.uid)}/labels`;
  const labels = [];
  let pageToken = '';
  do {
    const params = new URLSearchParams({ pageSize: '300' });
    if (pageToken) params.set('pageToken', pageToken);
    const res = await vendooFetch(`${base}?${params}`, { token: session.access_token });
    if (!res.ok) throw new Error(vendooError('list labels', res));
    for (const doc of res.data?.documents || []) {
      const id = String(doc.name || '').split('/').pop();
      const name = doc.fields?.name?.stringValue || '';
      if (id) labels.push({ id, name });
    }
    pageToken = res.data?.nextPageToken || '';
  } while (pageToken);
  return labels;
}

async function resolveVendooLabels(session, call) {
  const names = Array.isArray(call.names) ? call.names : [];
  const existing = await listVendooLabels(session);
  const byName = new Map(existing.map((label) => [label.name.trim().toLowerCase(), label.id]));
  const ids = new Set(existing.map((label) => label.id));
  const out = [];
  const created = [];
  for (const raw of names) {
    const name = String(raw || '').trim();
    if (!name) continue;
    let id = ids.has(name) ? name : byName.get(name.toLowerCase());
    if (!id) {
      id = vendooFirestoreId();
      const url = `${VENDOO_FIRESTORE_BASE}/users/${encodeURIComponent(session.uid)}/labels/${id}`;
      const res = await vendooFetch(url, {
        method: 'PATCH',
        token: session.access_token,
        json: {
          fields: {
            id: { stringValue: id },
            name: { stringValue: name },
            color: { stringValue: VENDOO_LABEL_COLOR },
            createdAt: { timestampValue: new Date().toISOString() },
          },
        },
      });
      if (!res.ok) throw new Error(vendooError(`create label ${name}`, res));
      byName.set(name.toLowerCase(), id);
      ids.add(id);
      created.push(name);
    }
    if (!out.includes(id)) out.push(id);
  }
  return { ids: out, created };
}

// Vendoo deletes an item by removing its Firestore document; there is no API
// call for it. Irreversible, so Studio only sends this when asked by name.
async function deleteVendooItem(session, call) {
  const url = `${VENDOO_FIRESTORE_BASE}/users/${encodeURIComponent(session.uid)}`
    + `/items/${encodeURIComponent(call.item_id)}`;
  const res = await vendooFetch(url, { method: 'DELETE', token: session.access_token });
  if (!res.ok) throw new Error(vendooError(`delete ${call.item_id}`, res));
  return { deleted: call.item_id };
}

async function searchVendooCategory(session, call) {
  const res = await vendooFetch(`${VENDOO_API_BASE}/api/category/search`, {
    method: 'POST',
    token: session.access_token,
    json: {
      text: call.text,
      country_code: call.country_code || 'US',
      marketplace_id: call.marketplace_id || 'ebay',
      type: call.type,
      additionalMultiMatchSearchParams: { noSearch: true },
    },
  });
  if (!res.ok) throw new Error(vendooError('Vendoo category search', res));
  const hits = res.data?.hits?.hits || [];
  return {
    leaf: hits.find((entry) => entry?._source?.is_leaf === true)?._source || null,
    matches: hits.map((entry) => entry?._source).filter(Boolean),
  };
}

// One Studio message, a list of ops, one reply. Studio sequences the calls it
// needs (probe, upload, create, verify); this only executes them in order and
// stops at the first failure so Studio sees exactly where it broke.
async function runVendooApiOps(ops) {
  const session = await freshVendooSession();
  const results = [];
  for (const op of ops) {
    try {
      switch (op.op) {
        case 'session':
          results.push({ op: 'session', ok: true, uid: session.uid, email: session.email });
          break;
        case 'new_item_id':
          results.push({ op: 'new_item_id', ok: true, item_id: vendooFirestoreId() });
          break;
        case 'subscription':
          results.push({ op: 'subscription', ok: true, version: await readVendooSubscriptionVersion(session) });
          break;
        case 'upload_photo':
          results.push({ op: 'upload_photo', ok: true, photo_id: op.photo?.id || null, image: await uploadVendooPhoto(session, op.photo || {}) });
          break;
        case 'create_item':
          results.push({ op: 'create_item', ok: true, result: await createVendooItem(session, op.item, op.subscription_version ?? null) });
          break;
        case 'list_items':
          results.push({ op: 'list_items', ok: true, ...(await listVendooItems(session, op)) });
          break;
        case 'get_item':
          results.push({ op: 'get_item', ok: true, item_id: op.item_id, item: await getVendooItem(session, op.item_id) });
          break;
        case 'category_search':
          results.push({ op: 'category_search', ok: true, ...(await searchVendooCategory(session, op)) });
          break;
        case 'resolve_labels':
          results.push({ op: 'resolve_labels', ok: true, ...(await resolveVendooLabels(session, op)) });
          break;
        case 'delete_item':
          results.push({ op: 'delete_item', ok: true, ...(await deleteVendooItem(session, op)) });
          break;
        case 'update_item':
          results.push({ op: 'update_item', ok: true, item_id: op.item_id, ...(await updateVendooItem(session, op)) });
          break;
        case 'list_item':
          results.push({ op: 'list_item', ok: true, item_id: op.item_id, ...(await listVendooItem(session, op)) });
          break;
        case 'delist_item':
          results.push({ op: 'delist_item', ok: true, item_id: op.item_id, ...(await delistVendooItem(session, op)) });
          break;
        case 'category_map':
          results.push({
            op: 'category_map',
            ok: true,
            marketplace_id: op.marketplace_id,
            ...(await mapVendooCategory(session, op)),
          });
          break;
        case 'size_query':
          results.push({
            op: 'size_query',
            ok: true,
            category_id: op.category_id,
            ...(await queryVendooSizes(session, op)),
          });
          break;
        case 'category_specifics':
          results.push({
            op: 'category_specifics',
            ok: true,
            category_id: op.category_id,
            ...(await getVendooCategorySpecifics(session, op)),
          });
          break;
        default:
          throw new Error(`Unknown Vendoo API op: ${op.op}`);
      }
    } catch (err) {
      results.push({ op: op.op, ok: false, error: String(err && err.message ? err.message : err) });
      return { ok: false, uid: session.uid, results };
    }
    if (op.throttle_ms) await new Promise((resolve) => setTimeout(resolve, op.throttle_ms));
  }
  return { ok: true, uid: session.uid, results };
}

function replyVendooApi(msg, payload) {
  const request = msg.payload || {};
  send({
    version: 1,
    type: 'job.vendoo_api_result',
    job_id: msg.job_id || request.job_id || null,
    message_id: request.request_id || Date.now().toString(36),
    sent_at: new Date().toISOString(),
    payload: { ...payload, request_id: request.request_id || null },
  });
}

async function handleVendooApiMessage(msg) {
  const payload = msg.payload || {};
  const ops = Array.isArray(payload.ops) ? payload.ops : [];
  if (!ops.length) {
    replyVendooApi(msg, { ok: false, error: 'job.vendoo_api needs ops', results: [] });
    return;
  }
  try {
    replyVendooApi(msg, await runVendooApiOps(ops));
  } catch (err) {
    replyVendooApi(msg, { ok: false, error: String(err && err.message ? err.message : err), results: [] });
  }
}
