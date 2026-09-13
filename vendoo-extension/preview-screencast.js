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
const ENGINE_TOP = 0;
const ENGINE_WIDTH = 1280;
const ENGINE_HEIGHT = 900;
const SHOW_LEFT = 80;
const SHOW_TOP = 80;

function isOffscreenEngineWindow(win) {
  return Boolean(win && win.id != null && Number.isFinite(win.left) && win.left <= ENGINE_LEFT / 2);
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

async function hideWindow(windowId) {
  if (windowId == null) {
    return;
  }
  try {
    // Stay off-screen at state 'normal'. Minimized Chrome windows stop
    // compositing, so Studio's preview stays blank until the window is restored.
    await chrome.windows.update(windowId, {
      focused: false,
      left: ENGINE_LEFT,
      top: ENGINE_TOP,
      width: ENGINE_WIDTH,
      height: ENGINE_HEIGHT,
      state: 'normal',
    });
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
      await chrome.windows.update(windowId, { focused: true, state: 'normal' });
      return;
    }
    await chrome.windows.update(windowId, {
      focused: true,
      state: 'normal',
      left: SHOW_LEFT,
      top: SHOW_TOP,
      width: ENGINE_WIDTH,
      height: ENGINE_HEIGHT,
    });
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
    if (isOffscreenEngineWindow(win)) {
      return win.id;
    }
  } catch (_) {}
  return null;
}

async function engineWindowId() {
  const existing = await rememberedEngineWindowId();
  if (existing != null) {
    return existing;
  }
  const created = await chrome.windows.create({
    url: 'about:blank',
    focused: false,
    type: 'normal',
    left: ENGINE_LEFT,
    top: ENGINE_TOP,
    width: ENGINE_WIDTH,
    height: ENGINE_HEIGHT,
  });
  await chrome.storage.local.set({ [ENGINE_WINDOW_KEY]: created.id });
  await hideWindow(created.id);
  return created.id;
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
