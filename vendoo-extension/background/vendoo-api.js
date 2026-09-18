// Talk to Vendoo's REST API from a signed-in web.vendoo.co tab.
//
// Vendoo's own importer never fills the Vendoo form: it normalizes items and
// POSTs a batch to /api/rest/v1/import/items_normalized. These helpers give
// Studio the same path, so generated listings are written as data instead of
// typed into a React form. See docs/vendoo-listing-architecture.md.
//
// Everything runs in the page's MAIN world so the Firebase session cookie
// rides along; there is no token to store on our side.

const VENDOO_API_BASE = 'https://api.web.vendoo.co';

// Creating items is in scope. Publishing is not — AGENTS.md says automation
// stops at saved drafts, so /api/item/{id}/list is deliberately absent.
function vendooApiInPage(base, calls) {
  const readUserId = () => {
    try {
      for (const key of Object.keys(localStorage)) {
        if (!key.startsWith('firebase:authUser:')) continue;
        const raw = JSON.parse(localStorage.getItem(key) || 'null');
        if (raw && raw.uid) return String(raw.uid);
      }
    } catch (err) {
      /* ignore */
    }
    return '';
  };

  const userId = readUserId();

  const request = async (method, path, body) => {
    const res = await fetch(`${base}${path}`, {
      method,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const text = await res.text();
    let data = null;
    try {
      data = JSON.parse(text);
    } catch (err) {
      data = null;
    }
    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        error: `${method} ${path} returned ${res.status}`,
        body: data ?? text.slice(0, 500),
      };
    }
    return { ok: true, status: res.status, data };
  };

  const run = async (call) => {
    switch (call.op) {
      case 'get_item': {
        const params = new URLSearchParams({
          useMarketplaceImages: 'true',
          isMultiQuantityItemsEnabled: 'true',
        });
        if (userId) params.set('userId', userId);
        const out = await request('GET', `/api/item/${call.item_id}?${params.toString()}`);
        if (out.ok) out.data = (out.data && (out.data.item || out.data.data)) || out.data;
        return out;
      }
      case 'upload_images':
        return request('POST', '/api/static/upload', { images: call.images });
      case 'import_normalized':
        return request('POST', '/api/rest/v1/import/items_normalized', {
          marketplaceId: call.marketplace_id || 'vendoo',
          marketplaceUserId: call.marketplace_user_id || userId,
          items: call.items,
        });
      case 'category_search':
        return request('POST', '/api/category/search', {
          text: call.text,
          country_code: call.country_code || 'US',
          marketplace_id: call.marketplace_id || 'ebay',
          type: call.type,
          additionalMultiMatchSearchParams: { noSearch: true },
        });
      default:
        return { ok: false, error: `Unknown Vendoo API op: ${call.op}` };
    }
  };

  return (async () => {
    if (!userId) {
      return { ok: false, error: 'Not signed in to Vendoo in this Chrome profile' };
    }
    const results = [];
    for (const call of calls) {
      try {
        results.push({ op: call.op, ...(await run(call)) });
      } catch (err) {
        results.push({ op: call.op, ok: false, error: String(err && err.message ? err.message : err) });
      }
      // Vendoo's own importer waits 1500ms between item fetches. Match it.
      if (call.throttle_ms) await new Promise((resolve) => setTimeout(resolve, call.throttle_ms));
    }
    return { ok: results.every((entry) => entry.ok), user_id: userId, results };
  })();
}

async function runVendooApiCalls(tabId, calls) {
  try {
    const [execution] = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: vendooApiInPage,
      args: [VENDOO_API_BASE, calls],
    });
    const result = execution?.result;
    if (result && typeof result === 'object') return result;
    return { ok: false, error: 'No result from the Vendoo page' };
  } catch (err) {
    return { ok: false, error: `Vendoo API call failed: ${err.message}` };
  }
}

// Read the user's own items so Studio can learn how Vendoo encodes conditions,
// colours and categories instead of guessing at them.
async function probeVendooItems(tabId, itemIds) {
  const calls = itemIds.map((itemId) => ({ op: 'get_item', item_id: itemId, throttle_ms: 250 }));
  const out = await runVendooApiCalls(tabId, calls);
  if (!out.ok && !Array.isArray(out.results)) return out;
  return {
    ok: true,
    user_id: out.user_id || null,
    items: (out.results || []).filter((entry) => entry.ok).map((entry) => entry.data),
    failures: (out.results || [])
      .filter((entry) => !entry.ok)
      .map((entry) => ({ error: entry.error, status: entry.status || null })),
  };
}

// Create items from already-serialized Vendoo bodies. Images are uploaded to
// Vendoo's storage first, matching what their importer does, so the stored item
// never points at a URL we host.
async function importVendooItems(tabId, items, imageUrls) {
  const calls = [];
  if (Array.isArray(imageUrls) && imageUrls.length) {
    calls.push({ op: 'upload_images', images: imageUrls });
  }
  calls.push({ op: 'import_normalized', items });
  const out = await runVendooApiCalls(tabId, calls);
  const results = out.results || [];
  const imported = results.find((entry) => entry.op === 'import_normalized');
  return {
    ok: Boolean(imported?.ok),
    user_id: out.user_id || null,
    uploaded: results.find((entry) => entry.op === 'upload_images')?.data ?? null,
    data: imported?.data ?? null,
    error: imported?.ok ? null : (imported?.error || out.error || 'Vendoo import failed'),
  };
}

// Vendoo's own category picker hits this endpoint and takes the first leaf hit.
// Exact where the form tour was a fuzzy match against rendered dropdown text.
async function searchVendooCategory(tabId, text, options) {
  const out = await runVendooApiCalls(tabId, [{
    op: 'category_search',
    text,
    country_code: options?.country_code,
    marketplace_id: options?.marketplace_id,
    type: options?.type,
  }]);
  const hit = (out.results || [])[0];
  if (!hit?.ok) return { ok: false, error: hit?.error || out.error || 'Category search failed' };
  const hits = hit.data?.hits?.hits || [];
  const leaf = hits.find((entry) => entry?._source?.is_leaf === true)?._source || null;
  return { ok: Boolean(leaf), leaf, matches: hits.map((entry) => entry?._source).filter(Boolean) };
}
