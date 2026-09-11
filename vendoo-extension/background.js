const STUDIO_URL = 'http://127.0.0.1:4318';
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const HEARTBEAT_MS = 20000;
const DIAGNOSTIC_OUTBOX_KEY = 'studio_diagnostic_outbox';
const CONTENT_SCRIPT_VERSION = '0.3.6';

let ws = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let paired = false;
let activeJob = null;
let reconnectAttempt = 0;

importScripts('diagnostic-collector.js');
importScripts('preview-screencast.js');

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
    if (activeJob.tabId && activeJob.job_id) {
      startJobPreview(activeJob.tabId, activeJob.job_id);
    }
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
    sendPendingObservations();
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      Promise.resolve(handleStudioMessage(msg)).catch((err) => {
        error(`Failed to handle message: ${err.message}`);
      });
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

function generateObservationId() {
  const ts = Date.now().toString(36);
  const rand = Array.from({ length: 8 }, () => Math.random().toString(36)[2]).join('');
  return `obs-${ts}-${rand}`;
}

async function queueObservation(obs) {
  const stored = await chrome.storage.local.get(DIAGNOSTIC_OUTBOX_KEY);
  const outbox = stored[DIAGNOSTIC_OUTBOX_KEY] || [];
  outbox.push(obs);
  if (outbox.length > 200) {
    outbox.splice(0, outbox.length - 200);
  }
  await chrome.storage.local.set({ [DIAGNOSTIC_OUTBOX_KEY]: outbox });
}

async function removeObservation(obsId) {
  const stored = await chrome.storage.local.get(DIAGNOSTIC_OUTBOX_KEY);
  const outbox = (stored[DIAGNOSTIC_OUTBOX_KEY] || []).filter(o => o.observation_id !== obsId);
  await chrome.storage.local.set({ [DIAGNOSTIC_OUTBOX_KEY]: outbox });
}

async function sendPendingObservations() {
  const stored = await chrome.storage.local.get(DIAGNOSTIC_OUTBOX_KEY);
  const outbox = stored[DIAGNOSTIC_OUTBOX_KEY] || [];
  if (outbox.length === 0) return;
  log(`Sending ${outbox.length} pending diagnostic observations`);
  for (const obs of outbox) {
    send({
      version: 1,
      type: 'diagnostic.observed',
      job_id: obs.job_id,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: obs,
    });
  }
}

async function collectDiagnostics(mode) {
  const tabId = activeJob?.tabId;
  if (!tabId) {
    log('No tabId for diagnostic collection');
    return;
  }
  try {
    const [execution] = await chrome.scripting.executeScript({
      target: { tabId },
      func: collectPageDiagnostics,
      args: [{ mode }],
    });
    const result = execution?.result;
    if (!result) {
      log('Diagnostic returned no data');
      return;
    }

    const observationId = generateObservationId();
    const listing = activeJob?.listing || {};
    const obs = {
      observation_id: observationId,
      job_id: activeJob.job_id,
      step: activeJob.current_step || '',
      category_path: listing.category_path || '',
      collector_version: result.collectorVersion || 'unknown',
      mode,
      url: result.url || '',
      title: result.title || '',
      timestamp: result.timestamp || new Date().toISOString(),
      field_count: result.fieldCount || 0,
      dropdown_count: result.dropdownCount || 0,
      dropdowns_with_options: result.dropdownsWithOptions || 0,
      live_dropdowns_with_options: result.liveDropdownsWithOptions || 0,
      total_dropdown_options: result.totalDropdownOptions || 0,
      expanded_sections: result.expandedSections || [],
      headings: result.headings || [],
      fields: (result.fields || []).map(f => ({
        label: f.label || '',
        label_sources: f.labelSources || [],
        section_path: f.sectionPath || [],
        selector: f.selector || '',
        tag: f.tag || '',
        control_type: f.type || '',
        role: f.role || '',
        name: f.name || '',
        control_id: f.id || '',
        placeholder: f.placeholder || '',
        classes: f.classes || '',
        is_dropdown: f.isDropdown || false,
        option_count: f.optionCount || 0,
        options: f.options || [],
        options_source: f.optionsSource || 'unknown',
      })),
    };

    await queueObservation(obs);

    send({
      version: 1,
      type: 'diagnostic.observed',
      job_id: obs.job_id,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: obs,
    });

    log(`Collected ${obs.field_count} fields in ${mode} mode, obs=${observationId}`);
  } catch (err) {
    error(`Diagnostic collection failed: ${err.message}`);
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
        registry_selectors: payload.registry_selectors || {},
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
        await stopJobPreview();

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

    case 'diagnostic.ack': {
      const obsId = msg.payload?.observation_id;
      if (obsId) {
        await removeObservation(obsId);
        log(`Diagnostic ack: ${obsId}`);
      }
      break;
    }
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
        collectDiagnostics('passive');
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
            fill_log: result.fill_log || null,
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
          fill_log: result.fill_log || null,
        },
      });

      if (step.step.startsWith('auditing_')) {
        collectDiagnostics('active');
      }

      if (result.vendoo_item_id && !activeJob.vendoo_item_id) {
        activeJob.vendoo_item_id = result.vendoo_item_id;
        await persistActiveJob(activeJob);
      }
    } catch (err) {
      failed = true;
      collectDiagnostics('passive');
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
    await stopJobPreview();

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

function isTabReady(tab) {
  return !!(tab && tab.status === 'complete' && isVendooUrl(tab.url));
}

async function waitForTabComplete(tabId, timeoutMs = 30000) {
  try {
    const current = await chrome.tabs.get(tabId);
    if (isTabReady(current)) return current;
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
      if (id === tabId && isTabReady(tab)) finish(tab);
    }

    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.get(tabId).then((tab) => {
      if (isTabReady(tab)) finish(tab);
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
    files: ['content-scripts/vendoo.js'],
  });
}

async function findNewItemTab() {
  const webTabs = await chrome.tabs.query({ url: 'https://web.vendoo.co/*' });
  const appTabs = await chrome.tabs.query({ url: 'https://app.vendoo.co/*' });
  return [...webTabs, ...appTabs].find(t => isNewItemUrl(t.url)) || null;
}

async function openVendooListing(job) {
  try {
    const existingTab = await findNewItemTab();
    if (existingTab) {
      log(`Reloading new-item tab ${existingTab.id} -> ${NEW_ITEM_URL}`);
      activeJob.windowId = existingTab.windowId;
      activeJob.tabId = existingTab.id;
      await persistActiveJob(activeJob);
      await waitForTabComplete(existingTab.id);
      await startJobPreview(existingTab.id, job.job_id);
      return { ok: true };
    }

    const existing = await chrome.windows.getLastFocused();
    const tab = await chrome.tabs.create({
      windowId: existing?.id,
      url: NEW_ITEM_URL,
      active: true,
    });
    log(`Created Vendoo tab ${tab.id} in window ${tab.windowId}`);

    activeJob.windowId = tab.windowId;
    activeJob.tabId = tab.id;
    await persistActiveJob(activeJob);

    const loaded = await waitForTabComplete(tab.id);
    await startJobPreview(tab.id, job.job_id);
    if (!isTabReady(loaded)) {
      return { ok: false, error: `Vendoo tab did not finish loading (${loaded?.url || 'unknown url'})` };
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, error: `Failed to open Vendoo: ${err.message}` };
  }
}

async function waitForContentScript(job) {
  const tabId = job.tabId || (activeJob && activeJob.tabId);
  if (!tabId) return { ok: false, error: 'No job tab stored' };

  const tab = await waitForTabComplete(tabId);
  if (!isTabReady(tab)) {
    return { ok: false, error: `Vendoo tab not ready (${tab?.url || 'unknown url'})` };
  }

  let injected = false;
  let lastUrl = tab.url;
  for (let i = 0; i < 20; i++) {
    const resp = await pingContentScript(tabId);
    if (resp && resp.ok) {
      if (resp.contentScriptVersion !== CONTENT_SCRIPT_VERSION) {
        log(`Content script version mismatch: got ${resp.contentScriptVersion}, expected ${CONTENT_SCRIPT_VERSION}. Reload extension and the Vendoo tab.`);
        return { ok: false, error: `Content script is stale (${resp.contentScriptVersion} vs ${CONTENT_SCRIPT_VERSION}). Reload the extension at chrome://extensions/, then refresh the Vendoo tab.` };
      }
      log(`Content script ready on tab ${tabId} v${resp.contentScriptVersion}`);
      return { ok: true };
    }

    try {
      const current = await chrome.tabs.get(tabId);
      if (current.url && current.url !== lastUrl) {
        log(`Vendoo tab navigated ${lastUrl} -> ${current.url}`);
        lastUrl = current.url;
        injected = false;
      }
    } catch (err) {
      return { ok: false, error: `Vendoo tab closed: ${err.message}` };
    }

    if (!injected) {
      try {
        await injectVendooContentScript(tabId);
        injected = true;
        log(`Injected content script into tab ${tabId}`);
      } catch (err) {
        log(`Content script inject failed on tab ${tabId}: ${err.message}`);
      }
    }

    await sleep(1000);
  }
  return { ok: false, error: 'Content script not ready after timeout' };
}

async function sendToVendoo(job, command) {
  const tabId = job.tabId || (activeJob && activeJob.tabId);
  if (!tabId) {
    return { ok: false, error: 'No job tab stored' };
  }
  const timeoutMs = command.type === 'FILL_GENERAL' || command.type === 'FILL_MARKETPLACE'
    ? 90000
    : 45000;
  try {
    const resp = await Promise.race([
      chrome.tabs.sendMessage(tabId, { ...command }),
      sleep(timeoutMs).then(() => ({
        ok: false,
        error: `${command.type} timed out after ${timeoutMs / 1000}s`,
      })),
    ]);
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
    registry_selectors: job.registry_selectors || {},
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
    registry_selectors: job.registry_selectors || {},
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
