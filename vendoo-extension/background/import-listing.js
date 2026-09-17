// Import an existing Vendoo listing and its photos into Studio.

async function importVendooListing(tabId) {
  if (!paired) {
    return { ok: false, error: 'Studio is not connected' };
  }
  if (!tabId) {
    return { ok: false, error: 'No active Vendoo tab' };
  }
  const tab = await chrome.tabs.get(tabId);
  const itemId = extractItemIdFromUrl(tab.url || '');
  if (!itemId) {
    return { ok: false, error: 'Open a saved Vendoo listing first' };
  }

  const ready = await waitForContentScript({ tabId, job_id: 'import' });
  if (!ready.ok) {
    return { ok: false, error: ready.error };
  }

  const apiRead = await readItemFromPage(tabId, itemId);
  const formRead = await sendToVendoo({ tabId }, { type: 'GET_VENDOO_ITEM' });
  const item = apiRead.ok ? apiRead.item : null;
  const form = formRead?.ok ? (formRead.form || formRead.item) : null;
  if (!item && !form) {
    return { ok: false, error: apiRead.error || formRead?.error || 'Could not read the Vendoo listing' };
  }

  const imageUrls = collectImportedImageUrls(item, form);
  const response = await fetch(`${STUDIO_URL}/api/imports/vendoo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      item_id: itemId,
      url: tab.url,
      source: [apiRead.ok ? 'api' : null, formRead?.ok ? 'form' : null].filter(Boolean).join('+') || 'none',
      item,
      form,
      image_urls: imageUrls,
    }),
  });
  let body = null;
  try {
    body = await response.json();
  } catch (err) {
    body = null;
  }
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === 'string' ? detail : (body?.message || `Studio import failed (${response.status})`);
    return { ok: false, error: message };
  }

  let photoCount = body.photo_count || 0;
  const remaining = imageUrls.filter((url) => url.startsWith('blob:') || url.startsWith('http'));
  if (photoCount === 0 && remaining.length) {
    photoCount = await uploadImportedPhotos(tabId, body.conversation_id, remaining);
  }

  await chrome.tabs.create({ url: `${STUDIO_URL}/?listing=${body.conversation_id}`, active: true });
  return {
    ok: true,
    conversation_id: body.conversation_id,
    reused: Boolean(body.reused),
    photo_count: photoCount,
    photo_warnings: body.photo_warnings || [],
    listing_title: body.listing_title || '',
  };
}

function collectImportedImageUrls(...blobs) {
  const urls = [];
  const seen = new Set();
  const add = (raw) => {
    if (!raw || typeof raw !== 'string') return;
    let url = raw.trim();
    if (url.startsWith('//')) url = `https:${url}`;
    if (!(url.startsWith('http://') || url.startsWith('https://') || url.startsWith('blob:'))) return;
    if (url.startsWith('data:')) return;
    const lower = url.toLowerCase();
    const looksImage = url.startsWith('blob:')
      || /\.(jpe?g|png|webp|gif|heic|heif|avif)(\?|$)/i.test(url)
      || /cloudinary|cloudfront|googleusercontent|firebasestorage|imgix|storage\.googleapis\.com/.test(lower)
      || /(cdn|images|img|media|static|storage)[.-].*vendoo|vendoo[^/]*\.(cdn|images)/i.test(lower);
    if (!looksImage || seen.has(url)) return;
    seen.add(url);
    urls.push(url);
  };
  const walk = (value, depth) => {
    if (value == null || depth > 10) return;
    if (typeof value === 'string') {
      add(value);
      return;
    }
    if (Array.isArray(value)) {
      value.slice(0, 40).forEach((entry) => walk(entry, depth + 1));
      return;
    }
    if (typeof value !== 'object') return;
    Object.values(value).slice(0, 120).forEach((entry) => walk(entry, depth + 1));
  };
  blobs.forEach((blob) => walk(blob, 0));
  return urls.slice(0, 20);
}

async function fetchImageBlobInPage(url) {
  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) return { ok: false, status: res.status };
  const buffer = await res.arrayBuffer();
  const bytes = Array.from(new Uint8Array(buffer));
  return {
    ok: true,
    bytes,
    contentType: res.headers.get('content-type') || 'image/jpeg',
  };
}

async function uploadImportedPhotos(tabId, conversationId, urls) {
  let uploaded = 0;
  for (const url of urls.slice(0, 20)) {
    try {
      const [execution] = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: fetchImageBlobInPage,
        args: [url],
      });
      const result = execution?.result;
      if (!result?.ok || !Array.isArray(result.bytes) || !result.bytes.length) continue;
      const blob = new Blob([new Uint8Array(result.bytes)], { type: result.contentType || 'image/jpeg' });
      const path = String(url).split('?')[0];
      const name = path.split('/').pop() || `vendoo-${uploaded + 1}.jpg`;
      const form = new FormData();
      form.append('files', blob, name.includes('.') ? name : `${name}.jpg`);
      const resp = await fetch(`${STUDIO_URL}/api/conversations/${conversationId}/photos`, {
        method: 'POST',
        body: form,
      });
      if (resp.ok) uploaded += 1;
    } catch (err) {
      log(`Imported photo fetch failed for ${url}: ${err.message}`);
    }
  }
  return uploaded;
}
