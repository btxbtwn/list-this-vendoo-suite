// Background service worker for Vendoo Multi-Lister

importScripts('diagnostic-collector.js');

// Listen for messages from popup and content scripts
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  console.log('[BG] Received:', msg.type);

  // Popup requests to start Vendoo fill
  if (msg.type === 'START_VENDOO' && msg.data) {
    startVendooFill(msg.data, 'vendoo', msg.tabId);
    sendResponse({ ok: true });
    return true;
  }

  // Popup requests to start eBay fill
  if (msg.type === 'START_EBAY' && msg.data) {
    // Route to Vendoo tab (filling eBay section)
    startVendooFill(msg.data, 'ebay', msg.tabId);
    sendResponse({ ok: true });
    return true;
  }

  // Popup requests to start Poshmark fill
  if (msg.type === 'START_POSHMARK' && msg.data) {
    startVendooFill(msg.data, 'poshmark', msg.tabId);
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === 'START_MERCARI' && msg.data) {
    startVendooFill(msg.data, 'mercari', msg.tabId);
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === 'START_DEPOP' && msg.data) {
    startVendooFill(msg.data, 'depop', msg.tabId);
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === 'START_ETSY' && msg.data) {
    startVendooFill(msg.data, 'etsy', msg.tabId);
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === 'RUN_DIAGNOSTIC') {
    runDiagnostic(msg.tabId)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (msg.type === 'REQUEST_DATA') {
    console.warn('[BG] REQUEST_DATA is not supported in the current fill flow');
    sendResponse({
      ok: false,
      error: 'REQUEST_DATA is not supported. Start fills from the popup.'
    });
    return false;
  }

  // Content script reports fill complete
  if (msg.type === 'FILL_COMPLETE') {
    console.log('[BG] Fill complete for:', msg.platform);
    chrome.runtime.sendMessage(msg).catch(() => {});
    sendResponse({ ok: true });
    return true;
  }

  // Content script reports fill error
  if (msg.type === 'FILL_ERROR') {
    console.log('[BG] Fill error for:', msg.platform, msg.error);
    chrome.runtime.sendMessage(msg).catch(() => {});
    sendResponse({ ok: true });
    return true;
  }

  return false;
});

async function startVendooFill(data, platform = 'vendoo', targetTabId = null) {
  console.log('[BG] Starting Vendoo fill. Platform:', platform, 'TargetTab:', targetTabId);

  try {
    let vendooTab = null;

    // 1. Try to use the specifically requested tab (Active Tab)
    if (targetTabId) {
      try {
        const tab = await chrome.tabs.get(targetTabId);
        // Verify it looks like Vendoo (or just try anyway? Better to check)
        if (tab && tab.url && (tab.url.includes('vendoo.co') || tab.url.includes('localhost'))) {
          vendooTab = tab;
          console.log('[BG] Using targeted active tab:', tab.id);
        } else {
          console.log('[BG] Targeted tab is not Vendoo:', tab?.url);
        }
      } catch (e) {
        console.log('[BG] Error getting target tab:', e);
      }
    }

    // 2. Fallback: Search for ANY Vendoo tab if we didn't find one
    if (!vendooTab) {
      console.log('[BG] No valid target tab found. Searching for any Vendoo tab...');
      const webTabs = await chrome.tabs.query({ url: 'https://web.vendoo.co/*' });
      const appTabs = await chrome.tabs.query({ url: 'https://app.vendoo.co/*' });
      const allTabs = [...webTabs, ...appTabs];
      
      vendooTab = allTabs.find(t => t.url && (t.url.includes('/app/item/') || t.url.includes('/item/new')));
      
      if (vendooTab) {
         console.log('[BG] Found fallback Vendoo tab:', vendooTab.id);
      }
    }

    if (!vendooTab) {
      console.log('[BG] No Vendoo tab found.');
      chrome.runtime.sendMessage({
        type: 'FILL_ERROR',
        platform: platform.toUpperCase(),
        error: 'No Vendoo tab found. Please open a listing in Vendoo.'
      }).catch(() => {});
      return;
    }

    // 3. Execute
    // Focus the tab (even if it's already active, this ensures the window is frontmost)
    await chrome.tabs.update(vendooTab.id, { active: true });
    if (vendooTab.windowId) {
        await chrome.windows.update(vendooTab.windowId, { focused: true });
    }
    
    await sleep(200); // Short pause for focus
    await injectAndFill(vendooTab.id, data, platform);
    
  } catch (err) {
    console.error('[BG] Error in startVendooFill:', err);
    chrome.runtime.sendMessage({
      type: 'FILL_ERROR',
      platform: platform.toUpperCase(),
      error: err.message
    }).catch(() => {});
  }
}

async function injectAndFill(tabId, data, platform = 'vendoo') {
  console.log('[BG] Injecting/Filling tab:', tabId, 'platform:', platform);
  
  // Choose script
  let scriptFile;
  if (platform === 'ebay') scriptFile = 'content-scripts/ebay.js';
  else if (platform === 'poshmark') scriptFile = 'content-scripts/poshmark.js';
  else scriptFile = 'content-scripts/vendoo.js';
  
  // For Vendoo-hosted platforms (filling sections within Vendoo), we always use vendoo.js logic
  // The 'ebay', 'poshmark' etc. platforms passed here are actually filling the Vendoo form SECTIONS.
  // Wait, looking at manifest:
  // content-scripts/vendoo.js matches vendoo.co
  // content-scripts/ebay.js matches ebay.com
  // content-scripts/poshmark.js matches poshmark.com
  
  // IF we are on Vendoo.co (which we are, per startVendooFill logic), we MUST use vendoo.js.
  // The "platform" argument passed to START_FILL tells vendoo.js which SECTION to fill.
  // EXCEPT if we are actually redirecting to eBay/Poshmark native sites?
  // The popup says "Fill Vendoo", "Fill eBay", "Fill Poshmark".
  // "Fill eBay" in popup calls START_EBAY.
  // My previous code: startVendooFill(msg.data, 'ebay').
  // And startVendooFill finds a Vendoo tab.
  // So it seems the intention is to fill the Vendoo form's eBay section.
  
  // So scriptFile should ALWAYS be 'content-scripts/vendoo.js' if we are on Vendoo?
  // Let's check where the script is injected.
  // If tab is Vendoo, we need vendoo.js.
  // If tab is eBay, we need ebay.js.
  
  // Current logic in startVendooFill finds a Vendoo tab.
  // So we are filling Vendoo.
  // So we should inject 'content-scripts/vendoo.js'.
  
  // However, older code had `if (platform === 'ebay') scriptFile = 'content-scripts/ebay.js'`.
  // That would only work if we were targeting an eBay tab.
  // But startVendooFill searches for Vendoo tabs!
  // So that logic was likely flawed or legacy for when it targeted eBay directly.
  // Given we are targeting Vendoo tabs, we force vendoo.js.
  
  scriptFile = 'content-scripts/vendoo.js';

  try {
    // Check if script is already there
    let response = null;
    try {
      response = await chrome.tabs.sendMessage(tabId, { type: 'PING' });
    } catch (e) { /* ignore */ }
    
    if (!response || !response.ok) {
      console.log('[BG] Injecting:', scriptFile);
      await chrome.scripting.executeScript({
        target: { tabId },
        files: [scriptFile]
      });
      await sleep(500);
    }
    
    // Send command
    console.log('[BG] Sending START_FILL...');
    const fillResp = await chrome.tabs.sendMessage(tabId, { 
      type: 'START_FILL', 
      data: data,
      platform: platform 
    });
    
    if (!fillResp?.ok) throw new Error('Content script failed to start');
    
  } catch (err) {
    console.error('[BG] InjectAndFill Error:', err);
    throw err;
  }
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

async function runDiagnostic(targetTabId = null) {
  let targetTab = null;

  if (targetTabId) {
    try {
      targetTab = await chrome.tabs.get(targetTabId);
    } catch (_error) {
      targetTab = null;
    }
  }

  if (!targetTab) {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    targetTab = activeTab || null;
  }

  if (!targetTab?.id) {
    throw new Error('No active tab found');
  }

  try {
    await chrome.tabs.update(targetTab.id, { active: true });
    if (targetTab.windowId) {
      await chrome.windows.update(targetTab.windowId, { focused: true });
    }
  } catch (_error) {
    // Best effort only. Diagnostics can still succeed without forcing focus.
  }

  const [execution] = await chrome.scripting.executeScript({
    target: { tabId: targetTab.id },
    func: collectPageDiagnostics
  });

  const result = execution?.result;
  if (!result) {
    throw new Error('Diagnostic returned no data');
  }

  const filename = buildDiagnosticFilename(result.url || targetTab.url);
  const downloadId = await chrome.downloads.download({
    url: `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(result, null, 2))}`,
    filename,
    saveAs: false,
    conflictAction: 'uniquify'
  });

  return {
    filename,
    downloadId,
    url: result.url || targetTab.url || '',
    fieldCount: result.fieldCount,
    dropdownCount: result.dropdownCount,
    dropdownsWithOptions: result.dropdownsWithOptions,
    liveDropdownsWithOptions: result.liveDropdownsWithOptions,
    totalDropdownOptions: result.totalDropdownOptions,
    expandedSections: result.expandedSections || []
  };
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}
