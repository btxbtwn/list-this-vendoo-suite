importScripts('category-reader.js');
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
importScripts('background/tabs.js');
importScripts('background/fill-fields.js');
importScripts('background/vendoo-item.js');
importScripts('background/vendoo-api.js');
importScripts('background/job-steps.js');
importScripts('background/import-listing.js');
importScripts('background/popup-actions.js');
importScripts('browser-session.js');

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

async function fetchStudioPairingToken() {
  const resp = await fetch(`${STUDIO_URL}/api/extension/pairing-token`);
  if (!resp.ok) throw new Error(`pairing-token HTTP ${resp.status}`);
  const data = await resp.json();
  const token = String(data?.token || '').trim();
  if (!token || token === 'direct') throw new Error('Studio returned an invalid pairing token');
  await setPairingToken(token);
  return token;
}

async function resolvePairingToken() {
  const stored = await getPairingToken();
  if (stored && stored !== 'direct') return stored;
  return fetchStudioPairingToken();
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
      if (msg.type === 'error' && /invalid pairing token/i.test(String(msg.message || ''))) {
        fetchStudioPairingToken().then(() => sendIdent()).catch((err) => {
          error(`Pairing token refresh failed: ${err.message}`);
        });
        return;
      }
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
  let token;
  try {
    token = await resolvePairingToken();
  } catch (err) {
    error(`Pairing token is unavailable: ${err.message}`);
    return;
  }
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
    token: token || '',
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

      if (payload.options?.publish !== false) {
        send({
          version: 1,
          type: 'job.step_failed',
          job_id: jobId,
          message_id: Date.now().toString(36),
          sent_at: new Date().toISOString(),
          payload: { step: 'queued', error: 'Publishing is not supported; publish must be false' },
        });
        return;
      }

      if (activePatch || (activeJob && activeJob.job_id !== jobId)) {
        send({
          version: 1,
          type: 'job.step_failed',
          job_id: jobId,
          message_id: Date.now().toString(36),
          sent_at: new Date().toISOString(),
          payload: { step: 'queued', error: 'Another automation job is already running' },
        });
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
        registry_options: payload.registry_options || {},
        vendoo_item_id: durableItemId(payload.vendoo_item_id || payload.options?.vendoo_item_id) || null,
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

    case 'catalog.read_children': {
      let result;
      try {
        if (activeJob || activePatch) throw new Error('Another automation job is already running');
        const tabs = await chrome.tabs.query({url: ['https://web.vendoo.co/*', 'https://app.vendoo.co/*']});
        const tab = tabs.find(tab => /\/app(?:\/|$)/.test(new URL(tab.url).pathname));
        if (!tab) throw new Error('Open Vendoo in Chrome before extracting categories');
        const results = await chrome.scripting.executeScript({target: {tabId: tab.id}, world: 'MAIN',
          func: readVendooCategoryChildren, args: [msg.payload.marketplace, msg.payload.parent_id]});
        result = results[0]?.result || {ok: false, error: 'No response from Vendoo'};
      } catch (error) {
        result = {ok: false, error: error.message};
      }
      send({type: 'catalog.children', payload: {...result, request_id: msg.payload.request_id}});
      break;
    }

    case 'extension.reload':
      await handleExtensionReload(msg.payload?.generation);
      break;

    case 'browser.open':
    case 'browser.close':
    case 'browser.input':
    case 'browser.pick':
    case 'browser.snapshot':
    case 'browser.act':
      await handleBrowserMessage(msg);
      break;
  }
}

function marketplaceFromStep(step) {
  const match = String(step || '').match(/^(?:clearing|filling|saving|auditing)_(.+)$/i);
  if (!match) return 'general';
  const platform = String(match[1] || '').toLowerCase();
  // Combined post-fill steps are not a real Vendoo marketplace tab.
  if (!platform || platform === 'general' || platform === 'marketplaces') return 'general';
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
    step.step === 'opening_vendoo'
    || step.step === 'waiting_ready'
    || step.step === 'checking_draft_safety'
  ));
  const prefixNames = new Set(prefix.map((step) => step.step));
  const resumed = allSteps.slice(resumeIdx).filter((step) => !prefixNames.has(step.step));
  log(`Resuming job at ${resumeFrom} (${resumed.length} step(s) after preflight)`);
  return [...prefix, ...resumed];
}

async function runJob(jobId) {
  try {
    await runJobSteps(jobId);
  } catch (error) {
    await releaseFailedJob(jobId);
    send({type: 'job.step_failed', job_id: jobId,
      payload: {step: 'automation', error: error.message || 'Automation failed'}});
  } finally {
    await releaseFailedJob(jobId);
  }
}

async function runJobSteps(jobId) {
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

    const stepStartedAt = Date.now();
    try {
      const result = await step.fn(activeJob);
      const durationMs = Date.now() - stepStartedAt;
      if (!result.ok && activeJob.options?.mode !== 'schema_probe'
          && step.step.startsWith('saving_') && durableItemId(activeJob.vendoo_item_id)) {
        // A required field may prevent saving. Read the persisted draft and let
        // Studio resolve its gaps before attempting another targeted fill.
        log(`Save needs repair: ${result.error || step.step}`);
        break;
      }
      if (!result.ok && !step.step.startsWith('auditing_')) {
        failed = true;
        collectDiagnostics('passive');
        await releaseFailedJob(jobId);
        send({
          version: 1,
          type: 'job.step_failed',
          job_id: jobId,
          message_id: Date.now().toString(36),
          sent_at: new Date().toISOString(),
          payload: {
            step: step.step,
            duration_ms: durationMs,
            error: result.error || 'Step failed',
            fields: result.fields || {},
            schema: result.schema || null,
            categories: result.categories || null,
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
          duration_ms: durationMs,
          skipped: Boolean(result.skipped),
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

      // Discover already set marketplace categories; fill can skip re-picking them.
      if (step.step === 'discovering_schema' && result.ok) {
        activeJob.categoriesAligned = true;
      }

      if (result.vendoo_item_id && !activeJob.vendoo_item_id) {
        activeJob.vendoo_item_id = result.vendoo_item_id;
        await persistActiveJob(activeJob);
      }
      if (result.vendoo_url && extractItemIdFromUrl(result.vendoo_url)) {
        activeJob.vendoo_url = result.vendoo_url;
        await persistActiveJob(activeJob);
      }
    } catch (err) {
      failed = true;
      collectDiagnostics('passive');
      await releaseFailedJob(jobId);
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

  if (!activeJob || activeJob.job_id !== jobId) {
    log('Job cancelled or replaced after last step, stopping');
    return;
  }

  let completionVerification = null;
  if (!failed && activeJob.options?.mode !== 'schema_probe') {
    let verified = await verifySavedDraft(activeJob);
    if (!verified?.readback) {
      log(`Saved draft readback missed (${verified?.error || 'no readback'}); retrying once`);
      await sleep(2000);
      verified = await verifySavedDraft(activeJob);
    }
    completionVerification = verified;
    if (!verified?.readback) {
      failed = true;
      collectDiagnostics('passive');
      await releaseFailedJob(jobId);
      send({
        version: 1,
        type: 'job.step_failed',
        job_id: jobId,
        message_id: Date.now().toString(36),
        sent_at: new Date().toISOString(),
        payload: {
          step: 'verifying_draft',
          error: verified?.error || 'Saved Vendoo draft could not be independently verified',
          fields: verified?.general?.fields || {},
          mismatches: verified?.mismatches || [],
          fill_log: null,
        },
      });
    } else {
      activeJob.vendoo_item_id = verified.item_id || activeJob.vendoo_item_id;
      activeJob.vendoo_url = verified.url || activeJob.vendoo_url;
      await persistActiveJob(activeJob);
    }
  }

  if (!failed) {
    const vurl = activeJob?.vendoo_url;
    const itemId = activeJob?.vendoo_item_id;
    const tabId = activeJob?.tabId;
    const mode = activeJob?.options?.mode;
    await addCompletedJobId(jobId);
    activeJob = null;
    await persistActiveJob(null);
    await stopJobPreview();
    await closeListingTab(tabId);

    send({
      version: 1,
      type: 'job.completed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { vendoo_url: vurl, vendoo_item_id: itemId, mode, verification: completionVerification },
    });
  }
}

async function releaseFailedJob(jobId) {
  if (activeJob?.job_id !== jobId) return;
  const tabId = activeJob.tabId;
  activeJob = null;
  await persistActiveJob(null);
  await stopJobPreview();
  await closeListingTab(tabId);
}

function buildJobSteps(job) {
  const platforms = job.options?.platforms || [];
  const resumeFrom = String(job.options?.resumeFrom || '').trim();
  const auditResume = resumeFrom.match(/^auditing_(.+)$/i);
  // On-demand marketplace audit retry (Fill Log / Retry) — not part of the
  // normal fill pipeline. End-of-job verifySavedDraft is the single audit.
  if (auditResume) {
    const target = String(auditResume[1] || '').toLowerCase();
    if (target && target !== 'general') {
      const auditSteps = [
        { step: 'opening_vendoo', fn: openVendooListing },
        { step: 'waiting_ready', fn: waitForContentScript },
      ];
      if (job.options?.reuseExistingItem) {
        auditSteps.push({ step: 'checking_draft_safety', fn: checkDraftSafety });
      }
      if (target === 'marketplaces') {
        auditSteps.push({ step: 'auditing_marketplaces', fn: auditAllMarketplaces });
      } else {
        auditSteps.push({
          step: `auditing_${target}`,
          fn: (j) => auditMarketplace(j, target),
        });
      }
      return auditSteps;
    }
  }

  if (job.options?.mode === 'schema_probe') {
    const steps = [
      { step: 'opening_vendoo', fn: openVendooListing },
      { step: 'waiting_ready', fn: waitForContentScript },
    ];
    if (job.options?.reuseExistingItem) {
      steps.push({ step: 'checking_draft_safety', fn: checkDraftSafety });
    }
    steps.push({ step: 'selecting_category', fn: selectGeneralCategoryOnly });
    steps.push({ step: 'saving_general', fn: saveGeneral });
    if (platforms.length) {
      steps.push({ step: 'discovering_schema', fn: discoverSchema });
    }
    return steps;
  }

  const steps = [];
  const clearBeforeFill = Boolean(job.options?.clearBeforeFill);

  steps.push({ step: 'opening_vendoo', fn: openVendooListing });
  steps.push({ step: 'waiting_ready', fn: waitForContentScript });
  if (job.options?.reuseExistingItem) {
    steps.push({ step: 'checking_draft_safety', fn: checkDraftSafety });
  }
  if (!job.options?.skipPhotos) {
    steps.push({ step: 'uploading_photos', fn: uploadPhotos });
  }
  if (clearBeforeFill) {
    steps.push({ step: 'clearing_general', fn: clearGeneral });
  }
  steps.push({ step: 'filling_general', fn: fillGeneral });
  steps.push({ step: 'saving_general', fn: saveGeneral });
  steps.push({ step: 'auditing_general', fn: auditGeneral });

  // After General category is committed, align each marketplace category and
  // scrape the live field schema before filling values — unless Studio already
  // has a complete cached schema for this category path.
  if (platforms.length && !job.options?.skipDiscoverSchema) {
    steps.push({ step: 'discovering_schema', fn: discoverSchema });
  }
  // Studio lists marketplaces whose saved draft already matches the listing
  // (read back after auto-apply); end-of-job verification still checks them.
  const skipPlatforms = new Set((job.options?.skipPlatforms || []).map((mp) => String(mp).toLowerCase()));
  for (const platform of platforms) {
    if (skipPlatforms.has(String(platform).toLowerCase()) && !clearBeforeFill) {
      log(`Skipping ${platform} fill: saved draft already matches the listing`);
      continue;
    }
    if (clearBeforeFill) {
      steps.push({ step: `clearing_${platform}`, fn: (j) => clearMarketplace(j, platform) });
    }
    steps.push({ step: `filling_${platform}`, fn: (j) => fillMarketplace(j, platform) });
    // Checkpoint after each marketplace. SAVE_MARKETPLACE is the same Vendoo
    // Save button, but flushing per tab is safer if inactive panels drop dirty state.
    steps.push({ step: `saving_${platform}`, fn: (j) => saveMarketplace(j, platform) });
  }

  return steps;
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

  if (msg.type === 'IMPORT_VENDOO_LISTING') {
    importVendooListing(msg.tabId).then(sendResponse).catch((err) => {
      sendResponse({ ok: false, error: err.message });
    });
    return true;
  }

  if (msg.type === 'IGNORE_PAIRING') {
    fetchStudioPairingToken().then(() => {
      if (ws && ws.readyState === WebSocket.OPEN) sendIdent();
      else connect();
      sendResponse({ ok: true });
    }).catch((err) => {
      sendResponse({ ok: false, error: err.message });
    });
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
