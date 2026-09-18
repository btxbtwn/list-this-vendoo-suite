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
// Publishing is out of scope: /api/item/{id}/list is deliberately absent.

const VENDOO_API_BASE = 'https://api.web.vendoo.co';
const VENDOO_MSVC_BASE = 'https://us.vendoo.co';
const VENDOO_FUNCTIONS_BASE = 'https://us-central1-vendoo-prod-7948f.cloudfunctions.net';
const VENDOO_FIRESTORE_BASE = 'https://firestore.googleapis.com/v1/projects/vendoo-prod-7948f/databases/(default)/documents';
const VENDOO_TOKEN_REFRESH_URL = 'https://securetoken.googleapis.com/v1/token';
const VENDOO_APP_URL = 'https://web.vendoo.co/app/';
const VENDOO_TOKEN_MIN_TTL_MS = 5 * 60 * 1000;
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
function readVendooSessionInPage() {
  try {
    for (const key of Object.keys(localStorage)) {
      if (!key.startsWith('firebase:authUser:')) continue;
      const raw = JSON.parse(localStorage.getItem(key) || 'null');
      if (!raw || !raw.uid) continue;
      const sts = raw.stsTokenManager || {};
      return {
        ok: true,
        uid: String(raw.uid),
        email: raw.email || null,
        api_key: raw.apiKey || key.split(':')[2] || null,
        access_token: sts.accessToken || null,
        refresh_token: sts.refreshToken || null,
        expiration_time: Number(sts.expirationTime) || 0,
      };
    }
  } catch (err) {
    return { ok: false, error: `Could not read the Vendoo session: ${err.message}` };
  }
  return { ok: false, error: 'Not signed in to Vendoo in this Chrome profile' };
}

async function findOrOpenVendooTab() {
  const existing = await findVisibleVendooTab();
  if (existing?.id) return existing.id;
  const opened = await openVisibleVendooWindow(VENDOO_APP_URL, null, { foreground: false });
  if (!opened.tabId) throw new Error('Could not open a Vendoo tab');
  await waitForTabComplete(opened.tabId, 30000);
  return opened.tabId;
}

async function readVendooSession() {
  const tabId = await findOrOpenVendooTab();
  const [execution] = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    func: readVendooSessionInPage,
  });
  const session = execution?.result;
  if (!session || !session.ok) throw new Error(session?.error || 'No Vendoo session in the page');
  return session;
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

async function freshVendooSession() {
  let session = await readVendooSession();
  if (!session.access_token || session.expiration_time - Date.now() < VENDOO_TOKEN_MIN_TTL_MS) {
    session = await refreshVendooToken(session);
  }
  if (!session.access_token) throw new Error('Vendoo session has no ID token; sign in to Vendoo again');
  return session;
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
        case 'get_item':
          results.push({ op: 'get_item', ok: true, item_id: op.item_id, item: await getVendooItem(session, op.item_id) });
          break;
        case 'category_search':
          results.push({ op: 'category_search', ok: true, ...(await searchVendooCategory(session, op)) });
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
