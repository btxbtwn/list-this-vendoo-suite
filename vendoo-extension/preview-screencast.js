const PREVIEW_PROTOCOL = '1.3';
const PREVIEW_MIN_INTERVAL_MS = 250;
const PREVIEW_MAX_WIDTH = 1024;
const PREVIEW_MAX_HEIGHT = 720;
const PREVIEW_QUALITY = 50;
const PREVIEW_CAPTURE_FALLBACK_MS = 400;

let previewTabId = null;
let previewJobId = null;
let previewAttached = false;
let previewFallbackTimer = null;
let lastPreviewSentAt = 0;

function sendPreviewFrame(jobId, data, extra) {
  if (typeof send !== 'function' || !jobId || !data) {
    return;
  }
  const now = Date.now();
  if (now - lastPreviewSentAt < PREVIEW_MIN_INTERVAL_MS) {
    return;
  }
  lastPreviewSentAt = now;
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
}

async function tabPreviewUrl(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    return tab?.url || '';
  } catch (_) {
    return '';
  }
}

function stopCaptureFallback() {
  if (previewFallbackTimer) {
    clearInterval(previewFallbackTimer);
    previewFallbackTimer = null;
  }
}

function startCaptureFallback(tabId, jobId) {
  stopCaptureFallback();
  previewFallbackTimer = setInterval(async () => {
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
      // Tab is not visible in its window; debugger path is preferred.
    }
  }, PREVIEW_CAPTURE_FALLBACK_MS);
}

async function stopJobPreview() {
  stopCaptureFallback();
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
      await chrome.debugger.detach({ tabId });
    } catch (_) {}
  }
}

async function startJobPreview(tabId, jobId) {
  if (!tabId || !jobId) {
    return;
  }
  if (previewTabId === tabId && previewJobId === jobId && previewAttached) {
    return;
  }
  await stopJobPreview();
  previewTabId = tabId;
  previewJobId = jobId;
  try {
    await chrome.debugger.attach({ tabId }, PREVIEW_PROTOCOL);
    previewAttached = true;
    await chrome.debugger.sendCommand({ tabId }, 'Page.enable');
    await chrome.debugger.sendCommand({ tabId }, 'Page.startScreencast', {
      format: 'jpeg',
      quality: PREVIEW_QUALITY,
      maxWidth: PREVIEW_MAX_WIDTH,
      maxHeight: PREVIEW_MAX_HEIGHT,
      everyNthFrame: 2,
    });
    log(`Preview screencast started on tab ${tabId}`);
  } catch (err) {
    previewAttached = false;
    log(`Preview debugger unavailable (${err.message}); using visible-tab capture fallback`);
    startCaptureFallback(tabId, jobId);
  }
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
        startCaptureFallback(previewTabId, previewJobId);
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
