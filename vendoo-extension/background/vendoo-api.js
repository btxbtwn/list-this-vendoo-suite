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
const VENDOO_PHOTO_CONCURRENCY = 3;
const VENDOO_PHOTO_CACHE_LIMIT = 500;
const VENDOO_PHOTO_CACHE_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const vendooPhotoUploads = new Map();
let vendooPhotoCacheWrite = Promise.resolve();
let vendooSessionRequest = null;

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
  const url = `${VENDOO_TOKEN_REFRESH_URL}?key=${encodeURIComponent(session.api_key)}`;
  const started = Date.now();
  let status = null;
  let ok = false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), VENDOO_REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: session.refresh_token }),
    });
    status = res.status;
    ok = res.ok;
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const error = new Error(`Vendoo session refresh returned ${res.status}`);
      error.invalidSession = ['TOKEN_EXPIRED', 'USER_DISABLED', 'USER_NOT_FOUND', 'INVALID_REFRESH_TOKEN']
        .includes(data.error?.message);
      throw error;
    }
    const data = await res.json();
    return {
      ...session,
      access_token: data.id_token,
      refresh_token: data.refresh_token || session.refresh_token,
      expiration_time: Date.now() + Number(data.expires_in || 3600) * 1000,
    };
  } finally {
    clearTimeout(timer);
    noteVendooApiCall({ method: 'POST', url, status, ok, durationMs: Date.now() - started });
  }
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
async function loadFreshVendooSession(rejectedToken = null) {
  const cached = await loadCachedVendooSession();
  if (tokenIsFresh(cached) && cached.access_token !== rejectedToken) return cached;
  if (cached) {
    try {
      return await cacheVendooSession(await refreshVendooToken(cached));
    } catch (err) {
      if (!err.invalidSession) throw err;
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

async function freshVendooSession(rejectedToken = null) {
  if (!vendooSessionRequest) {
    vendooSessionRequest = loadFreshVendooSession(rejectedToken).finally(() => { vendooSessionRequest = null; });
  }
  return vendooSessionRequest;
}

// A request line for Settings → Logs. Query strings carry API keys and signed
// upload URLs, so only the host and path are kept. Bodies and tokens never are.
function vendooApiLogEntry({ method, url, status, ok, durationMs, at } = {}) {
  let host = '';
  let path = '/';
  try {
    const parsed = new URL(String(url || ''));
    host = String(parsed.host || '').slice(0, 120);
    path = String(parsed.pathname || '/').slice(0, 300) || '/';
  } catch (err) {
    host = '';
    path = '/';
  }
  const verb = String(method || 'GET').toUpperCase().slice(0, 8);
  const code = Number.isFinite(status) ? status : null;
  let error = null;
  if (!ok) error = code == null ? 'timed out' : `HTTP ${code}`;
  return {
    at: at || new Date().toISOString(),
    method: verb,
    host,
    path,
    status: code,
    duration_ms: Math.max(0, Math.round(Number(durationMs) || 0)),
    ok: Boolean(ok),
    error,
  };
}

function noteVendooApiCall(fields) {
  if (typeof recordVendooApiLog !== 'function') return;
  try {
    recordVendooApiLog(vendooApiLogEntry(fields));
  } catch (err) {
    /* a log line must never fail the Vendoo call it describes */
  }
}

async function vendooFetch(url, options = {}) {
  const safe = options.retrySafe === true || ['GET', 'HEAD'].includes(options.method || 'GET');
  const deadline = Date.now() + (options.timeoutMs || VENDOO_REQUEST_TIMEOUT_MS);
  let authRetried = false;
  for (let attempt = 0; ; attempt += 1) {
    let result;
    try {
      result = await vendooFetchOnce(url, { ...options, timeoutMs: Math.max(1, deadline - Date.now()) });
      if (safe && result.status === 401 && options.token && !authRetried && attempt < 2) {
        authRetried = true;
        const session = await freshVendooSession(options.token);
        options = { ...options, token: session.access_token };
        continue;
      }
      if (!safe || ![408, 429, 500, 502, 503, 504].includes(result.status)) return result;
    } catch (err) {
      if (!safe || attempt >= 2 || Date.now() >= deadline) throw err;
    }
    if (attempt >= 2) return result;
    const delay = result?.retryAfterMs ?? Math.floor(Math.random() * (500 * (2 ** attempt)));
    if (delay >= deadline - Date.now()) {
      if (result) return result;
      throw new Error('Vendoo read timed out');
    }
    await new Promise((resolve) => setTimeout(resolve, delay));
  }
}

async function vendooFetchOnce(url, { method = 'GET', token, json, body, headers = {}, responseType = 'json', timeoutMs } = {}) {
  const controller = new AbortController();
  const started = Date.now();
  const timer = setTimeout(() => controller.abort(), timeoutMs || VENDOO_REQUEST_TIMEOUT_MS);
  let status = null;
  let ok = false;
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
    status = res.status;
    ok = res.ok;
    let data = null;
    if (responseType === 'json') {
      const text = await res.text();
      try { data = JSON.parse(text); } catch (err) { data = text; }
    } else if (responseType === 'blob') {
      data = await res.blob();
    }
    const retryAfter = res.headers?.get('Retry-After');
    const retryAfterMs = retryAfter == null ? null : (
      /^\d+(?:\.\d+)?$/.test(retryAfter)
        ? Number(retryAfter) * 1000 : Math.max(0, Date.parse(retryAfter) - Date.now())
    );
    return { ok: res.ok, status: res.status, data, retryAfterMs: Number.isFinite(retryAfterMs) ? retryAfterMs : null };
  } finally {
    clearTimeout(timer);
    noteVendooApiCall({ method, url, status, ok, durationMs: Date.now() - started });
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
  const source = await vendooFetch(photo.url, { responseType: 'blob' });
  if (!source.ok) throw new Error(`Fetching photo ${photo.id || ''} returned ${source.status}`);
  const bytes = source.data;
  const digest = await crypto.subtle.digest('SHA-256', await bytes.arrayBuffer());
  const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  const cacheKey = `vendoo_photo_uploads:${session.uid}`;
  const photoKey = `${hash}:${extension}`;
  const flightKey = `${cacheKey}:${photoKey}`;
  const stored = await chrome.storage.local.get(cacheKey);
  const cached = stored?.[cacheKey]?.[photoKey];
  const dimension = Number(photo.max_dimension) || 0;
  if (cached?.image?.id && Date.now() - cached.at < VENDOO_PHOTO_CACHE_TTL_MS) {
    return { ...cached.image, originalMaxDimension: dimension };
  }
  if (!vendooPhotoUploads.has(flightKey)) {
    const upload = uploadVendooPhotoBytes(session, photo, bytes, extension).then(async (image) => {
      // Serialize read/modify/write so concurrent uploads cannot erase one
      // another. Cache only completed PUTs, bounded by count and age.
      const write = vendooPhotoCacheWrite.catch(() => {}).then(async () => {
        const latest = await chrome.storage.local.get(cacheKey);
        const entries = { ...(latest?.[cacheKey] || {}), [photoKey]: { image, at: Date.now() } };
        const retained = Object.entries(entries)
          .filter(([, entry]) => Date.now() - entry.at < VENDOO_PHOTO_CACHE_TTL_MS)
          .sort((a, b) => b[1].at - a[1].at)
          .slice(0, VENDOO_PHOTO_CACHE_LIMIT);
        await chrome.storage.local.set({ [cacheKey]: Object.fromEntries(retained) });
      });
      vendooPhotoCacheWrite = write;
      await write;
      return image;
    }).finally(() => vendooPhotoUploads.delete(flightKey));
    vendooPhotoUploads.set(flightKey, upload);
  }
  return { ...await vendooPhotoUploads.get(flightKey), originalMaxDimension: dimension };
}

async function uploadVendooPhotoBytes(session, photo, bytes, extension) {
  const slot = await vendooFetch(`${VENDOO_MSVC_BASE}/inventory/v1/images/url`, {
    method: 'POST', token: session.access_token, json: { fileExtension: extension },
  });
  if (!slot.ok || !slot.data?.url || !slot.data?.imagePath) throw new Error(vendooError('Vendoo image slot', slot));
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
  if (item.userID !== session.uid) throw new Error('The Vendoo account changed during Send. Sign in to the original account and retry.');
  const call = await vendooFetch(`${VENDOO_FUNCTIONS_BASE}/items`, {
    method: 'POST',
    token: session.access_token,
    json: { data: { type: 'createItem', payload: { item, subscriptionVersion } } },
    timeoutMs: 90000,
  });
  if (!call.ok || (call.data && call.data.error)) throw new Error(vendooError('Vendoo createItem', call));
  return call.data?.result ?? call.data;
}

async function getVendooItem(session, itemId, { allowMissing = false, withVersion = false, raw = false } = {}) {
  let version = null;
  if (withVersion || raw) {
    // Read the version before the API snapshot. A concurrent edit during
    // either read then makes the subsequent conditional PATCH fail safely.
    const doc = await vendooFetch(
      `${VENDOO_FIRESTORE_BASE}/users/${encodeURIComponent(session.uid)}/items/${encodeURIComponent(itemId)}`,
      { token: session.access_token },
    );
    if (allowMissing && doc.status === 404) return null;
    if (!doc.ok || !doc.data?.updateTime) throw new Error(vendooError('Read draft version', doc));
    version = doc.data.updateTime;
    // PATCH writes Firestore fields. The item API reshapes category specifics
    // and defaults, so it cannot prove those exact fields were retained.
    if (raw) {
      const item = firestoreFields(doc.data.fields, true);
      return withVersion ? { ...item, _studio_update_time: version } : item;
    }
  }
  const params = new URLSearchParams({
    useMarketplaceImages: 'true',
    isMultiQuantityItemsEnabled: 'true',
    userId: session.uid,
  });
  const res = await vendooFetch(`${VENDOO_API_BASE}/api/item/${encodeURIComponent(itemId)}?${params}`, {
    token: session.access_token,
  });
  if (allowMissing && res.status === 404) return null;
  if (!res.ok) throw new Error(vendooError(`GET /api/item/${itemId}`, res));
  const data = res.data;
  const item = (data && (data.item || data.data)) || data;
  return withVersion ? { ...item, _studio_update_time: version } : item;
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
    retrySafe: true,
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
    // GET /api/item returns Firebase Timestamp instances as their JSON shape.
    // A direct REST update must put them back as Firestore timestamps, not as
    // ordinary {_seconds, _nanoseconds} maps. Vendoo uses these stamps to tell
    // that each marketplace form has been saved.
    const seconds = Number(value._seconds);
    const nanoseconds = Number(value._nanoseconds || 0);
    if (
      Number.isInteger(seconds)
      && Number.isInteger(nanoseconds)
      && nanoseconds >= 0
      && nanoseconds < 1_000_000_000
    ) {
      const wholeSecond = new Date(seconds * 1000).toISOString().replace(/\.\d{3}Z$/, '');
      return { timestampValue: `${wholeSecond}.${String(nanoseconds).padStart(9, '0')}Z` };
    }
    const fields = {};
    for (const [key, inner] of Object.entries(value)) fields[key] = firestoreValue(inner);
    return { mapValue: { fields } };
  }
  return { stringValue: String(value) };
}

// The inverse of ``firestoreValue``: Vendoo's inventory lives in Firestore, so
// one paged listing of users/{uid}/items returns every item document whole and
// there is no need for an /api/item call per listing.
function firestorePlain(value, timestampObjects = false) {
  if (!value || typeof value !== 'object') return null;
  if ('nullValue' in value) return null;
  if ('booleanValue' in value) return Boolean(value.booleanValue);
  if ('integerValue' in value) return Number(value.integerValue);
  if ('doubleValue' in value) return Number(value.doubleValue);
  if ('timestampValue' in value) {
    const timestamp = String(value.timestampValue);
    if (!timestampObjects) return timestamp;
    // Match Firebase Timestamp JSON used by the form payload, retaining all
    // nine fractional digits instead of rounding through JavaScript dates.
    const fraction = timestamp.match(/\.(\d+)/)?.[1] || '';
    return {
      _seconds: Math.floor(Date.parse(timestamp) / 1000),
      _nanoseconds: Number(fraction.padEnd(9, '0')),
    };
  }
  if ('stringValue' in value) return String(value.stringValue);
  if ('bytesValue' in value) return String(value.bytesValue);
  if ('referenceValue' in value) return String(value.referenceValue);
  if ('geoPointValue' in value) return value.geoPointValue;
  if ('arrayValue' in value) return (value.arrayValue?.values || []).map((part) => firestorePlain(part, timestampObjects));
  if ('mapValue' in value) return firestoreFields(value.mapValue?.fields, timestampObjects);
  return null;
}

function firestoreFields(fields, timestampObjects = false) {
  const out = {};
  for (const [key, value] of Object.entries(fields || {})) out[key] = firestorePlain(value, timestampObjects);
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
  if (call.expected_update_time) params.set('currentDocument.updateTime', call.expected_update_time);
  const url = `${VENDOO_FIRESTORE_BASE}/users/${encodeURIComponent(session.uid)}`
    + `/items/${encodeURIComponent(call.item_id)}?${params}`;
  const res = await vendooFetch(url, {
    method: 'PATCH',
    token: session.access_token,
    json: { fields },
  });
  if ([409, 412].includes(res.status) || res.data?.error?.status === 'FAILED_PRECONDITION') {
    throw new Error('The Vendoo draft changed during this save. Refresh it and review your changes before trying again.');
  }
  if (!res.ok) throw new Error(vendooError(`update ${call.item_id}`, res));
  return { updated: paths, update_time: res.data?.updateTime || null };
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
    retrySafe: true,
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

const VENDOO_READ_OPS = new Set([
  'get_item', 'category_search', 'category_map', 'category_specifics', 'size_query',
  'list_labels', 'list_items', 'subscription',
]);
const VENDOO_READ_CONCURRENCY = 3;

async function runVendooRead(session, op) {
  switch (op.op) {
    case 'get_item':
      return { item_id: op.item_id, item: await getVendooItem(session, op.item_id, {
        allowMissing: op.allow_missing === true, withVersion: op.with_version === true,
        raw: op.raw === true,
      }) };
    case 'category_search': return searchVendooCategory(session, op);
    case 'category_map': return { marketplace_id: op.marketplace_id, ...await mapVendooCategory(session, op) };
    case 'category_specifics': return { category_id: op.category_id, ...await getVendooCategorySpecifics(session, op) };
    case 'size_query': return { category_id: op.category_id, ...await queryVendooSizes(session, op) };
    case 'list_labels': return { labels: await listVendooLabels(session) };
    case 'list_items': return listVendooItems(session, op);
    case 'subscription': return { version: await readVendooSubscriptionVersion(session) };
    default: throw new Error(`Unknown Vendoo read: ${op.op}`);
  }
}

// One Studio message, a list of ops, one reply. Studio sequences the calls it
// needs (probe, upload, create, verify). Independent photo uploads run in small
// batches, in result order; every batch settles before any dependent write.
// A failed upload stops the sequence before the draft can be created.
async function runVendooApiOps(ops, onProgress = () => {}) {
  const session = await freshVendooSession();
  const results = [];
  const totalPhotos = ops.filter((op) => op.op === 'upload_photo').length;
  let completedPhotos = 0;
  if (totalPhotos) onProgress({ completed: 0, total: totalPhotos });
  for (let index = 0; index < ops.length; index += 1) {
    const op = ops[index];
    if (VENDOO_READ_OPS.has(op.op)) {
      const batch = [op];
      while (!op.throttle_ms && batch.length < VENDOO_READ_CONCURRENCY
        && VENDOO_READ_OPS.has(ops[index + batch.length]?.op)
        && !ops[index + batch.length].throttle_ms) {
        batch.push(ops[index + batch.length]);
      }
      const reads = await Promise.all(batch.map(async (call) => {
        try {
          return { op: call.op, ok: true, ...await runVendooRead(session, call) };
        } catch (err) {
          return { op: call.op, ok: false, error: String(err.message || err) };
        }
      }));
      results.push(...reads);
      if (reads.some((result) => !result.ok)) return { ok: false, uid: session.uid, results };
      index += batch.length - 1;
      if (op.throttle_ms) await new Promise((resolve) => setTimeout(resolve, op.throttle_ms));
      continue;
    }
    if (op.op === 'upload_photo' && !op.throttle_ms) {
      const batch = [];
      while (batch.length < VENDOO_PHOTO_CONCURRENCY
        && ops[index + batch.length]?.op === 'upload_photo'
        && !ops[index + batch.length].throttle_ms) {
        batch.push(ops[index + batch.length]);
      }
      const uploaded = await Promise.all(batch.map(async (call) => {
        try {
          const image = await uploadVendooPhoto(session, call.photo || {});
          completedPhotos += 1;
          onProgress({ completed: completedPhotos, total: totalPhotos });
          return {
            op: 'upload_photo', ok: true, photo_id: call.photo?.id || null,
            image,
          };
        } catch (err) {
          return {
            op: 'upload_photo', ok: false, photo_id: call.photo?.id || null,
            error: String(err && err.message ? err.message : err),
          };
        }
      }));
      results.push(...uploaded);
      if (uploaded.some((result) => !result.ok)) return { ok: false, uid: session.uid, results };
      index += batch.length - 1;
      continue;
    }
    try {
      switch (op.op) {
        case 'session':
          if (op.expected_uid && op.expected_uid !== session.uid) {
            throw new Error('This interrupted send belongs to a different Vendoo account. Sign in to that account to recover it.');
          }
          results.push({ op: 'session', ok: true, uid: session.uid, email: session.email });
          break;
        case 'new_item_id':
          results.push({ op: 'new_item_id', ok: true, item_id: vendooFirestoreId() });
          break;
        case 'upload_photo':
          results.push({ op: 'upload_photo', ok: true, photo_id: op.photo?.id || null, image: await uploadVendooPhoto(session, op.photo || {}) });
          completedPhotos += 1;
          onProgress({ completed: completedPhotos, total: totalPhotos });
          break;
        case 'create_item':
          results.push({ op: 'create_item', ok: true, result: await createVendooItem(session, op.item, op.subscription_version ?? null) });
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
    replyVendooApi(msg, await runVendooApiOps(ops, (progress) => {
      if (!msg.job_id) return;
      send({
        version: 1, type: 'job.vendoo_api_progress', job_id: msg.job_id,
        message_id: payload.request_id, sent_at: new Date().toISOString(),
        payload: { ...progress, request_id: payload.request_id, step: 'vendoo_api_photos' },
      });
    }));
  } catch (err) {
    replyVendooApi(msg, { ok: false, error: String(err && err.message ? err.message : err), results: [] });
  }
}
