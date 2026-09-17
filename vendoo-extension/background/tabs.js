// Vendoo tab lookup, readiness, and listing navigation.

const NEW_ITEM_URL = 'https://web.vendoo.co/app/item/new?marketplace=general';

function isNewItemUrl(url) {
  if (!url) return false;
  try {
    return new URL(url).pathname.includes('/item/new');
  } catch {
    return url.includes('/item/new');
  }
}

function isVendooUrl(url) {
  if (!url) return false;
  try {
    const host = new URL(url).hostname;
    return host === 'web.vendoo.co' || host === 'app.vendoo.co';
  } catch {
    return url.includes('vendoo.co');
  }
}

function withMarketplaceQuery(url, marketplace) {
  if (!url || !marketplace) return url;
  try {
    const parsed = new URL(url);
    parsed.searchParams.set('marketplace', String(marketplace).toLowerCase());
    return parsed.toString();
  } catch {
    return url;
  }
}

function listingUrlsMatch(currentUrl, targetUrl) {
  if (!currentUrl || !targetUrl) return false;
  try {
    const current = new URL(currentUrl);
    const target = new URL(targetUrl);
    if (current.pathname !== target.pathname) return false;
    const wantMp = (target.searchParams.get('marketplace') || '').toLowerCase();
    if (!wantMp) return true;
    const haveMp = (current.searchParams.get('marketplace') || '').toLowerCase();
    return haveMp === wantMp;
  } catch {
    return false;
  }
}

function isTabReady(tab) {
  if (!tab || !isVendooUrl(tab.url)) return false;
  if (tab.status === 'complete') return true;
  // Vendoo's SPA often keeps status "loading" on /item/new while the form is usable.
  return /\/app\/item\//i.test(String(tab.url || '')) && tab.status === 'loading';
}

function tabMatchesTarget(tab, targetUrl) {
  if (!isTabReady(tab)) return false;
  if (!targetUrl) return true;
  return listingUrlsMatch(tab.url || '', targetUrl);
}

async function waitForTabComplete(tabId, timeoutMs = 30000, targetUrl = null) {
  try {
    const current = await chrome.tabs.get(tabId);
    if (tabMatchesTarget(current, targetUrl)) return current;
  } catch (err) {
    log(`waitForTabComplete: cannot get tab ${tabId}: ${err.message}`);
    return null;
  }

  return new Promise((resolve) => {
    let settled = false;

    const timer = setTimeout(async () => {
      if (settled) return;
      settled = true;
      chrome.tabs.onUpdated.removeListener(onUpdated);
      try {
        resolve(await chrome.tabs.get(tabId));
      } catch {
        resolve(null);
      }
    }, timeoutMs);

    function finish(tab) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve(tab);
    }

    function onUpdated(id, _info, tab) {
      if (id === tabId && tabMatchesTarget(tab, targetUrl)) finish(tab);
    }

    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.get(tabId).then((tab) => {
      if (tabMatchesTarget(tab, targetUrl)) finish(tab);
    }).catch(() => {});
  });
}

async function pingContentScript(tabId) {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: 'PING' });
  } catch (err) {
    log(`PING failed on tab ${tabId}: ${err.message}`);
    return null;
  }
}

async function injectVendooContentScript(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ['content-script-version.js', 'content-scripts/vendoo.js'],
  });
}

async function reloadTabAndWait(tabId, timeoutMs = 30000) {
  return new Promise((resolve) => {
    let seenLoading = false;
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      chrome.tabs.get(tabId).then(resolve).catch(() => resolve(null));
    }, timeoutMs);

    function finish(tab) {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve(tab);
    }

    function onUpdated(id, info, tab) {
      if (id !== tabId) return;
      if (info.status === 'loading') seenLoading = true;
      if (seenLoading && isTabReady(tab)) finish(tab);
    }

    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.reload(tabId).catch((err) => {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      log(`Tab reload failed: ${err.message}`);
      resolve(null);
    });
  });
}

async function findNewItemTab() {
  const engineId = await rememberedEngineWindowId();
  if (engineId == null) return null;
  const webTabs = await chrome.tabs.query({ url: 'https://web.vendoo.co/*', windowId: engineId });
  const appTabs = await chrome.tabs.query({ url: 'https://app.vendoo.co/*', windowId: engineId });
  return [...webTabs, ...appTabs].find(t => isNewItemUrl(t.url)) || null;
}

const NON_DURABLE_ITEM_IDS = new Set(['new', 'edit', 'create']);

function durableItemId(value) {
  const itemId = String(value || '').trim();
  if (!itemId || NON_DURABLE_ITEM_IDS.has(itemId.toLowerCase())) return '';
  return itemId;
}

function extractItemIdFromUrl(url) {
  try {
    const match = new URL(url).pathname.match(/\/item\/([^/?]+)/);
    return durableItemId(match?.[1]);
  } catch {
    return '';
  }
}

async function findTabByDraft(vendooUrl, itemId) {
  const webTabs = await chrome.tabs.query({ url: 'https://web.vendoo.co/*' });
  const appTabs = await chrome.tabs.query({ url: 'https://app.vendoo.co/*' });
  const tabs = [...webTabs, ...appTabs];
  if (vendooUrl) {
    try {
      const wantPath = new URL(vendooUrl).pathname;
      const match = tabs.find((tab) => {
        try { return new URL(tab.url).pathname === wantPath; } catch { return false; }
      });
      if (match) return match;
    } catch {
      /* ignore malformed draft URLs */
    }
  }
  if (itemId) {
    const match = tabs.find((tab) => tab.url && tab.url.includes(`/item/${itemId}`));
    if (match) return match;
  }
  return null;
}

async function findVisibleVendooTab() {
  const engineId = await rememberedEngineWindowId();
  let engineOffscreen = false;
  if (engineId != null) {
    try {
      engineOffscreen = isOffscreenEngineWindow(await chrome.windows.get(engineId));
    } catch (_) {}
  }
  const webTabs = await chrome.tabs.query({ url: 'https://web.vendoo.co/*' });
  const appTabs = await chrome.tabs.query({ url: 'https://app.vendoo.co/*' });
  const tabs = [...webTabs, ...appTabs];
  return tabs.find((tab) => (
    tab.windowId
    && tab.status === 'complete'
    && isVendooUrl(tab.url)
    && (!engineOffscreen || tab.windowId !== engineId)
  )) || null;
}

async function openVisibleVendooWindow(url, existingTab, { foreground = false } = {}) {
  try {
    const tab = await openEverydayListingTab(url, existingTab, { foreground });
    return { ok: true, tabId: tab.id, windowId: tab.windowId };
  } catch (err) {
    log(`Could not open a Vendoo tab (${err.message})`);
    const created = await createWindowSafe({ url, focused: foreground, type: 'normal' });
    await chrome.storage.local.set({ [ENGINE_WINDOW_KEY]: created.id });
    if (foreground) await showWindow(created.id);
    else await hideWindow(created.id);
    const tab = created.tabs && created.tabs[0];
    return { ok: true, tabId: tab?.id, windowId: created.id };
  }
}

async function focusVendooListing(payload) {
  const itemId = durableItemId(payload.vendoo_item_id) || extractItemIdFromUrl(payload.vendoo_url || '');
  const itemUrl = itemId
    ? (extractItemIdFromUrl(payload.vendoo_url || '') === itemId
      ? payload.vendoo_url
      : `https://web.vendoo.co/app/item/${itemId}`)
    : '';
  const url = itemUrl || 'https://web.vendoo.co/app';
  const existing = itemId ? await findTabByDraft(url, itemId) : await findVisibleVendooTab();
  const engineId = await rememberedEngineWindowId();

  try {
    if (existing?.id && engineId != null && existing.windowId === engineId) {
      return await openVisibleVendooWindow(url, existing, { foreground: true });
    }
    if (existing?.id) {
      await chrome.tabs.update(existing.id, { active: true });
      await showWindow(existing.windowId);
      return { ok: true, tabId: existing.id, windowId: existing.windowId };
    }
    return await openVisibleVendooWindow(url, null, { foreground: true });
  } catch (err) {
    log(`job.open_listing could not show tab: ${err.message}`);
    const created = await createWindowSafe({ url, focused: true, type: 'normal' });
    await chrome.storage.local.set({ [ENGINE_WINDOW_KEY]: created.id });
    await showWindow(created.id);
    const tab = created.tabs && created.tabs[0];
    return { ok: true, tabId: tab?.id, windowId: created.id };
  }
}

async function openListingForPatch(payload, { reload = true, preview = true, marketplace = '', foreground = false } = {}) {
  const requestedUrl = payload.vendoo_url || '';
  const itemId = durableItemId(payload.vendoo_item_id) || extractItemIdFromUrl(requestedUrl);
  if (!itemId) {
    return { ok: false, error: 'No Vendoo draft URL. Send the listing first.' };
  }
  let url = extractItemIdFromUrl(requestedUrl) === itemId
    ? requestedUrl
    : `https://web.vendoo.co/app/item/${itemId}`;
  if (marketplace) url = withMarketplaceQuery(url, marketplace);
  const existing = await findTabByDraft(url, itemId);
  let currentUrl = existing?.url || '';
  if (existing?.id) {
    try {
      const current = await chrome.tabs.get(existing.id);
      currentUrl = current.url || currentUrl;
    } catch (_) {}
  }
  const samePage = Boolean(existing?.id) && listingUrlsMatch(currentUrl, url);
  const opened = await openVisibleVendooWindow(samePage ? null : url, existing, { foreground });
  const tabId = opened.tabId;
  if (!tabId) {
    return { ok: false, error: 'Could not open the Vendoo draft.' };
  }
  let loaded;
  if (reload && samePage) {
    log(`Reloading Vendoo draft tab ${tabId} -> ${url}`);
    loaded = await reloadTabAndWait(tabId, 20000);
  } else {
    if (!samePage) log(`Opening Vendoo draft ${url}`);
    loaded = await waitForTabComplete(tabId, 20000, url);
  }
  if (preview && payload.job_id) {
    await startJobPreview(tabId, payload.job_id);
  }
  if (!isTabReady(loaded)) {
    if (loaded && isVendooUrl(loaded.url)) {
      log(`Vendoo tab still ${loaded.status || 'unknown'}; waiting longer ${loaded.url}`);
      loaded = await waitForTabComplete(tabId, 15000, url);
    }
    if (!isTabReady(loaded)) {
      return { ok: false, error: `Vendoo draft did not finish loading (${loaded?.url || 'unknown url'})` };
    }
  }
  return { ok: true, tabId };
}
