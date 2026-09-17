// Interactive Vendoo browser for Studio.
//
// Studio shows the draft tab as a live frame. This module lets the seller drive
// that tab from Studio (pointer, wheel, keyboard), point at fields, and lets the
// listing agent read and act on the page. Everything goes through the Chrome
// debugger session the preview already holds, so the tab can stay in the
// background engine window.

const BROWSER_MAX_INPUT_EVENTS = 40;
const BROWSER_MAX_TEXT = 2000;
const BROWSER_WAIT_MAX_MS = 15000;
const BROWSER_MODIFIER_MASK = 1 | 2 | 4 | 8;

const BROWSER_MOUSE_TYPES = new Set(['mousePressed', 'mouseReleased', 'mouseMoved', 'mouseWheel']);
const BROWSER_MOUSE_BUTTONS = new Set(['none', 'left', 'middle', 'right']);

// Keys without printable text. CDP needs the Windows virtual key code for these.
const BROWSER_SPECIAL_KEYS = {
  Enter: { code: 'Enter', vk: 13, text: '\r' },
  ' ': { code: 'Space', vk: 32, text: ' ' },
  Backspace: { code: 'Backspace', vk: 8 },
  Tab: { code: 'Tab', vk: 9 },
  Escape: { code: 'Escape', vk: 27 },
  Delete: { code: 'Delete', vk: 46 },
  ArrowLeft: { code: 'ArrowLeft', vk: 37 },
  ArrowUp: { code: 'ArrowUp', vk: 38 },
  ArrowRight: { code: 'ArrowRight', vk: 39 },
  ArrowDown: { code: 'ArrowDown', vk: 40 },
  Home: { code: 'Home', vk: 36 },
  End: { code: 'End', vk: 35 },
  PageUp: { code: 'PageUp', vk: 33 },
  PageDown: { code: 'PageDown', vk: 34 },
};

// Cmd/Ctrl shortcuts do not run editing commands when synthesized; name them.
const BROWSER_EDIT_COMMANDS = {
  a: 'selectAll',
  z: 'undo',
  x: 'cut',
  c: 'copy',
};

let browserSession = null;
// WebSocket messages are handled concurrently; input must replay in arrival order.
let browserInputChain = Promise.resolve();

function browserSessionOwnsTab(tabId) {
  return Boolean(browserSession && browserSession.tabId === tabId);
}

function browserAutomationJob() {
  return activeJob || activePatch || null;
}

function browserController(jobId) {
  const running = browserAutomationJob();
  if (running) return running.job_id === jobId ? 'agent' : 'busy';
  return browserSession && browserSession.jobId === jobId ? 'human' : 'none';
}

function sendBrowserResult(msg, result) {
  const payload = msg.payload || {};
  send({
    version: 1,
    type: 'browser.result',
    job_id: msg.job_id || payload.job_id || null,
    message_id: payload.request_id || Date.now().toString(36),
    sent_at: new Date().toISOString(),
    payload: {
      ...result,
      request_id: payload.request_id || null,
      controller: browserController(msg.job_id || payload.job_id),
    },
  });
}

async function resumeBrowserSessionPreview() {
  const session = browserSession;
  if (!session) return false;
  try {
    await chrome.tabs.get(session.tabId);
  } catch (_) {
    browserSession = null;
    return false;
  }
  if (previewTabId !== session.tabId || previewJobId !== session.jobId) {
    await startJobPreview(session.tabId, session.jobId);
  }
  // Input needs the debugger even when the tab happens to be in front.
  await attachDebuggerPreview(session.tabId, session.jobId);
  return previewAttached && previewTabId === session.tabId;
}

function browserSessionFor(msg) {
  const jobId = msg.job_id || msg.payload?.job_id;
  if (!browserSession || browserSession.jobId !== jobId) {
    return { error: 'Open the browser for this listing first' };
  }
  const running = browserAutomationJob();
  if (running) {
    return {
      error: running.job_id === jobId
        ? 'Studio is filling this draft. Wait for it to finish or cancel it.'
        : 'Another automation job is running',
    };
  }
  return { session: browserSession };
}

async function browserContentCommand(tabId, command) {
  const ready = await waitForContentScript({ tabId });
  if (!ready.ok) return { ok: false, error: ready.error || 'Vendoo page is not ready' };
  try {
    const response = await chrome.tabs.sendMessage(tabId, command);
    return response || { ok: false, error: 'No response from the Vendoo page' };
  } catch (err) {
    return { ok: false, error: `Vendoo page did not answer (${err.message})` };
  }
}

function clampRatio(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(1, number));
}

function browserModifiers(value) {
  return (Number(value) || 0) & BROWSER_MODIFIER_MASK;
}

async function browserViewport(tabId) {
  const info = await tabPreviewInfo(tabId, { attached: true });
  return {
    width: info.viewportWidth || 0,
    height: info.viewportHeight || 0,
  };
}

async function dispatchMouse(tabId, viewport, event) {
  if (!BROWSER_MOUSE_TYPES.has(event.type)) return;
  const button = BROWSER_MOUSE_BUTTONS.has(event.button) ? event.button : 'none';
  const params = {
    type: event.type,
    x: clampRatio(event.x_ratio) * viewport.width,
    y: clampRatio(event.y_ratio) * viewport.height,
    button,
    buttons: Number(event.buttons) || 0,
    clickCount: Math.max(0, Math.min(3, Number(event.click_count) || 0)),
    modifiers: browserModifiers(event.modifiers),
  };
  if (event.type === 'mouseWheel') {
    params.deltaX = Math.max(-2000, Math.min(2000, Number(event.delta_x) || 0));
    params.deltaY = Math.max(-2000, Math.min(2000, Number(event.delta_y) || 0));
  }
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', params);
}

async function dispatchKey(tabId, event) {
  const key = String(event.key || '');
  const modifiers = browserModifiers(event.modifiers);
  const down = event.type !== 'up';
  const special = BROWSER_SPECIAL_KEYS[key];
  const shortcut = (modifiers & (2 | 4)) && key.length === 1;
  if (shortcut) {
    const command = BROWSER_EDIT_COMMANDS[key.toLowerCase()];
    if (!down) return;
    const redo = key.toLowerCase() === 'z' && (modifiers & 8);
    const params = {
      type: 'rawKeyDown',
      key,
      code: String(event.code || ''),
      modifiers,
      windowsVirtualKeyCode: key.toUpperCase().charCodeAt(0),
    };
    if (command) params.commands = [redo ? 'redo' : command];
    await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', params);
    await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', { ...params, type: 'keyUp', commands: undefined });
    return;
  }
  if (special) {
    await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', {
      type: down ? (special.text ? 'keyDown' : 'rawKeyDown') : 'keyUp',
      key,
      code: special.code,
      windowsVirtualKeyCode: special.vk,
      modifiers,
      ...(down && special.text ? { text: special.text, unmodifiedText: special.text } : {}),
    });
    return;
  }
  if (key.length === 1) {
    if (!down) return;
    await chrome.debugger.sendCommand({ tabId }, 'Input.insertText', { text: key });
  }
}

async function runBrowserInput(tabId, viewport, events) {
  for (const event of events.slice(0, BROWSER_MAX_INPUT_EVENTS)) {
    if (!event || typeof event !== 'object') continue;
    if (event.kind === 'mouse') {
      await dispatchMouse(tabId, viewport, event);
    } else if (event.kind === 'key') {
      await dispatchKey(tabId, event);
    } else if (event.kind === 'text') {
      const text = String(event.text || '').slice(0, BROWSER_MAX_TEXT);
      if (text) await chrome.debugger.sendCommand({ tabId }, 'Input.insertText', { text });
    }
  }
}

async function browserClickAt(tabId, xRatio, yRatio) {
  const viewport = await browserViewport(tabId);
  const base = { kind: 'mouse', x_ratio: xRatio, y_ratio: yRatio, button: 'left', click_count: 1 };
  await runBrowserInput(tabId, viewport, [
    { ...base, type: 'mouseMoved', button: 'none', click_count: 0 },
    { ...base, type: 'mousePressed', buttons: 1 },
    { ...base, type: 'mouseReleased', buttons: 0 },
  ]);
}

async function openBrowserSession(msg) {
  const payload = msg.payload || {};
  const jobId = msg.job_id || payload.job_id;
  const running = browserAutomationJob();
  if (running && running.job_id !== jobId) {
    return { ok: false, error: 'Another automation job is running' };
  }
  if (running) {
    browserSession = { jobId, tabId: running.tabId, itemId: browserDraftItemId(payload) };
    return { ok: true, tab_id: running.tabId };
  }
  if (browserSession && browserSession.jobId !== jobId) {
    await closeBrowserSession({ job_id: browserSession.jobId });
  }
  const opened = await openListingForPatch(
    { ...payload, job_id: jobId },
    { reload: false, preview: true, marketplace: payload.marketplace || '' },
  );
  if (!opened.ok) return opened;
  browserSession = { jobId, tabId: opened.tabId, itemId: browserDraftItemId(payload) };
  const attached = await resumeBrowserSessionPreview();
  return {
    ok: true,
    tab_id: opened.tabId,
    input: attached,
    ...(attached ? {} : { warning: 'Chrome refused the debugger, so the view is read-only. Close DevTools on the Vendoo tab.' }),
  };
}

async function closeBrowserSession(payload) {
  const session = browserSession;
  if (!session || (payload.job_id && session.jobId !== payload.job_id)) {
    return { ok: true };
  }
  browserSession = null;
  if (!browserAutomationJob()) {
    await stopJobPreview();
    await closeListingTab(session.tabId);
  }
  return { ok: true };
}

function browserDraftItemId(payload) {
  return durableItemId(payload.vendoo_item_id) || extractItemIdFromUrl(payload.vendoo_url || '') || null;
}

// Agent actions stay on the draft the seller opened.
async function browserDraftScope(session) {
  let url = '';
  try {
    url = (await chrome.tabs.get(session.tabId)).url || '';
  } catch (_) {
    return { ok: false, error: 'The Vendoo tab was closed' };
  }
  if (!isVendooUrl(url) || (session.itemId && extractItemIdFromUrl(url) !== session.itemId)) {
    return { ok: false, error: 'The Vendoo tab is no longer on this draft', url };
  }
  return { ok: true, url };
}

async function runBrowserAction(session, payload) {
  const scope = await browserDraftScope(session);
  if (!scope.ok) return scope;
  const result = await runScopedBrowserAction(session, payload);
  const after = await browserDraftScope(session);
  if (!after.ok && after.url && session.itemId) {
    await chrome.tabs.update(session.tabId, { url: `https://web.vendoo.co/app/item/${session.itemId}` });
    return { ok: false, error: 'That action left the draft, so Studio went back to it. Unsaved edits may be lost.' };
  }
  return result;
}

async function runScopedBrowserAction(session, payload) {
  const tabId = session.tabId;
  const action = String(payload.action || '');
  if (action === 'click') {
    let xRatio = payload.x_ratio;
    let yRatio = payload.y_ratio;
    if (payload.text) {
      const located = await browserContentCommand(tabId, { type: 'LOCATE_TEXT', text: payload.text });
      if (!located.ok) return located;
      xRatio = located.x_ratio;
      yRatio = located.y_ratio;
    } else if (payload.selector) {
      const located = await browserContentCommand(tabId, { type: 'LOCATE_SELECTOR', selector: payload.selector });
      if (!located.ok) return located;
      xRatio = located.x_ratio;
      yRatio = located.y_ratio;
    }
    const target = await browserContentCommand(tabId, { type: 'PICK_FIELD_AT', x_ratio: xRatio, y_ratio: yRatio });
    if (target.element?.danger) {
      return { ok: false, error: `Refused to press "${target.element.text}". Studio never publishes or deletes listings.` };
    }
    await browserClickAt(tabId, xRatio, yRatio);
    return { ok: true, clicked: target.element || null, field: target.field || null };
  }
  if (action === 'type') {
    if (payload.selector) {
      const located = await browserContentCommand(tabId, { type: 'LOCATE_SELECTOR', selector: payload.selector });
      if (!located.ok) return located;
      await browserClickAt(tabId, located.x_ratio, located.y_ratio);
    }
    const focused = await browserContentCommand(tabId, { type: 'DESCRIBE_FOCUS' });
    if (!focused.editable) {
      return { ok: false, error: 'No text field is focused. Click a field first.' };
    }
    const text = String(payload.text || '').slice(0, BROWSER_MAX_TEXT);
    if (text) await chrome.debugger.sendCommand({ tabId }, 'Input.insertText', { text });
    return { ok: true };
  }
  if (action === 'press') {
    const key = String(payload.key || '');
    if (!BROWSER_SPECIAL_KEYS[key]) return { ok: false, error: `Unsupported key ${key}` };
    if (key === 'Enter' || key === ' ') {
      const focused = await browserContentCommand(tabId, { type: 'DESCRIBE_FOCUS' });
      if (focused.element?.danger) {
        return { ok: false, error: `Refused to press ${key === ' ' ? 'Space' : 'Enter'} on "${focused.element.text}".` };
      }
    }
    await dispatchKey(tabId, { key, type: 'down' });
    await dispatchKey(tabId, { key, type: 'up' });
    return { ok: true };
  }
  if (action === 'scroll') {
    const viewport = await browserViewport(tabId);
    await runBrowserInput(tabId, viewport, [{
      kind: 'mouse',
      type: 'mouseWheel',
      x_ratio: 0.5,
      y_ratio: 0.5,
      delta_x: payload.delta_x,
      delta_y: payload.delta_y,
    }]);
    return { ok: true };
  }
  if (action === 'wait') {
    await sleep(Math.max(0, Math.min(BROWSER_WAIT_MAX_MS, Number(payload.ms) || 0)));
    return { ok: true };
  }
  return { ok: false, error: `Unknown browser action ${action}` };
}

async function handleBrowserMessage(msg) {
  const payload = msg.payload || {};
  switch (msg.type) {
    case 'browser.open': {
      let result;
      try {
        result = await openBrowserSession(msg);
      } catch (err) {
        result = { ok: false, error: err.message };
      }
      sendBrowserResult(msg, result);
      return;
    }

    case 'browser.close':
      sendBrowserResult(msg, await closeBrowserSession({ job_id: msg.job_id || payload.job_id }));
      return;

    case 'browser.input': {
      // Fire-and-forget: pointer moves arrive in bursts and must not queue replies.
      browserInputChain = browserInputChain.then(async () => {
        const { session } = browserSessionFor(msg);
        if (!session) return;
        try {
          if (!await resumeBrowserSessionPreview()) return;
          await runBrowserInput(session.tabId, await browserViewport(session.tabId), payload.events || []);
          capturePreviewSoon();
        } catch (err) {
          log(`Browser input failed (${err.message})`);
        }
      });
      await browserInputChain;
      return;
    }

    case 'browser.pick':
    case 'browser.snapshot': {
      const jobId = msg.job_id || payload.job_id;
      if (!browserSession || browserSession.jobId !== jobId) {
        sendBrowserResult(msg, { ok: false, error: 'Open the browser for this listing first' });
        return;
      }
      const command = msg.type === 'browser.pick'
        ? { type: 'PICK_FIELD_AT', x_ratio: payload.x_ratio, y_ratio: payload.y_ratio }
        : { type: 'SNAPSHOT_FIELDS' };
      sendBrowserResult(msg, await browserContentCommand(browserSession.tabId, command));
      return;
    }

    case 'browser.act': {
      const { session, error: sessionError } = browserSessionFor(msg);
      if (!session) {
        sendBrowserResult(msg, { ok: false, error: sessionError });
        return;
      }
      let result;
      try {
        if (!await resumeBrowserSessionPreview()) {
          result = { ok: false, error: 'Chrome refused the debugger for this tab' };
        } else {
          result = await runBrowserAction(session, payload);
          capturePreviewSoon(250);
        }
      } catch (err) {
        result = { ok: false, error: err.message };
      }
      sendBrowserResult(msg, result);
      return;
    }
  }
}

chrome.tabs.onRemoved.addListener((tabId) => {
  if (browserSessionOwnsTab(tabId)) {
    browserSession = null;
  }
});

// Fills stop the preview on every exit path, including failures that leave the
// tab open. Bring the seller's live view back once automation lets go.
const BROWSER_KEEPALIVE_MS = 2000;
let browserResuming = false;
setInterval(async () => {
  if (!browserSession || browserResuming || browserAutomationJob()) return;
  if (previewTabId === browserSession.tabId && previewJobId === browserSession.jobId && previewPollTimer) return;
  browserResuming = true;
  try {
    await resumeBrowserSessionPreview();
  } catch (err) {
    log(`Browser preview resume failed (${err.message})`);
  } finally {
    browserResuming = false;
  }
}, BROWSER_KEEPALIVE_MS);
