const PREVIEW_PROTOCOL = '1.3';
const PREVIEW_MIN_INTERVAL_MS = 250;
const PREVIEW_MAX_WIDTH = 1024;
const PREVIEW_MAX_HEIGHT = 720;
// Frames go over a local WebSocket, so favor a crisp picture over bandwidth.
const PREVIEW_QUALITY = 85;
const PREVIEW_POLL_MS = 400;
const PREVIEW_WATCHDOG_MS = 800;

let previewTabId = null;
let previewJobId = null;
let previewAttached = false;
let previewPollTimer = null;
let previewWatchdogTimer = null;
let lastPreviewSentAt = 0;

function sendPreviewFrame(jobId, data, extra) {
  if (typeof send !== 'function' || !jobId || !data) {
    return;
  }
  const now = Date.now();
  if (lastPreviewSentAt && now - lastPreviewSentAt < PREVIEW_MIN_INTERVAL_MS) {
    return;
  }
  lastPreviewSentAt = now;
  try {
    send({
      version: 1,
      type: 'job.preview_frame',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: {
        mime: 'image/jpeg',
        data,
        url: extra?.url || '',
        step: (typeof activeJob !== 'undefined' && activeJob?.current_step) || extra?.step || '',
        width: extra?.width || null,
        height: extra?.height || null,
        viewport_width: extra?.viewportWidth || null,
        viewport_height: extra?.viewportHeight || null,
      },
    });
  } catch (err) {
    lastPreviewSentAt = 0;
    log(`Preview frame send failed (${err.message})`);
  }
}

async function tabPreviewUrl(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    return tab?.url || '';
  } catch (_) {
    return '';
  }
}

// CSS-pixel viewport of the captured tab. Studio maps overlay clicks and field
// rectangles onto the frame with it, so it travels with every frame.
async function tabPreviewInfo(tabId, { attached = false } = {}) {
  let url = '';
  let viewportWidth = null;
  let viewportHeight = null;
  try {
    const tab = await chrome.tabs.get(tabId);
    url = tab?.url || '';
    viewportWidth = tab?.width || null;
    viewportHeight = tab?.height || null;
  } catch (_) {}
  if (attached) {
    try {
      const metrics = await chrome.debugger.sendCommand({ tabId }, 'Page.getLayoutMetrics');
      const viewport = metrics?.cssVisualViewport || metrics?.cssLayoutViewport;
      if (viewport?.clientWidth && viewport?.clientHeight) {
        viewportWidth = Math.round(viewport.clientWidth);
        viewportHeight = Math.round(viewport.clientHeight);
      }
    } catch (_) {}
  }
  return { url, viewportWidth, viewportHeight };
}

const ENGINE_WINDOW_KEY = 'studio_engine_window_id';
const ENGINE_LEFT = -20000;
const ENGINE_WIDTH = 1280;
const ENGINE_HEIGHT = 900;
const SHOW_LEFT = 80;
const SHOW_TOP = 80;
const FALLBACK_WIDTH = 800;
const FALLBACK_HEIGHT = 600;

function isOffscreenEngineWindow(win) {
  return Boolean(win && win.id != null && Number.isFinite(win.left) && win.left <= ENGINE_LEFT / 2);
}

function isWindowBoundsError(err) {
  const message = String((err && err.message) || err || '');
  return /bounds/i.test(message) && /visible screen/i.test(message);
}

function workAreasFromDisplays(displays) {
  return (displays || [])
    .filter((display) => (
      display
      && display.isEnabled !== false
      && display.workArea
      && Number.isFinite(display.workArea.left)
      && Number.isFinite(display.workArea.top)
      && Number.isFinite(display.workArea.width)
      && display.workArea.width > 0
      && Number.isFinite(display.workArea.height)
      && display.workArea.height > 0
    ))
    .map((display) => display.workArea);
}

function overlapArea(win, area) {
  const left = Math.max(win.left, area.left);
  const top = Math.max(win.top, area.top);
  const right = Math.min(win.left + win.width, area.left + area.width);
  const bottom = Math.min(win.top + win.height, area.top + area.height);
  if (right <= left || bottom <= top) {
    return 0;
  }
  return (right - left) * (bottom - top);
}

function isMostlyOnscreen(win, areas) {
  const total = Number(win && win.width) * Number(win && win.height);
  if (!total || !(areas || []).length) {
    return false;
  }
  let overlap = 0;
  for (const area of areas) {
    overlap += overlapArea(win, area);
  }
  return overlap >= total * 0.5;
}

function boundsInWorkArea(area, width, height) {
  const areaWidth = Number(area && area.width) || FALLBACK_WIDTH;
  const areaHeight = Number(area && area.height) || FALLBACK_HEIGHT;
  const w = Math.max(1, Math.min(width || FALLBACK_WIDTH, areaWidth));
  const h = Math.max(1, Math.min(height || FALLBACK_HEIGHT, areaHeight));
  return {
    left: (Number(area && area.left) || 0) + Math.max(0, Math.floor((areaWidth - w) / 2)),
    top: (Number(area && area.top) || 0) + Math.max(0, Math.floor((areaHeight - h) / 2)),
    width: w,
    height: h,
  };
}

function pickOnscreenBounds(windows, displays) {
  const areas = workAreasFromDisplays(displays);
  const primary = (displays || []).find((display) => display && display.isPrimary && display.workArea);
  const fallbackArea = (primary && primary.workArea) || areas[0];
  const visible = (windows || []).find((win) => (
    win
    && win.state !== 'minimized'
    && Number.isFinite(win.left)
    && win.left > ENGINE_LEFT / 2
    && Number.isFinite(win.top)
    && Number.isFinite(win.width)
    && win.width >= 400
    && Number.isFinite(win.height)
    && win.height >= 300
    && (!areas.length || isMostlyOnscreen(win, areas))
  ));
  if (fallbackArea) {
    return boundsInWorkArea(
      fallbackArea,
      visible ? Math.min(ENGINE_WIDTH, visible.width) : ENGINE_WIDTH,
      visible ? Math.min(ENGINE_HEIGHT, visible.height) : ENGINE_HEIGHT,
    );
  }
  if (!visible) {
    return {
      left: SHOW_LEFT,
      top: SHOW_TOP,
      width: FALLBACK_WIDTH,
      height: FALLBACK_HEIGHT,
    };
  }
  return {
    left: visible.left,
    top: visible.top,
    width: Math.min(ENGINE_WIDTH, visible.width),
    height: Math.min(ENGINE_HEIGHT, visible.height),
  };
}

function stopPreviewPolling() {
  previewCaptureNow = null;
  if (previewPollTimer) {
    clearInterval(previewPollTimer);
    previewPollTimer = null;
  }
  if (previewWatchdogTimer) {
    clearTimeout(previewWatchdogTimer);
    previewWatchdogTimer = null;
  }
}

async function displayInfo() {
  try {
    if (chrome.system && chrome.system.display && chrome.system.display.getInfo) {
      return await chrome.system.display.getInfo();
    }
  } catch (_) {}
  return [];
}

async function safeWindowBounds() {
  const displays = await displayInfo();
  try {
    return pickOnscreenBounds(await chrome.windows.getAll(), displays);
  } catch (_) {
    return pickOnscreenBounds([], displays);
  }
}

function createOptionsWithoutBounds(createOptions) {
  const rest = { type: 'normal', ...createOptions };
  delete rest.left;
  delete rest.top;
  delete rest.width;
  delete rest.height;
  return rest;
}

async function adoptTabIntoWindow(tabId, windowId) {
  if (tabId == null || windowId == null) {
    return;
  }
  await chrome.tabs.move(tabId, { windowId, index: -1 });
  try {
    await chrome.tabs.update(tabId, { active: true });
  } catch (_) {}
  await closeSpareBlankTabs(windowId, tabId);
}

async function updateWindowSafe(windowId, extras = {}) {
  const bounds = await safeWindowBounds();
  const attempts = [
    { ...bounds, ...extras },
    { ...bounds, focused: extras.focused, state: extras.state || 'normal' },
    { ...bounds, focused: extras.focused },
    { focused: extras.focused, state: extras.state || 'normal' },
    { focused: extras.focused },
  ];
  let lastError = null;
  for (const update of attempts) {
    try {
      await chrome.windows.update(windowId, update);
      return;
    } catch (err) {
      lastError = err;
      if (!isWindowBoundsError(err)) {
        throw err;
      }
      log(`Chrome rejected window update (${err.message})`);
    }
  }
  throw lastError;
}

async function createWindowSafe(createOptions = {}) {
  const bounds = await safeWindowBounds();
  const tabId = createOptions.tabId;
  const withoutBounds = createOptionsWithoutBounds(createOptions);
  const withoutTab = { ...withoutBounds };
  delete withoutTab.tabId;
  if (!withoutTab.url && tabId == null) {
    withoutTab.url = 'about:blank';
  }
  const attempts = [
    { ...bounds, type: 'normal', ...createOptions },
    { ...bounds, ...withoutTab },
    {
      ...withoutTab,
      left: 0,
      top: 0,
      width: FALLBACK_WIDTH,
      height: FALLBACK_HEIGHT,
    },
    withoutTab,
  ];
  let lastError = null;
  let created = null;
  for (const options of attempts) {
    try {
      created = await chrome.windows.create(options);
      break;
    } catch (err) {
      lastError = err;
      if (!isWindowBoundsError(err)) {
        throw err;
      }
      log(`Chrome rejected window create (${err.message})`);
    }
  }
  if (!created) {
    throw lastError;
  }
  const createdWithTab = Array.isArray(created.tabs)
    && created.tabs.some((tab) => tab && tab.id === tabId);
  if (tabId != null && !createdWithTab) {
    await adoptTabIntoWindow(tabId, created.id);
  }
  return created;
}

async function hideWindow(windowId) {
  if (windowId == null) {
    return;
  }
  try {
    // Chrome rejects off-screen bounds. Keep the window on-screen at state
    // 'normal' so compositing (and Studio preview) continue.
    await updateWindowSafe(windowId, { focused: false, state: 'normal' });
  } catch (err) {
    log(`Could not hide Chrome window (${err.message})`);
  }
}

async function showWindow(windowId) {
  if (windowId == null) {
    return;
  }
  try {
    const win = await chrome.windows.get(windowId);
    if (win && !isOffscreenEngineWindow(win) && win.state !== 'minimized') {
      try {
        await chrome.windows.update(windowId, { focused: true, state: 'normal' });
        return;
      } catch (err) {
        if (!isWindowBoundsError(err)) {
          throw err;
        }
      }
    }
    await updateWindowSafe(windowId, { focused: true, state: 'normal' });
  } catch (err) {
    log(`Could not show Chrome window (${err.message})`);
  }
}

async function rememberedEngineWindowId() {
  const stored = await chrome.storage.local.get(ENGINE_WINDOW_KEY);
  const remembered = stored[ENGINE_WINDOW_KEY];
  if (remembered == null) {
    return null;
  }
  try {
    const win = await chrome.windows.get(remembered);
    if (win?.id != null) {
      return win.id;
    }
  } catch (_) {}
  return null;
}

async function closeSpareBlankTabs(windowId, keepTabId) {
  try {
    const tabs = await chrome.tabs.query({ windowId });
    await Promise.all(tabs
      .filter((tab) => tab.id && tab.id !== keepTabId && (!tab.url || tab.url === 'about:blank'))
      .map((tab) => chrome.tabs.remove(tab.id)));
  } catch (_) {}
}

async function closeEmptyEngineWindows(keepWindowId) {
  // Only clean up Studio's previous engine window. Never close the user's everyday
  // Chrome windows — blank NTP / about:blank tabs are normal there.
  let engineId = null;
  try {
    const stored = await chrome.storage.local.get(ENGINE_WINDOW_KEY);
    engineId = stored[ENGINE_WINDOW_KEY];
  } catch (_) {}
  if (engineId == null || engineId === keepWindowId) {
    return;
  }
  try {
    const win = await chrome.windows.get(engineId, { populate: true });
    const hasRealTab = (win.tabs || []).some((tab) => tab.url && tab.url !== 'about:blank');
    if (hasRealTab) {
      return;
    }
    try {
      await chrome.windows.remove(engineId);
    } catch (_) {}
    try {
      await chrome.storage.local.remove(ENGINE_WINDOW_KEY);
    } catch (_) {}
  } catch (_) {
    try {
      await chrome.storage.local.remove(ENGINE_WINDOW_KEY);
    } catch (_) {}
  }
}

async function openEverydayListingTab(url, existing, { foreground = false } = {}) {
  const engineId = await rememberedEngineWindowId();
  if (existing?.id && engineId != null && existing.windowId === engineId) {
    try {
      const update = { active: true };
      if (url) update.url = url;
      const tab = await chrome.tabs.update(existing.id, update);
      if (foreground && tab.windowId) await showWindow(tab.windowId);
      else if (tab.windowId) await hideWindow(tab.windowId);
      return tab;
    } catch (err) {
      log(`Could not reuse engine Vendoo tab (${err.message}); opening a new window`);
    }
  }

  try {
    const targetUrl = url || existing?.url || 'about:blank';
    const created = await createWindowSafe({
      url: targetUrl,
      focused: Boolean(foreground),
      type: 'normal',
    });
    await chrome.storage.local.set({ [ENGINE_WINDOW_KEY]: created.id });
    const tab = created.tabs && created.tabs[0];
    if (!tab) {
      throw new Error('Chrome did not return a listing tab');
    }
    await closeSpareBlankTabs(created.id, tab.id);
    await closeEmptyEngineWindows(created.id);
    // Keep a freshly created engine window on-screen (Chrome stops painting
    // minimized or off-screen windows, which freezes the live view and the
    // fill). Only focus it when the caller asked for the foreground; otherwise
    // it stays behind Studio so the seller keeps working.
    if (foreground) await showWindow(created.id);
    else await hideWindow(created.id);
    return tab;
  } catch (err) {
    log(`Could not open listing in a new window (${err.message})`);
    throw err;
  }
}

async function closeListingTab(tabId) {
  if (tabId == null) {
    return;
  }
  // The seller is looking at this tab in Studio. Keep it and resume the live view.
  if (typeof browserSessionOwnsTab === 'function' && browserSessionOwnsTab(tabId)) {
    await resumeBrowserSessionPreview();
    return;
  }
  let windowId = null;
  try {
    const tab = await chrome.tabs.get(tabId);
    windowId = tab.windowId;
  } catch (_) {}
  try {
    await chrome.tabs.remove(tabId);
    log(`Closed listing tab ${tabId}`);
  } catch (err) {
    log(`Could not close listing tab (${err.message})`);
  }
  if (windowId != null) {
    await closeEmptyEngineWindows(null);
  }
}

function startVisibleTabPoll(tabId, jobId) {
  stopPreviewPolling();
  previewPollTimer = setInterval(async () => {
    if (!previewJobId || previewJobId !== jobId || previewTabId !== tabId) {
      return;
    }
    try {
      const tab = await chrome.tabs.get(tabId);
      if (!tab?.windowId) {
        return;
      }
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
        format: 'jpeg',
        quality: PREVIEW_QUALITY,
      });
      const prefix = 'data:image/jpeg;base64,';
      if (!dataUrl || !dataUrl.startsWith(prefix)) {
        return;
      }
      sendPreviewFrame(jobId, dataUrl.slice(prefix.length), {
        url: tab.url || '',
        viewportWidth: tab.width || null,
        viewportHeight: tab.height || null,
      });
    } catch (_) {
      // Hidden window; debugger capture is preferred.
    }
  }, PREVIEW_POLL_MS);
}

async function preparePageForCapture(tabId) {
  try {
    await chrome.debugger.sendCommand({ tabId }, 'Page.setWebLifecycleState', {
      state: 'active',
    });
  } catch (_) {}
  try {
    await chrome.debugger.sendCommand({ tabId }, 'Emulation.clearDeviceMetricsOverride');
  } catch (_) {}
}

async function captureDebuggerScreenshot(tabId) {
  const attempts = [
    { fromSurface: false, captureBeyondViewport: false },
    { fromSurface: true, captureBeyondViewport: false },
  ];
  for (const options of attempts) {
    try {
      const result = await chrome.debugger.sendCommand({ tabId }, 'Page.captureScreenshot', {
        format: 'jpeg',
        quality: PREVIEW_QUALITY,
        ...options,
      });
      if (result?.data) {
        return result.data;
      }
    } catch (_) {}
  }
  return null;
}

function startDebuggerScreenshotPoll(tabId, jobId) {
  stopPreviewPolling();
  const captureOnce = async () => {
    if (!previewJobId || previewJobId !== jobId || previewTabId !== tabId || !previewAttached) {
      return;
    }
    try {
      const data = await captureDebuggerScreenshot(tabId);
      if (!data) {
        return;
      }
      sendPreviewFrame(jobId, data, await tabPreviewInfo(tabId, { attached: true }));
    } catch (_) {
      if (!previewAttached && await tabIsInFront(tabId)) {
        startVisibleTabPoll(tabId, jobId);
      }
    }
  };
  previewCaptureNow = captureOnce;
  captureOnce();
  previewPollTimer = setInterval(captureOnce, PREVIEW_POLL_MS);
}

let previewCaptureNow = null;
let previewSoonTimer = null;

// Interactive input should show up faster than the idle poll interval.
function capturePreviewSoon(delayMs = 120) {
  if (previewSoonTimer || typeof previewCaptureNow !== 'function') {
    return;
  }
  previewSoonTimer = setTimeout(() => {
    previewSoonTimer = null;
    lastPreviewSentAt = 0;
    if (typeof previewCaptureNow === 'function') {
      previewCaptureNow();
    }
  }, delayMs);
}

async function tabIsInFront(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (!tab?.active || tab.windowId == null) {
      return false;
    }
    const win = await chrome.windows.get(tab.windowId);
    return Boolean(
      win
      && win.focused
      && win.state !== 'minimized'
      && !isOffscreenEngineWindow(win),
    );
  } catch (_) {
    return false;
  }
}

async function attachDebuggerPreview(tabId, jobId) {
  if (previewAttached && previewTabId === tabId && previewJobId === jobId) {
    if (!previewPollTimer) startDebuggerScreenshotPoll(tabId, jobId);
    return;
  }
  try {
    await chrome.debugger.attach({ tabId }, PREVIEW_PROTOCOL);
    previewAttached = true;
    await chrome.debugger.sendCommand({ tabId }, 'Page.enable');
    await preparePageForCapture(tabId);
    startDebuggerScreenshotPoll(tabId, jobId);
  } catch (err) {
    previewAttached = false;
    log(`Preview debugger unavailable (${err.message})`);
    if (await tabIsInFront(tabId)) {
      startVisibleTabPoll(tabId, jobId);
    }
  }
}

function armPreviewWatchdog(tabId, jobId) {
  if (previewWatchdogTimer) {
    clearTimeout(previewWatchdogTimer);
  }
  previewWatchdogTimer = setTimeout(async () => {
    previewWatchdogTimer = null;
    if (previewJobId !== jobId || previewTabId !== tabId || lastPreviewSentAt) {
      return;
    }
    log('Visible-tab preview produced no frames; polling debugger screenshots');
    await attachDebuggerPreview(tabId, jobId);
  }, PREVIEW_WATCHDOG_MS);
}

async function stopJobPreview() {
  stopPreviewPolling();
  const tabId = previewTabId;
  const attached = previewAttached;
  previewAttached = false;
  previewTabId = null;
  previewJobId = null;
  lastPreviewSentAt = 0;
  if (attached && tabId != null) {
    try {
      await chrome.debugger.sendCommand({ tabId }, 'Page.stopScreencast');
    } catch (_) {}
    try {
      await chrome.debugger.sendCommand({ tabId }, 'Emulation.clearDeviceMetricsOverride');
    } catch (_) {}
    try {
      await chrome.debugger.detach({ tabId });
    } catch (_) {}
  }
}

async function startJobPreview(tabId, jobId) {
  if (!tabId || !jobId) {
    return;
  }
  if (previewTabId === tabId && previewJobId === jobId && (previewAttached || previewPollTimer)) {
    return;
  }
  await stopJobPreview();
  previewTabId = tabId;
  previewJobId = jobId;
  try {
    await chrome.tabs.update(tabId, { autoDiscardable: false });
  } catch (_) {}
  if (await tabIsInFront(tabId)) {
    startVisibleTabPoll(tabId, jobId);
    armPreviewWatchdog(tabId, jobId);
    return;
  }
  await attachDebuggerPreview(tabId, jobId);
}

try {
  chrome.debugger.onEvent.addListener((source, method, params) => {
    if (method !== 'Page.screencastFrame') {
      return;
    }
    if (!previewJobId || source.tabId !== previewTabId) {
      return;
    }
    const sessionId = params.sessionId;
    chrome.debugger.sendCommand(source, 'Page.screencastFrameAck', { sessionId }).catch(() => {});
    const metadata = params.metadata || {};
    tabPreviewUrl(source.tabId).then((url) => {
      sendPreviewFrame(previewJobId, params.data, {
        url,
        width: metadata.deviceWidth,
        height: metadata.deviceHeight,
        viewportWidth: metadata.deviceWidth,
        viewportHeight: metadata.deviceHeight,
      });
    });
  });

  chrome.debugger.onDetach.addListener((source, reason) => {
    if (source.tabId === previewTabId) {
      previewAttached = false;
      log(`Preview debugger detached (${reason || 'unknown'})`);
      if (previewTabId && previewJobId) {
        tabIsInFront(previewTabId).then((inFront) => {
          if (inFront && previewTabId && previewJobId) {
            startVisibleTabPoll(previewTabId, previewJobId);
          }
        });
      }
    }
  });
} catch (err) {
  console.warn('[BG-Studio] Debugger API unavailable', err);
}

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === previewTabId) {
    stopJobPreview();
  }
});
