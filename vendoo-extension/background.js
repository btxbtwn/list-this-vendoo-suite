const STUDIO_URL = 'http://127.0.0.1:4318';
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const HEARTBEAT_MS = 20000;

let ws = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let paired = false;
let activeJob = null;
let reconnectAttempt = 0;

importScripts('diagnostic-collector.js');

function log(msg) {
  console.log(`[BG-Studio] ${msg}`);
}

function error(msg) {
  console.error(`[BG-Studio] ${msg}`);
}

async function getPairingToken() {
  const stored = await chrome.storage.local.get('studio_pairing_token');
  return stored.studio_pairing_token || null;
}

async function setPairingToken(token) {
  await chrome.storage.local.set({ studio_pairing_token: token });
}

async function persistActiveJob(job) {
  activeJob = job;
  if (job) {
    await chrome.storage.local.set({ studio_active_job: job });
  } else {
    await chrome.storage.local.remove('studio_active_job');
  }
}

async function restoreActiveJob() {
  const stored = await chrome.storage.local.get('studio_active_job');
  if (stored.studio_active_job) {
    activeJob = stored.studio_active_job;
    log(`Restored active job: ${activeJob.job_id} step=${activeJob.current_step}`);
  }
}

async function persistCompletedJobIds() {
  const stored = await chrome.storage.local.get('studio_completed_job_ids');
  return stored.studio_completed_job_ids || [];
}

async function addCompletedJobId(jobId) {
  const ids = await persistCompletedJobIds();
  ids.push(jobId);
  await chrome.storage.local.set({ studio_completed_job_ids: ids.slice(-100) });
}

async function removeCompletedJobId(jobId) {
  const ids = await persistCompletedJobIds();
  await chrome.storage.local.set({
    studio_completed_job_ids: ids.filter(id => id !== jobId),
  });
}

async function isJobCompleted(jobId) {
  const ids = await persistCompletedJobIds();
  return ids.includes(jobId);
}

function send(message) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
  }
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  log(`Connecting to ${STUDIO_URL}/api/extension/ws...`);

  try {
    ws = new WebSocket(`ws://127.0.0.1:4318/api/extension/ws`);
  } catch (e) {
    error(`WebSocket creation failed: ${e.message}`);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    log('WebSocket connected');
    reconnectAttempt = 0;
    startHeartbeat();
    sendIdent();
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleStudioMessage(msg);
    } catch (e) {
      error(`Failed to parse message: ${e.message}`);
    }
  };

  ws.onclose = (event) => {
    log(`WebSocket closed code=${event.code}`);
    paired = false;
    stopHeartbeat();
    scheduleReconnect();
  };

  ws.onerror = (event) => {
    error('WebSocket error');
  };
}

async function sendIdent() {
  const token = await getPairingToken();
  send({
    version: 1,
    type: 'extension.ready',
    message_id: crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36),
    sent_at: new Date().toISOString(),
    payload: { token: token || 'direct' },
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt), RECONNECT_MAX_MS);
  reconnectAttempt++;
  log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempt})`);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    send({ version: 1, type: 'pong', message_id: Date.now().toString(36), sent_at: new Date().toISOString() });
  }, HEARTBEAT_MS);
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

async function handleStudioMessage(msg) {
  const type = msg.type || '';

  switch (type) {
    case 'connection.accepted':
      log('Paired with Studio');
      paired = true;
      break;

    case 'job.start': {
      const payload = msg.payload || {};
      const jobId = msg.job_id || payload.job_id;

      if (!jobId) {
        log('job.start missing job_id');
        return;
      }

      if (activeJob && activeJob.job_id === jobId) {
        activeJob = null;
        await persistActiveJob(null);
      }

      if (await isJobCompleted(jobId)) {
        log(`Job ${jobId} was previously completed, clearing and re-running`);
        await removeCompletedJobId(jobId);
      }

      await persistActiveJob({
        job_id: jobId,
        listing: payload.listing || {},
        photos: payload.photos || [],
        options: payload.options || {},
        current_step: 'accepted',
        attempt: 0,
      });

      send({
        version: 1,
        type: 'job.accepted',
        job_id: jobId,
        message_id: Date.now().toString(36),
        sent_at: new Date().toISOString(),
        payload: { status: 'accepted' },
      });

      runJob(jobId);
      break;
    }

    case 'job.retry': {
      const jobId = msg.job_id || msg.payload?.job_id;
      if (!jobId) return;

      if (activeJob && activeJob.job_id === jobId) {
        activeJob.attempt = (activeJob.attempt || 0) + 1;
        await persistActiveJob(activeJob);
        runJob(jobId);
      }
      break;
    }

    case 'job.cancel': {
      const jobId = msg.job_id || msg.payload?.job_id;
      if (!jobId) return;

      if (activeJob && activeJob.job_id === jobId) {
        const csJob = activeJob;
        activeJob = null;
        await persistActiveJob(null);

        send({
          version: 1,
          type: 'job.cancelled',
          job_id: jobId,
          message_id: Date.now().toString(36),
          sent_at: new Date().toISOString(),
          payload: { cancelled_at: csJob.current_step },
        });
      }
      break;
    }

    case 'ping':
      send({
        version: 1,
        type: 'pong',
        message_id: Date.now().toString(36),
        sent_at: new Date().toISOString(),
      });
      break;
  }
}

async function runJob(jobId) {
  if (!activeJob || activeJob.job_id !== jobId) {
    return;
  }

  const steps = buildJobSteps(activeJob);

  let failed = false;
  for (const step of steps) {
    if (!activeJob || activeJob.job_id !== jobId) {
      log('Job cancelled or replaced, stopping');
      return;
    }

    activeJob.current_step = step.step;
    await persistActiveJob(activeJob);

    send({
      version: 1,
      type: 'job.progress',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { step: step.step },
    });

    try {
      const result = await step.fn(activeJob);
      if (!result.ok) {
        failed = true;
        send({
          version: 1,
          type: 'job.step_failed',
          job_id: jobId,
          message_id: Date.now().toString(36),
          sent_at: new Date().toISOString(),
          payload: {
            step: step.step,
            error: result.error || 'Step failed',
            fields: result.fields || {},
          },
        });
        break;
      }

      send({
        version: 1,
        type: 'job.step_completed',
        job_id: jobId,
        message_id: Date.now().toString(36),
        sent_at: new Date().toISOString(),
        payload: {
          step: step.step,
          vendoo_item_id: result.vendoo_item_id,
          vendoo_url: result.vendoo_url,
        },
      });

      if (result.vendoo_item_id && !activeJob.vendoo_item_id) {
        activeJob.vendoo_item_id = result.vendoo_item_id;
        await persistActiveJob(activeJob);
      }
    } catch (err) {
      failed = true;
      send({
        version: 1,
        type: 'job.step_failed',
        job_id: jobId,
        message_id: Date.now().toString(36),
        sent_at: new Date().toISOString(),
        payload: { step: step.step, error: err.message },
      });
      break;
    }
  }

  if (!failed) {
    const vurl = activeJob?.vendoo_url;
    await addCompletedJobId(jobId);
    activeJob = null;
    await persistActiveJob(null);

    send({
      version: 1,
      type: 'job.completed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { vendoo_url: vurl },
    });
  }
}

function buildJobSteps(job) {
  const steps = [];

  steps.push({ step: 'opening_vendoo', fn: openVendooListing });
  steps.push({ step: 'waiting_ready', fn: waitForContentScript });
  steps.push({ step: 'uploading_photos', fn: uploadPhotos });
  steps.push({ step: 'filling_general', fn: fillGeneral });
  steps.push({ step: 'saving_general', fn: saveGeneral });
  steps.push({ step: 'auditing_general', fn: auditGeneral });

  const platforms = job.options?.platforms || [];
  for (const platform of platforms) {
    steps.push({ step: `filling_${platform}`, fn: (j) => fillMarketplace(j, platform) });
    steps.push({ step: `saving_${platform}`, fn: (j) => saveMarketplace(j, platform) });
    steps.push({ step: `auditing_${platform}`, fn: (j) => auditMarketplace(j, platform) });
  }

  return steps;
}

async function findOrCreateVendooTab() {
  const NEW_ITEM_URL = 'https://web.vendoo.co/app/item/new?marketplace=general';
  const webTabs = await chrome.tabs.query({ url: 'https://web.vendoo.co/*' });
  const appTabs = await chrome.tabs.query({ url: 'https://app.vendoo.co/*' });
  const allTabs = [...webTabs, ...appTabs];

  const newItemTab = allTabs.find(t => {
    const url = t.url || '';
    return url.includes('/item/new') && url.includes('marketplace=general');
  });

  if (newItemTab) return { tab: newItemTab, url: NEW_ITEM_URL };

  const anyVendooTab = allTabs[0];
  if (anyVendooTab) return { tab: anyVendooTab, url: NEW_ITEM_URL };

  return null;
}

async function openVendooListing(job) {
  try {
    const existing = await chrome.windows.getLastFocused();
    const win = await chrome.windows.create({
      url: 'https://web.vendoo.co/app/item/new?marketplace=general',
      focused: true,
      ...(existing && { left: existing.left + 30, top: existing.top + 30 }),
    });

    const tab = win.tabs[0];
    log(`Created new Vendoo window ${win.id} tab ${tab.id}`);

    activeJob.windowId = win.id;
    activeJob.tabId = tab.id;
    await persistActiveJob(activeJob);

    await sleep(3000);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: `Failed to open Vendoo: ${err.message}` };
  }
}

async function waitForContentScript(job) {
  const tabId = job.tabId || (activeJob && activeJob.tabId);
  if (!tabId) return { ok: false, error: 'No job tab stored' };

  const EXPECTED_VERSION = '0.3.0';

  for (let i = 0; i < 20; i++) {
    try {
      const resp = await chrome.tabs.sendMessage(tabId, { type: 'PING' });
      if (resp && resp.ok) {
        if (resp.contentScriptVersion !== EXPECTED_VERSION) {
          log(`Content script version mismatch: got ${resp.contentScriptVersion}, expected ${EXPECTED_VERSION}. Reload extension.`);
          return { ok: false, error: `Content script version mismatch (${resp.contentScriptVersion} vs ${EXPECTED_VERSION}). Reload extension at chrome://extensions/.` };
        }
        log(`Content script ready on tab ${tabId} v${resp.contentScriptVersion}`);
        return { ok: true };
      }
    } catch (e) {}

    await sleep(1000);
  }
  return { ok: false, error: 'Content script not ready after timeout' };
}

async function sendToVendoo(job, command) {
  const tabId = job.tabId || (activeJob && activeJob.tabId);
  if (!tabId) {
    return { ok: false, error: 'No job tab stored' };
  }
  try {
    const resp = await chrome.tabs.sendMessage(tabId, { ...command });
    return resp || { ok: false, error: 'No response' };
  } catch (err) {
    return { ok: false, error: `sendMessage failed: ${err.message}` };
  }
}

async function uploadPhotos(job) {
  const photos = job.photos || [];
  if (photos.length === 0) {
    return { ok: true };
  }

  const result = await sendToVendoo(job, {
    type: 'UPLOAD_PHOTOS',
    photos,
    studio_url: STUDIO_URL,
    job_id: job.job_id,
  });

  return result;
}

async function fillGeneral(job) {
  return sendToVendoo(job, {
    type: 'FILL_GENERAL',
    data: job.listing,
  });
}

async function saveGeneral(job) {
  return sendToVendoo(job, {
    type: 'SAVE_GENERAL',
  });
}

async function auditGeneral(job) {
  return sendToVendoo(job, {
    type: 'AUDIT_GENERAL',
    data: job.listing,
  });
}

async function fillMarketplace(job, platform) {
  return sendToVendoo(job, {
    type: 'FILL_MARKETPLACE',
    platform,
    data: job.listing,
  });
}

async function saveMarketplace(job, platform) {
  return sendToVendoo(job, {
    type: 'SAVE_MARKETPLACE',
    platform,
  });
}

async function auditMarketplace(job, platform) {
  return sendToVendoo(job, {
    type: 'AUDIT_MARKETPLACE',
    platform,
    data: job.listing,
  });
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// Existing popup message handlers (backward compatible)
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'GET_STUDIO_STATUS') {
    sendResponse({
      connected: paired,
      paired,
      active_job_id: activeJob?.job_id || null,
      active_job_step: activeJob?.current_step || null,
    });
    return true;
  }

  if (msg.type === 'PAIR_WITH_STUDIO') {
    const token = msg.token;
    if (token) {
      setPairingToken(token).then(() => {
        connect();
        sendResponse({ ok: true });
      });
    } else {
      sendResponse({ ok: false, error: 'No token provided' });
    }
    return true;
  }

  if (msg.type === 'OPEN_STUDIO') {
    chrome.tabs.create({ url: `${STUDIO_URL}/`, active: true });
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === 'IGNORE_PAIRING') {
    if (ws && ws.readyState === WebSocket.OPEN) {
      send({
        version: 1,
        type: 'extension.ready',
        message_id: Date.now().toString(36),
        sent_at: new Date().toISOString(),
        payload: { token: 'direct' },
      });
    }
    sendResponse({ ok: true });
    return true;
  }

  // Existing manual fill handlers
  if (msg.type === 'START_VENDOO' && msg.data) {
    startVendooFill(msg.data, 'vendoo', msg.tabId);
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === 'START_EBAY' && msg.data) {
    startVendooFill(msg.data, 'ebay', msg.tabId);
    sendResponse({ ok: true });
    return true;
  }
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
      .then(result => sendResponse({ ok: true, ...result }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg.type === 'FILL_COMPLETE') {
    chrome.runtime.sendMessage(msg).catch(() => {});
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === 'FILL_ERROR') {
    chrome.runtime.sendMessage(msg).catch(() => {});
    sendResponse({ ok: true });
    return true;
  }

  return false;
});

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
  let response = null;
  try {
    response = await chrome.tabs.sendMessage(tabId, { type: 'PING' });
  } catch (e) {}
  if (!response || !response.ok) {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content-scripts/vendoo.js'] });
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
    func: collectPageDiagnostics,
  });
  const result = execution?.result;
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

// Initialize
(async () => {
  await restoreActiveJob();
  connect();
})();
