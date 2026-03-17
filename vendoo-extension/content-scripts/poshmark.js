// Poshmark content script - Auto Saver
// Vendoo fills the form; we just click "Next" / "List" / "Save"

(function() {
  'use strict';

  const PLATFORM = 'POSHMARK';
  const DEBUG = true;

  function log(msg) {
    if (DEBUG) console.log(`[${PLATFORM}]`, msg);
  }

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  async function clickButtonByText(text) {
      const buttons = Array.from(document.querySelectorAll('button, a.btn, div.btn'));
      const target = buttons.find(b => b.innerText && b.innerText.trim().toLowerCase() === text.toLowerCase());
      
      if (target) {
          log(`Clicking button: "${target.innerText}"`);
          target.scrollIntoView({ block: 'center' });
          await sleep(500);
          target.click();
          return true;
      }
      return false;
  }

  async function finishListing() {
      log('Attempting to save/list...');
      
      // 1. Try "Next" (Standard flow)
      let clicked = await clickButtonByText('Next');
      
      // 2. If Next clicked, wait for "List This Item"
      if (clicked) {
          log('Clicked Next. Waiting for "List This Item"...');
          await sleep(2000);
          const listed = await clickButtonByText('List This Item');
          if (listed) log('Clicked "List This Item"');
          else log('Could not find "List This Item" (maybe already listed?)');
          return;
      }

      // 3. Try "Update" (Editing)
      if (!clicked) clicked = await clickButtonByText('Update');
      
      // 4. Try "Save Draft" (if requested)
      if (!clicked) clicked = await clickButtonByText('Save Draft');
      
      // 5. Try just "Save" (Generic)
      if (!clicked) clicked = await clickButtonByText('Save');

      if (clicked) {
          log('Success!');
          chrome.runtime.sendMessage({ type: 'FILL_COMPLETE', platform: PLATFORM });
      } else {
          log('Could not find any Save/Next buttons.');
          chrome.runtime.sendMessage({ type: 'FILL_ERROR', platform: PLATFORM, error: 'Button not found' });
      }
  }

  function init() {
    if (!window.location.href.includes('poshmark.com')) return;
    log('Content script loaded');

    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      if (msg.type === 'START_FILL' || msg.type === 'START_POSHMARK') {
        finishListing();
        sendResponse({ ok: true });
        return true;
      }
      if (msg.type === 'PING') {
        sendResponse({ ok: true, platform: PLATFORM });
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
