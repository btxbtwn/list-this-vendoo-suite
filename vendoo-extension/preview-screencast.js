const PREVIEW_PROTOCOL = '1.3';
const PREVIEW_MIN_INTERVAL_MS = 250;
const PREVIEW_MAX_WIDTH = 1024;
const PREVIEW_MAX_HEIGHT = 720;
const PREVIEW_QUALITY = 50;
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

async function engineWindowId() {
  const existing = await rememberedEngineWindowId();
  if (existing != null) {
    try {
      await updateWindowSafe(existing, { focused: false, state: 'normal' });
      return existing;
    } catch (err) {
      log(`Could not reuse engine window (${err.message}); opening a new one`);
      try {
        await chrome.storage.local.remove(ENGINE_WINDOW_KEY);
      } catch (_) {}
    }
  }
  try {
    const created = await createWindowSafe({
      url: 'about:blank',
      focused: false,
      type: 'normal',
    });
    await chrome.storage.local.set({ [ENGINE_WINDOW_KEY]: created.id });
    await hideWindow(created.id);
    return created.id;
  } catch (err) {
    log(`Could not create engine window (${err.message}); using an existing Chrome window`);
    const windows = await chrome.windows.getAll();
    const visible = (windows || []).find((win) => (
      win && win.id != null && win.state !== 'minimized' && !isOffscreenEngineWindow(win)
    ));
    if (visible?.id != null) {
      await chrome.storage.local.set({ [ENGINE_WINDOW_KEY]: visible.id });
      return visible.id;
    }
    throw err;
  }
}

async function closeSpareBlankTabs(windowId, keepTabId) {
  try {
    const tabs = await chrome.tabs.query({ windowId });
    await Promise.all(tabs
      .filter((tab) => tab.id && tab.id !== keepTabId && (!tab.url || tab.url === 'about:blank'))
      .map((tab) => chrome.tabs.remove(tab.id)));
  } catch (_) {}
}

async function closeEmptyWindows(keepWindowId) {
  try {
    const windows = await chrome.windows.getAll({ populate: true });
    await Promise.all(windows
      .filter((win) => win.id && win.id !== keepWindowId)
      .filter((win) => !(win.tabs || []).some((tab) => tab.url && tab.url !== 'about:blank'))
      .map((win) => chrome.windows.remove(win.id)));
  } catch (_) {}
}

async function openTabInHiddenWindow(url, existing) {
  try {
    const windowId = await engineWindowId();
    await hideWindow(windowId);
    let tab;
    if (existing?.id) {
      if (existing.windowId !== windowId) {
        try {
          await chrome.tabs.move(existing.id, { windowId, index: -1 });
        } catch (_) {}
      }
      tab = url
        ? await chrome.tabs.update(existing.id, { url, active: true })
        : await chrome.tabs.update(existing.id, { active: true });
    } else {
      tab = await chrome.tabs.create({ windowId, url, active: true });
    }
    const hiddenId = tab.windowId || windowId;
    await closeSpareBlankTabs(hiddenId, tab.id);
    await closeEmptyWindows(hiddenId);
    await hideWindow(hiddenId);
    return tab;
  } catch (err) {
    log(`Could not open engine tab (${err.message}); opening in a regular tab`);
    if (existing?.id) {
      return url
        ? chrome.tabs.update(existing.id, { url, active: true })
        : chrome.tabs.update(existing.id, { active: true });
    }
    return chrome.tabs.create({ url, active: true });
  }
}

async function parkJobTab(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    await openTabInHiddenWindow(null, tab);
  } catch (err) {
    log(`Could not keep Chrome hidden (${err.message})`);
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
      sendPreviewFrame(jobId, dataUrl.slice(prefix.length), { url: tab.url || '' });
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
      const url = await tabPreviewUrl(tabId);
      sendPreviewFrame(jobId, data, { url });
    } catch (_) {
      if (!previewAttached) {
        startVisibleTabPoll(tabId, jobId);
      }
    }
  };
  captureOnce();
  previewPollTimer = setInterval(captureOnce, PREVIEW_POLL_MS);
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
    try {
      await chrome.debugger.attach({ tabId }, PREVIEW_PROTOCOL);
      previewAttached = true;
      await chrome.debugger.sendCommand({ tabId }, 'Page.enable');
      await preparePageForCapture(tabId);
      startDebuggerScreenshotPoll(tabId, jobId);
    } catch (err) {
      previewAttached = false;
      log(`Preview debugger unavailable (${err.message}); keeping visible-tab capture`);
      startVisibleTabPoll(tabId, jobId);
    }
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
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab?.windowId) {
      await showWindow(tab.windowId);
    }
  } catch (_) {}
  if (previewTabId === tabId && previewJobId === jobId && (previewAttached || previewPollTimer)) {
    return;
  }
  await stopJobPreview();
  previewTabId = tabId;
  previewJobId = jobId;
  // Visible window: snapshot the real tab. Screencast + device-metrics
  // override fight the OS scale and make Vendoo's layout pulse.
  startVisibleTabPoll(tabId, jobId);
  armPreviewWatchdog(tabId, jobId);
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
      });
    });
  });

  chrome.debugger.onDetach.addListener((source, reason) => {
    if (source.tabId === previewTabId) {
      previewAttached = false;
      log(`Preview debugger detached (${reason || 'unknown'})`);
      if (previewTabId && previewJobId) {
        startVisibleTabPoll(previewTabId, previewJobId);
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
