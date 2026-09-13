const STUDIO_URL = 'http://127.0.0.1:4318';
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const HEARTBEAT_MS = 20000;
const DIAGNOSTIC_OUTBOX_KEY = 'studio_diagnostic_outbox';
const RELOAD_GENERATION_KEY = 'studio_reload_generation';
const RELOAD_TABS_KEY = 'studio_reload_tabs';
const EXTENSION_TAB_URLS = [
  'https://app.vendoo.co/*',
  'https://web.vendoo.co/*',
  'https://www.ebay.com/*',
  'https://poshmark.com/*',
  'https://www.mercari.com/*',
  'https://www.depop.com/*',
  'https://www.etsy.com/*',
];

let ws = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let paired = false;
let activeJob = null;
let activePatch = null;
let reconnectAttempt = 0;

importScripts('content-script-version.js');
importScripts('diagnostic-collector.js');
importScripts('preview-screencast.js');

var STUDIO_EXTENSION_BUILD = null;
try {
  importScripts('studio-build.js');
} catch (e) {}

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
  const stored = await chrome.storage.local.get(RELOAD_GENERATION_KEY);
  send({
    version: 1,
    type: 'extension.ready',
    message_id: crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36),
    sent_at: new Date().toISOString(),
    payload: identPayload(token, stored[RELOAD_GENERATION_KEY] || null),
  });
}

function identPayload(token, reloadGeneration) {
  const build = typeof STUDIO_EXTENSION_BUILD === 'string' ? STUDIO_EXTENSION_BUILD.trim() : '';
  return {
    token: token || 'direct',
    version: chrome.runtime.getManifest().version,
    build: build || null,
    reload_generation: reloadGeneration || null,
  };
}

async function reloadMarketplaceTabs() {
  const tabs = await chrome.tabs.query({ url: EXTENSION_TAB_URLS });
  for (const tab of tabs) {
    if (!tab.id) continue;
    try {
      await chrome.tabs.reload(tab.id);
    } catch (err) {
      error(`Tab reload failed: ${err.message}`);
    }
  }
}

async function handleExtensionReload(generation) {
  const stored = { [RELOAD_TABS_KEY]: true };
  if (generation) {
    stored[RELOAD_GENERATION_KEY] = generation;
  }
  await chrome.storage.local.set(stored);
  await persistActiveJob(null);
  log('Reloading extension after Studio update');
  chrome.runtime.reload();
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
        vendoo_item_id: payload.vendoo_item_id || payload.options?.vendoo_item_id || null,
        vendoo_url: payload.vendoo_url || payload.options?.vendoo_url || null,
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

    case 'job.fill_fields': {
      const payload = msg.payload || {};
      const jobId = msg.job_id || payload.job_id;
      if (!jobId) {
        log('job.fill_fields missing job_id');
        return;
      }
      await runFillFields(jobId, payload);
      break;
    }

    case 'job.vendoo_get': {
      const payload = msg.payload || {};
      const jobId = msg.job_id || payload.job_id;
      if (!payload.request_id) {
        log('job.vendoo_get missing request_id');
        return;
      }
      await runVendooGet(jobId, payload);
      break;
    }

    case 'job.search_categories': {
      const payload = msg.payload || {};
      const jobId = msg.job_id || payload.job_id;
      if (!payload.request_id) {
        log('job.search_categories missing request_id');
        return;
      }
      await runSearchCategories(jobId, payload);
      break;
    }

    case 'job.open_listing': {
      const payload = msg.payload || {};
      const opened = await focusVendooListing(payload);
      if (!opened.ok) {
        log(`job.open_listing failed: ${opened.error || 'unknown error'}`);
      }
      break;
    }

    case 'job.retry': {
      const jobId = msg.job_id || msg.payload?.job_id;
      if (!jobId) return;

      if (activeJob && activeJob.job_id === jobId) {
        activeJob.attempt = (activeJob.attempt || 0) + 1;
        const resumeFrom = String(
          msg.payload?.resumeFrom || activeJob.current_step || ''
        ).trim();
        activeJob.options = {
          ...(activeJob.options || {}),
          ...(resumeFrom ? { resumeFrom } : {}),
        };
        await persistActiveJob(activeJob);
        runJob(jobId);
      }
      break;
    }

    case 'job.cancel': {
      const jobId = msg.job_id || msg.payload?.job_id;
      if (!jobId) return;

      if (activePatch && activePatch.job_id === jobId) {
        const tabId = activePatch.tabId;
        activePatch = null;
        await stopJobPreview();
        send({
          version: 1,
          type: 'job.cancelled',
          job_id: jobId,
          message_id: Date.now().toString(36),
          sent_at: new Date().toISOString(),
          payload: { cancelled_at: 'filling_fields' },
        });
        await closeListingTab(tabId);
        return;
      }

      if (activeJob && activeJob.job_id === jobId) {
        const csJob = activeJob;
        const tabId = csJob.tabId;
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
        await closeListingTab(tabId);
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

    case 'extension.reload':
      await handleExtensionReload(msg.payload?.generation);
      break;
  }
}

function marketplaceFromStep(step) {
  const match = String(step || '').match(/^(?:clearing|filling|saving|auditing)_(.+)$/i);
  if (!match) return 'general';
  const platform = String(match[1] || '').toLowerCase();
  if (!platform || platform === 'general') return 'general';
  return platform;
}

function selectJobSteps(job, steps) {
  const allSteps = Array.isArray(steps) ? steps : [];
  const resumeFrom = String(job?.options?.resumeFrom || job?.resume_from || '').trim();
  if (!resumeFrom) return allSteps;

  const resumeIdx = allSteps.findIndex((step) => step.step === resumeFrom);
  if (resumeIdx < 0) {
    log(`resumeFrom=${resumeFrom} not in pipeline; running full job`);
    return allSteps;
  }

  const prefix = allSteps.filter((step) => (
    step.step === 'opening_vendoo' || step.step === 'waiting_ready'
  ));
  const prefixNames = new Set(prefix.map((step) => step.step));
  const resumed = allSteps.slice(resumeIdx).filter((step) => !prefixNames.has(step.step));
  log(`Resuming job at ${resumeFrom} (${resumed.length} step(s) after open/ready)`);
  return [...prefix, ...resumed];
}

async function runJob(jobId) {
  if (!activeJob || activeJob.job_id !== jobId) {
    return;
  }

  const steps = selectJobSteps(activeJob, buildJobSteps(activeJob));

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
          schema: result.schema || null,
          categories: result.categories || null,
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
    const tabId = activeJob?.tabId;
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
    await closeListingTab(tabId);
  }
}

function buildJobSteps(job) {
  const steps = [];
  const clearBeforeFill = Boolean(job.options?.clearBeforeFill);

  steps.push({ step: 'opening_vendoo', fn: openVendooListing });
  steps.push({ step: 'waiting_ready', fn: waitForContentScript });
  if (!job.options?.skipPhotos) {
    steps.push({ step: 'uploading_photos', fn: uploadPhotos });
  }
  if (clearBeforeFill) {
    steps.push({ step: 'clearing_general', fn: clearGeneral });
  }
  steps.push({ step: 'filling_general', fn: fillGeneral });
  steps.push({ step: 'saving_general', fn: saveGeneral });
  steps.push({ step: 'auditing_general', fn: auditGeneral });

  const platforms = job.options?.platforms || [];
  // After General category is committed, align each marketplace category and
  // scrape the live field schema before filling values.
  if (platforms.length) {
    steps.push({ step: 'discovering_schema', fn: discoverSchema });
  }
  for (const platform of platforms) {
    if (clearBeforeFill) {
      steps.push({ step: `clearing_${platform}`, fn: (j) => clearMarketplace(j, platform) });
    }
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
  return !!(tab && tab.status === 'complete' && isVendooUrl(tab.url));
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
  const webTabs = await chrome.tabs.query({ url: 'https://web.vendoo.co/*' });
  const appTabs = await chrome.tabs.query({ url: 'https://app.vendoo.co/*' });
  return [...webTabs, ...appTabs].find(t => isNewItemUrl(t.url)) || null;
}

function extractItemIdFromUrl(url) {
  try {
    const match = new URL(url).pathname.match(/\/item\/([^/?]+)/);
    return match && match[1] !== 'new' ? match[1] : '';
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
    const created = await chrome.tabs.create({ url, active: foreground });
    if (foreground && created.windowId != null) await showWindow(created.windowId);
    return { ok: true, tabId: created.id, windowId: created.windowId };
  }
}

async function focusVendooListing(payload) {
  const itemUrl = payload.vendoo_url || (payload.vendoo_item_id
    ? `https://web.vendoo.co/app/item/${payload.vendoo_item_id}`
    : '');
  const url = itemUrl || 'https://web.vendoo.co/app';
  const itemId = payload.vendoo_item_id || extractItemIdFromUrl(url);
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
    const created = await chrome.tabs.create({ url, active: true });
    if (created.windowId != null) {
      await showWindow(created.windowId);
    }
    return { ok: true, tabId: created.id, windowId: created.windowId };
  }
}

async function openListingForPatch(payload, { reload = true, preview = true, marketplace = '' } = {}) {
  let url = payload.vendoo_url || (payload.vendoo_item_id
    ? `https://web.vendoo.co/app/item/${payload.vendoo_item_id}`
    : null);
  if (!url) {
    return { ok: false, error: 'No Vendoo draft URL. Send the listing first.' };
  }
  if (marketplace) url = withMarketplaceQuery(url, marketplace);
  const itemId = payload.vendoo_item_id || extractItemIdFromUrl(url);
  const existing = await findTabByDraft(url, itemId);
  let currentUrl = existing?.url || '';
  if (existing?.id) {
    try {
      const current = await chrome.tabs.get(existing.id);
      currentUrl = current.url || currentUrl;
    } catch (_) {}
  }
  const samePage = Boolean(existing?.id) && listingUrlsMatch(currentUrl, url);
  const opened = await openVisibleVendooWindow(samePage ? null : url, existing);
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

async function runFillFields(jobId, payload) {
  if (activeJob) {
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { step: 'filling_fields', error: 'Another fill is already running' },
    });
    return;
  }

  const opened = await openListingForPatch({ ...payload, job_id: jobId });
  if (!opened.ok) {
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { step: 'filling_fields', error: opened.error },
    });
    return;
  }

  const job = { job_id: jobId, tabId: opened.tabId };
  activePatch = job;
  send({
    version: 1,
    type: 'job.progress',
    job_id: jobId,
    message_id: Date.now().toString(36),
    sent_at: new Date().toISOString(),
    payload: { step: 'filling_fields' },
  });

  const ready = await waitForContentScript(job);
  if (!ready.ok) {
    activePatch = null;
    await stopJobPreview();
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { step: 'filling_fields', error: ready.error },
    });
    return;
  }

  const formReady = await sendToVendoo(job, { type: 'WAIT_FOR_FORM', timeoutMs: 30000 });
  if (!formReady?.ok) {
    activePatch = null;
    await stopJobPreview();
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: {
        step: 'filling_fields',
        error: formReady?.error || 'Vendoo listing form did not finish loading',
      },
    });
    return;
  }

  const batches = groupFillFieldBatches(payload.fields || []);
  const batchResults = [];
  let lastSaved = null;
  log(`Filling leftover fields in ${batches.length} batch(es)`);

  for (let i = 0; i < batches.length; i++) {
    const fields = batches[i];
    const marketplace = fields[0]?.marketplace || 'general';
    send({
      version: 1,
      type: 'job.progress',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: {
        step: 'filling_fields',
        marketplace,
        batch: i + 1,
        batch_count: batches.length,
        field_count: fields.length,
      },
    });
    const result = await sendToVendoo(job, {
      type: 'FILL_FIELDS',
      fields,
    });
    batchResults.push(result);
    log(`Saving leftover ${marketplace} form`);
    const saved = await sendToVendoo(job, saveCommandForMarketplace(marketplace));
    lastSaved = saved;
    if (!result.ok || !saved.ok) {
      activePatch = null;
      await stopJobPreview();
      send({
        version: 1,
        type: 'job.step_failed',
        job_id: jobId,
        message_id: Date.now().toString(36),
        sent_at: new Date().toISOString(),
        payload: {
          step: 'filling_fields',
          error: !result.ok
            ? (result.error || 'Leftover field fill failed')
            : (saved.error || 'Filled fields, but Vendoo did not save the draft'),
          fill_log: mergeFillLogs(batchResults),
        },
      });
      return;
    }
  }

  const fillLog = mergeFillLogs(batchResults);
  activePatch = null;
  await stopJobPreview();
  await sleep(1500);

  send({
    version: 1,
    type: 'job.step_completed',
    job_id: jobId,
    message_id: Date.now().toString(36),
    sent_at: new Date().toISOString(),
    payload: {
      step: 'filling_fields',
      vendoo_item_id: lastSaved?.vendoo_item_id || payload.vendoo_item_id || null,
      vendoo_url: lastSaved?.vendoo_url || payload.vendoo_url || null,
      fill_log: fillLog,
    },
  });
  await closeListingTab(job.tabId);
}

function groupFillFieldBatches(fields) {
  const grouped = new Map();
  for (const item of Array.isArray(fields) ? fields : []) {
    const marketplace = String(item?.marketplace || 'general').toLowerCase();
    if (!grouped.has(marketplace)) grouped.set(marketplace, []);
    grouped.get(marketplace).push(item);
  }
  const batches = [];
  const chunkSize = 25;
  for (const group of grouped.values()) {
    for (let i = 0; i < group.length; i += chunkSize) {
      batches.push(group.slice(i, i + chunkSize));
    }
  }
  return batches.length ? batches : [[]];
}

function mergeFillLogs(results) {
  const entries = [];
  for (const result of results) {
    const log = result && result.fill_log;
    if (log && Array.isArray(log.entries)) entries.push(...log.entries);
  }
  if (!entries.length) return null;
  return {
    marketplace: entries[0].marketplace || 'general',
    entries,
  };
}

function saveCommandForMarketplace(marketplace) {
  const platform = String(marketplace || 'general').toLowerCase();
  if (platform && platform !== 'general' && platform !== 'unknown') {
    return { type: 'SAVE_MARKETPLACE', platform };
  }
  return { type: 'SAVE_GENERAL' };
}

function commandTimeoutMs(command) {
  if (command.type === 'FILL_FIELDS') {
    const count = Array.isArray(command.fields) ? command.fields.length : 0;
    return Math.min(300000, Math.max(90000, 30000 + count * 5000));
  }
  if (command.type === 'WAIT_FOR_FORM') {
    return Math.max(35000, Number(command.timeoutMs) || 30000) + 5000;
  }
  // Full marketplace fills (esp. Etsy category specifics) routinely exceed 90s.
  // Leftover FILL_FIELDS already scales up to 300s; keep the bulk fill in the same range.
  if (command.type === 'FILL_GENERAL' || command.type === 'FILL_MARKETPLACE') {
    return 180000;
  }
  if (command.type === 'CLEAR_GENERAL' || command.type === 'CLEAR_MARKETPLACE') {
    return 90000;
  }
  if (command.type === 'SAVE_GENERAL' || command.type === 'SAVE_MARKETPLACE') {
    return 60000;
  }
  if (command.type === 'DISCOVER_SCHEMA') {
    const count = Array.isArray(command.platforms) ? command.platforms.length : 5;
    return Math.min(180000, Math.max(120000, 30000 + count * 25000));
  }
  if (command.type === 'GET_VENDOO_ITEM') {
    return 120000;
  }
  if (command.type === 'SEARCH_CATEGORIES') {
    return 45000;
  }
  if (command.type === 'UPLOAD_PHOTOS') {
    const count = Array.isArray(command.files) ? command.files.length : 0;
    return Math.min(180000, Math.max(60000, 20000 + count * 10000));
  }
  return 45000;
}

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
  const itemId = wantedId && wantedId !== 'new' ? wantedId : (fromUrl && fromUrl !== 'new' ? fromUrl : '');
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
  try {
    const [execution] = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: readVendooItemInPage,
      args: [itemId || ''],
    });
    return execution?.result || { ok: false, error: 'No result from the Vendoo page' };
  } catch (err) {
    return { ok: false, error: `Page read failed: ${err.message}` };
  }
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

  let tabId = null;
  const existingTabId = activePatch?.tabId || activeJob?.tabId || null;
  if (existingTabId) {
    try {
      const tab = await chrome.tabs.get(existingTabId);
      const currentId = extractItemIdFromUrl(tab.url || '');
      const wantId = payload.vendoo_item_id || extractItemIdFromUrl(payload.vendoo_url || '');
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
  const itemId = payload.vendoo_item_id || extractItemIdFromUrl(payload.vendoo_url || '');
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
      const wantId = payload.vendoo_item_id || extractItemIdFromUrl(payload.vendoo_url || '');
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
  const result = await sendToVendoo(job, { type: 'SEARCH_CATEGORIES', query });
  reply({
    ok: Boolean(result?.ok),
    query,
    path: result?.path || '',
    matches: Array.isArray(result?.matches) ? result.matches : [],
    error: result?.ok ? null : (result?.error || 'Could not search Vendoo categories'),
  });
}

async function openVendooListing(job) {
  try {
    const reuseId = job.vendoo_item_id || job.options?.vendoo_item_id;
    const reuseUrl = job.vendoo_url || job.options?.vendoo_url || (reuseId
      ? `https://web.vendoo.co/app/item/${reuseId}`
      : null);
    if (reuseId || reuseUrl) {
      const resumeMarketplace = marketplaceFromStep(job.options?.resumeFrom);
      const opened = await openListingForPatch({
        job_id: job.job_id,
        vendoo_item_id: reuseId,
        vendoo_url: reuseUrl,
      }, { reload: true, preview: true, marketplace: resumeMarketplace });
      if (!opened.ok) return opened;
      const tab = await chrome.tabs.get(opened.tabId);
      activeJob.windowId = tab.windowId;
      activeJob.tabId = opened.tabId;
      activeJob.vendoo_item_id = reuseId || extractItemIdFromUrl(tab.url || reuseUrl || '');
      activeJob.vendoo_url = reuseUrl || tab.url;
      await persistActiveJob(activeJob);
      return {
        ok: true,
        vendoo_item_id: activeJob.vendoo_item_id,
        vendoo_url: activeJob.vendoo_url,
      };
    }

    const existingTab = await findNewItemTab();
    if (existingTab) {
      log(`Reloading new-item tab ${existingTab.id} -> ${NEW_ITEM_URL}`);
      const tab = await openEverydayListingTab(NEW_ITEM_URL, existingTab);
      activeJob.windowId = tab.windowId;
      activeJob.tabId = tab.id;
      await persistActiveJob(activeJob);
      await waitForTabComplete(tab.id);
      await startJobPreview(tab.id, job.job_id);
      return { ok: true };
    }

    const tab = await openEverydayListingTab(NEW_ITEM_URL);
    log(`Opened Vendoo tab ${tab.id} in everyday Chrome window ${tab.windowId}`);

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
  let reloaded = false;
  let lastUrl = tab.url;
  for (let i = 0; i < 20; i++) {
    const resp = await pingContentScript(tabId);
    if (resp && resp.ok) {
      if (resp.contentScriptVersion === CONTENT_SCRIPT_VERSION) {
        log(`Content script ready on tab ${tabId} v${resp.contentScriptVersion}`);
        return { ok: true };
      }
      log(`Content script version mismatch: got ${resp.contentScriptVersion}, expected ${CONTENT_SCRIPT_VERSION}`);
      if (!reloaded) {
        log(`Reloading Vendoo tab ${tabId} to pick up the current content script`);
        const reloadedTab = await reloadTabAndWait(tabId);
        reloaded = true;
        injected = false;
        if (!isTabReady(reloadedTab)) {
          return { ok: false, error: `Vendoo tab did not finish reloading (${reloadedTab?.url || 'unknown url'})` };
        }
        lastUrl = reloadedTab.url;
        continue;
      }
      log(`Content script still at v${resp.contentScriptVersion} after reload; continuing`);
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
  const timeoutMs = commandTimeoutMs(command);
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

async function clearGeneral(job) {
  return sendToVendoo(job, { type: 'CLEAR_GENERAL' });
}

async function clearMarketplace(job, platform) {
  return sendToVendoo(job, { type: 'CLEAR_MARKETPLACE', platform });
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunks = [];
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    chunks.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize)));
  }
  return btoa(chunks.join(''));
}

function photoFetchTimeoutSignal() {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(30000);
  }
  return undefined;
}

async function fetchStudioPhotoFiles(jobId, photos) {
  const files = [];
  const errors = [];
  for (const photo of photos) {
    const photoId = photo.id || photo.stored_filename || photo.name;
    if (!photoId) {
      errors.push('Photo is missing an id');
      continue;
    }
    const url = `${STUDIO_URL}/api/jobs/${jobId}/photos/${encodeURIComponent(photoId)}`;
    try {
      const response = await fetch(url, { signal: photoFetchTimeoutSignal() });
      if (!response.ok) {
        errors.push(`${photoId}: HTTP ${response.status}`);
        continue;
      }
      const buffer = await response.arrayBuffer();
      files.push({
        name: photo.name || photo.original_filename || 'photo.jpg',
        type: response.headers.get('content-type') || photo.mime_type || 'image/jpeg',
        data: arrayBufferToBase64(buffer),
      });
    } catch (err) {
      errors.push(`${photoId}: ${err.message}`);
    }
  }
  return { files, errors };
}

async function uploadPhotos(job) {
  if (job.options?.skipPhotos) {
    return { ok: true };
  }
  if (job.vendoo_item_id) {
    log(`Draft ${job.vendoo_item_id} already exists, skipping photo upload`);
    return { ok: true };
  }
  const photos = job.photos || [];
  if (photos.length === 0) {
    return { ok: true };
  }

  const { files, errors } = await fetchStudioPhotoFiles(job.job_id, photos);
  if (errors.length) {
    log(`Studio photo fetch failed: ${errors.join('; ')}`);
  }
  if (files.length === 0) {
    const detail = errors.length ? `: ${errors.join('; ')}` : '';
    return { ok: false, error: `No photos could be fetched${detail}` };
  }

  return sendToVendoo(job, {
    type: 'UPLOAD_PHOTOS',
    files,
  });
}

async function fillGeneral(job) {
  return sendToVendoo(job, {
    type: 'FILL_GENERAL',
    data: job.listing,
    registry_selectors: job.registry_selectors || {},
  });
}

async function discoverSchema(job) {
  const platforms = job.options?.platforms || [];
  const result = await sendToVendoo(job, {
    type: 'DISCOVER_SCHEMA',
    data: job.listing,
    platforms,
  });
  if (result?.ok && result.schema) {
    job.discovered_schema = result.schema;
    await persistActiveJob(job);
  }
  return result;
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

  if (msg.type === 'IMPORT_VENDOO_LISTING') {
    importVendooListing(msg.tabId).then(sendResponse).catch((err) => {
      sendResponse({ ok: false, error: err.message });
    });
    return true;
  }

  if (msg.type === 'IGNORE_PAIRING') {
    if (ws && ws.readyState === WebSocket.OPEN) {
      chrome.storage.local.get(RELOAD_GENERATION_KEY).then((stored) => {
        send({
          version: 1,
          type: 'extension.ready',
          message_id: Date.now().toString(36),
          sent_at: new Date().toISOString(),
            payload: identPayload('direct', stored[RELOAD_GENERATION_KEY] || null),
        });
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
  const stored = await chrome.storage.local.get(RELOAD_TABS_KEY);
  if (stored[RELOAD_TABS_KEY]) {
    await chrome.storage.local.remove(RELOAD_TABS_KEY);
    await reloadMarketplaceTabs();
  }
  await restoreActiveJob();
  connect();
})();
