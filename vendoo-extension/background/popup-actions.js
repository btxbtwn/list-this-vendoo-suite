// Manual popup fill and Diagnose Page.

// Existing fill function (backward compatible)
async function startVendooFill(data, platform, targetTabId) {
  try {
    let vendooTab = null;
    if (targetTabId) {
      try {
        const tab = await chrome.tabs.get(targetTabId);
        if (tab && tab.url && (tab.url.includes('vendoo.co') || tab.url.includes('localhost'))) {
          vendooTab = tab;
        }
      } catch (e) {}
    }
    if (!vendooTab) {
      const webTabs = await chrome.tabs.query({ url: 'https://web.vendoo.co/*' });
      const appTabs = await chrome.tabs.query({ url: 'https://app.vendoo.co/*' });
      const allTabs = [...webTabs, ...appTabs];
      vendooTab = allTabs.find(t => t.url && (t.url.includes('/app/item/') || t.url.includes('/item/new')));
    }
    if (!vendooTab) {
      chrome.runtime.sendMessage({
        type: 'FILL_ERROR',
        platform: platform.toUpperCase(),
        error: 'No Vendoo tab found',
      }).catch(() => {});
      return;
    }

    await chrome.tabs.update(vendooTab.id, { active: true });
    if (vendooTab.windowId) {
      await chrome.windows.update(vendooTab.windowId, { focused: true });
    }
    await sleep(200);
    await injectAndFill(vendooTab.id, data, platform);
  } catch (err) {
    chrome.runtime.sendMessage({
      type: 'FILL_ERROR',
      platform: platform.toUpperCase(),
      error: err.message,
    }).catch(() => {});
  }
}

async function injectAndFill(tabId, data, platform) {
  let response = await pingContentScript(tabId);
  if (!response || !response.ok) {
    await injectVendooContentScript(tabId);
    await sleep(500);
  }
  const fillResp = await chrome.tabs.sendMessage(tabId, {
    type: 'START_FILL',
    data,
    platform,
  });
  if (!fillResp?.ok) throw new Error('Content script failed to start');
}

function buildDiagnosticFilename(url) {
  const slug = String(url || 'page')
    .replace(/^https?:\/\//, '')
    .replace(/[^a-z0-9]+/gi, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
    .slice(0, 60) || 'page';
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  return `vendoo-diagnostic-${slug}-${timestamp}.json`;
}

async function runDiagnostic(targetTabId) {
  let targetTab = null;
  if (targetTabId) {
    try { targetTab = await chrome.tabs.get(targetTabId); } catch (_) {}
  }
  if (!targetTab) {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    targetTab = activeTab || null;
  }
  if (!targetTab?.id) throw new Error('No active tab found');

  try {
    await chrome.tabs.update(targetTab.id, { active: true });
    if (targetTab.windowId) await chrome.windows.update(targetTab.windowId, { focused: true });
  } catch (_) {}

  const [execution] = await chrome.scripting.executeScript({
    target: { tabId: targetTab.id },
    files: ['diagnostic-collector.js'],
  });
  void execution;
  const [collected] = await chrome.scripting.executeScript({
    target: { tabId: targetTab.id },
    func: async () => {
      const raw = await collectPageDiagnostics({ mode: 'active' });
      return typeof sanitizeDiagnostic === 'function' ? sanitizeDiagnostic(raw) : raw;
    },
  });
  const result = collected?.result;
  if (!result) throw new Error('Diagnostic returned no data');

  const filename = buildDiagnosticFilename(result.url || targetTab.url);
  await chrome.downloads.download({
    url: `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(result, null, 2))}`,
    filename,
    saveAs: false,
    conflictAction: 'uniquify',
  });

  return {
    filename,
    url: result.url || targetTab.url || '',
    fieldCount: result.fieldCount,
    dropdownCount: result.dropdownCount,
    dropdownsWithOptions: result.dropdownsWithOptions,
    liveDropdownsWithOptions: result.liveDropdownsWithOptions,
    totalDropdownOptions: result.totalDropdownOptions,
    expandedSections: result.expandedSections || [],
  };
}
