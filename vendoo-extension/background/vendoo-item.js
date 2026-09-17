// Read Vendoo drafts and search categories inside the page.

function compactVendooValue(value, depth) {
  if (value == null) return value;
  if (typeof value === 'string') {
    if (value.startsWith('data:') && value.length > 200) return `[data-url ${value.length} chars]`;
    if (value.length > 8000) return `${value.slice(0, 4000)}…[truncated ${value.length} chars]`;
    return value;
  }
  if (typeof value !== 'object' || depth > 8) return value;
  if (Array.isArray(value)) {
    return value.slice(0, 40).map((item) => compactVendooValue(item, depth + 1));
  }
  const out = {};
  const keys = Object.keys(value);
  const priority = ['generalDetails', 'listings', 'images', 'statuses', 'overrides', 'marketplaceSpecifics', 'categorySpecifics'];
  const ordered = [
    ...priority.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !priority.includes(key)),
  ].slice(0, 400);
  for (const key of ordered) {
    out[key] = compactVendooValue(value[key], depth + 1);
  }
  return out;
}

async function readVendooItemInPage(wantedId) {
  const fromUrl = (location.pathname.match(/\/item\/([^/?]+)/) || [])[1] || '';
  const itemId = durableItemId(wantedId) || durableItemId(fromUrl);
  if (!itemId) {
    return { ok: false, error: 'No Vendoo item id', url: location.href };
  }
  let userId = '';
  try {
    for (const key of Object.keys(localStorage)) {
      if (!key.startsWith('firebase:authUser:')) continue;
      const raw = JSON.parse(localStorage.getItem(key) || 'null');
      if (raw && raw.uid) {
        userId = String(raw.uid);
        break;
      }
    }
  } catch (err) {
    /* ignore */
  }
  const params = new URLSearchParams({
    useMarketplaceImages: 'true',
    isMultiQuantityItemsEnabled: 'true',
  });
  if (userId) params.set('userId', userId);
  const res = await fetch(`https://api.web.vendoo.co/api/item/${itemId}?${params.toString()}`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  let data = null;
  try {
    data = JSON.parse(await res.text());
  } catch (err) {
    data = null;
  }
  if (!res.ok) {
    return {
      ok: false,
      source: 'api',
      item_id: itemId,
      status: res.status,
      error: `GET /api/item returned ${res.status}`,
      url: location.href,
    };
  }
  const item = compactImportedVendooItem((data && (data.item || data.data || data)) || null);
  return {
    ok: true,
    source: 'api',
    item_id: itemId,
    status: res.status,
    url: location.href,
    item,
  };

  function compactImportedVendooItem(value) {
    const urls = [];
    const seen = new Set();
    const addUrl = (raw) => {
      if (!raw || typeof raw !== 'string') return;
      let url = raw.trim();
      if (url.startsWith('//')) url = `https:${url}`;
      if (!(url.startsWith('http://') || url.startsWith('https://'))) return;
      const lower = url.toLowerCase();
      const looksImage = /\.(jpe?g|png|webp|gif|heic|heif|avif)(\?|$)/i.test(url)
        || /cloudinary|cloudfront|googleusercontent|firebasestorage|imgix|storage\.googleapis\.com/.test(lower)
        || /(cdn|images|img|media|static|storage)[.-].*vendoo|vendoo[^/]*\.(cdn|images)/i.test(lower);
      if (!looksImage) return;
      if (seen.has(url)) return;
      seen.add(url);
      urls.push(url);
    };
    const compact = (node, depth) => {
      if (node == null || depth > 8) return node;
      if (typeof node === 'string') {
        addUrl(node);
        if (node.startsWith('data:') && node.length > 200) return `[data-url ${node.length} chars]`;
        if (node.length > 8000) return `${node.slice(0, 4000)}…[truncated ${node.length} chars]`;
        return node;
      }
      if (typeof node !== 'object') return node;
      if (Array.isArray(node)) return node.slice(0, 40).map((entry) => compact(entry, depth + 1));
      const out = {};
      for (const key of Object.keys(node).slice(0, 400)) {
        out[key] = compact(node[key], depth + 1);
      }
      return out;
    };
    const compacted = compact(value, 0);
    if (compacted && typeof compacted === 'object' && !Array.isArray(compacted) && urls.length) {
      if (!Array.isArray(compacted.images) || compacted.images.length === 0) {
        compacted.images = urls.map((url) => ({ url }));
      }
    }
    return compacted;
  }
}

async function readItemFromPage(tabId, itemId) {
  const attempts = 3;
  let last = { ok: false, error: 'No result from the Vendoo page' };
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      const [execution] = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: readVendooItemInPage,
        args: [itemId || ''],
      });
      const result = execution?.result;
      if (result && typeof result === 'object') {
        if (result.ok || attempt === attempts - 1) return result;
        last = result;
      } else {
        last = { ok: false, error: 'No result from the Vendoo page' };
      }
    } catch (err) {
      last = { ok: false, error: `Page read failed: ${err.message}` };
      if (attempt === attempts - 1) return last;
    }
    await sleep(750 * (attempt + 1));
  }
  return last;
}

function replyVendooItem(jobId, requestId, payload) {
  send({
    version: 1,
    type: 'job.vendoo_item',
    job_id: jobId || undefined,
    message_id: requestId,
    sent_at: new Date().toISOString(),
    payload: { request_id: requestId, ...payload },
  });
}

async function runVendooGet(jobId, payload) {
  const requestId = payload.request_id;
  const reply = (body) => replyVendooItem(jobId, requestId, body);

  // Fields Discovering… must not steal marketplace focus from Send/verify.
  if (activePatch || activeJob) {
    reply({
      ok: false,
      busy: true,
      error: 'Vendoo automation is using this draft; refresh after verification finishes',
    });
    return;
  }

  let tabId = null;
  const existingTabId = activePatch?.tabId || activeJob?.tabId || null;
  if (existingTabId) {
    try {
      const tab = await chrome.tabs.get(existingTabId);
      const currentId = extractItemIdFromUrl(tab.url || '');
      const wantId = durableItemId(payload.vendoo_item_id) || extractItemIdFromUrl(payload.vendoo_url || '');
      if (wantId && currentId === wantId) tabId = existingTabId;
    } catch (err) {
      /* tab closed */
    }
  }
  if (!tabId) {
    const opened = await openListingForPatch(
      { ...payload, job_id: jobId },
      { reload: false, preview: false },
    );
    if (!opened.ok) {
      reply({ ok: false, error: opened.error });
      return;
    }
    tabId = opened.tabId;
  }

  const job = { job_id: jobId, tabId };
  const itemId = durableItemId(payload.vendoo_item_id) || extractItemIdFromUrl(payload.vendoo_url || '');
  const apiRead = await Promise.race([
    readItemFromPage(tabId, itemId),
    sleep(8000).then(() => ({
      ok: false,
      source: 'api',
      item_id: itemId,
      error: 'Vendoo API read timed out',
    })),
  ]);

  let formRead = { ok: false };
  // Callers that only need the saved item (auto-apply) skip the form tour when the API answered.
  if (payload.api_only && apiRead.ok) {
    reply({
      ok: true,
      source: 'api',
      item_id: apiRead.item_id || itemId || null,
      url: apiRead.url || payload.vendoo_url || null,
      item: compactVendooValue(apiRead.item, 0),
      form: null,
      statuses: null,
      api_error: null,
      error: null,
    });
    return;
  }
  const ping = await pingContentScript(tabId);
  if (!ping?.ok) {
    try {
      await injectVendooContentScript(tabId);
      await sleep(400);
    } catch (err) {
      log(`Content script inject failed on tab ${tabId}: ${err.message}`);
    }
  }
  formRead = await sendToVendoo(job, { type: 'GET_VENDOO_ITEM' });
  const item = apiRead.ok ? compactVendooValue(apiRead.item, 0) : null;
  const form = formRead?.ok ? compactVendooValue(formRead.form || formRead.item, 0) : null;
  const statuses = (formRead?.ok && formRead.statuses && typeof formRead.statuses === 'object')
    ? formRead.statuses
    : (form && form.statuses && typeof form.statuses === 'object' ? form.statuses : null);
  const ok = Boolean(item || form);
  const sources = [];
  if (item) sources.push('api');
  if (form) sources.push('form');

  reply({
    ok,
    source: sources.join('+') || (apiRead.source || 'none'),
    item_id: apiRead.item_id || formRead?.item_id || itemId || null,
    url: apiRead.url || formRead?.url || payload.vendoo_url || null,
    item,
    form,
    statuses,
    api_error: apiRead.ok ? null : (apiRead.error || null),
    error: ok ? null : (apiRead.error || formRead?.error || 'Could not read the Vendoo draft'),
  });
}

function replyCategories(jobId, requestId, payload) {
  send({
    version: 1,
    type: 'job.categories',
    job_id: jobId || undefined,
    message_id: requestId,
    sent_at: new Date().toISOString(),
    payload: { request_id: requestId, ...payload },
  });
}

async function runSearchCategories(jobId, payload) {
  const requestId = payload.request_id;
  const reply = (body) => replyCategories(jobId, requestId, body);
  const query = String(payload.query || '').trim();
  if (!query) {
    reply({ ok: false, error: 'No category search query' });
    return;
  }
  if (activeJob && String(activeJob.current_step || '').includes('fill')) {
    reply({ ok: false, error: 'A fill is already running' });
    return;
  }

  let tabId = null;
  const existingTabId = activePatch?.tabId || activeJob?.tabId || null;
  if (existingTabId) {
    try {
      const tab = await chrome.tabs.get(existingTabId);
      const currentId = extractItemIdFromUrl(tab.url || '');
      const wantId = durableItemId(payload.vendoo_item_id) || extractItemIdFromUrl(payload.vendoo_url || '');
      if (wantId && currentId === wantId) tabId = existingTabId;
    } catch (err) {
      /* tab closed */
    }
  }
  if (!tabId) {
    const opened = await openListingForPatch(
      { ...payload, job_id: jobId },
      { reload: false, preview: false },
    );
    if (!opened.ok) {
      reply({ ok: false, query, error: opened.error });
      return;
    }
    tabId = opened.tabId;
  }

  const job = { job_id: jobId, tabId };
  const ping = await pingContentScript(tabId);
  if (!ping?.ok) {
    try {
      await injectVendooContentScript(tabId);
      await sleep(400);
    } catch (err) {
      log(`Content script inject failed on tab ${tabId}: ${err.message}`);
    }
  }
  const formReady = await sendToVendoo(job, { type: 'WAIT_FOR_FORM', timeoutMs: 30000 });
  if (!formReady?.ok) {
    reply({
      ok: false,
      query,
      error: formReady?.error || 'Vendoo listing form did not finish loading',
    });
    return;
  }
  const safety = await sendToVendoo(job, {
    type: 'CHECK_DRAFT_SAFETY',
    platforms: payload.platforms || [],
  });
  if (!safety?.ok) {
    reply({
      ok: false,
      query,
      error: safety?.error || 'Could not verify that the existing Vendoo item is a draft',
    });
    return;
  }
  const result = await sendToVendoo(job, { type: 'SEARCH_CATEGORIES', query });
  reply({
    ok: Boolean(result?.ok),
    query,
    path: result?.path || '',
    matches: Array.isArray(result?.matches) ? result.matches : [],
    error: result?.ok ? null : (result?.error || 'Could not search Vendoo categories'),
  });
}
