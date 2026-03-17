// eBay content script - REWRITTEN for robustness
// Fills the eBay sell form (draft only)
// Uses attribute-based selectors to handle eBay's dynamic IDs

(function() {
  'use strict';

  const PLATFORM = 'EBAY';
  const DEBUG = true;

  function log(...args) {
    if (DEBUG) console.log(`[${PLATFORM}]`, ...args);
  }

  function error(...args) {
    console.error(`[${PLATFORM}]`, ...args);
  }

  // ===========================================
  // ROBUST SELECTORS (Attribute-based)
  // ===========================================
  const SELECTORS = {
    // Title usually has a stable name or aria-label
    title: 'input[name="title"], input[aria-label="Title"], input[data-testid="textbox"]',
    
    // Condition is often a radio group or dropdown
    // Note: This often requires clicking a "Condition" section first or handling a modal
    conditionDropdown: 'div[id*="condition"] input, input[name="condition"], input[aria-label="Condition"]',
    conditionOptions: 'div[role="option"], span.radio-text',
    
    // Photos
    photoInput: 'input[type="file"][name*="image"]',
    
    // Description (iframe)
    descriptionIframe: 'iframe[title*="Description"], iframe.cke_wysiwyg_frame',
    
    // Pricing
    price: 'input[name="price"], input[aria-label="Price"], input[data-testid="price-input"]',
    
    // Shipping
    shippingWeightLb: 'input[name*="weightMajor"], input[aria-label*="pounds"]',
    shippingWeightOz: 'input[name*="weightMinor"], input[aria-label*="ounces"]',
    
    // Dimensions
    dimLength: 'input[name*="length"], input[aria-label*="Length"]',
    dimWidth: 'input[name*="width"], input[aria-label*="Width"]',
    dimHeight: 'input[name*="height"], input[aria-label*="Height"]',
    
    // Item Specifics (Container)
    itemSpecificsContainer: '#s0-1-5-7-17-1-section-body', // This ID might be dynamic, need fallback
    
    // Brand (Dynamic within item specifics)
    brand: 'input[aria-label="Brand"], input[name="Brand"]',
    
    // Category (Search input)
    categorySearch: 'input[role="combobox"][placeholder*="category"], input[aria-label*="category"]',
  };

  // ===========================================
  // UTILITY FUNCTIONS
  // ===========================================

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function waitForElement(selector, timeout = 10000) {
    return new Promise((resolve, reject) => {
      // Try finding it immediately
      const el = document.querySelector(selector);
      if (el) return resolve(el);

      const observer = new MutationObserver(() => {
        const el = document.querySelector(selector);
        if (el) {
          observer.disconnect();
          resolve(el);
        }
      });

      observer.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => {
        observer.disconnect();
        reject(new Error(`Timeout waiting for: ${selector}`));
      }, timeout);
    });
  }

  function setNativeValue(element, value) {
    const valueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set;
    const prototype = Object.getPrototypeOf(element);
    const prototypeValueSetter = prototype
      ? Object.getOwnPropertyDescriptor(prototype, 'value')?.set
      : null;

    if (valueSetter && prototypeValueSetter && valueSetter !== prototypeValueSetter) {
      prototypeValueSetter.call(element, value);
    } else if (valueSetter) {
      valueSetter.call(element, value);
    } else if (prototypeValueSetter) {
      prototypeValueSetter.call(element, value);
    } else {
      element.value = value;
    }

    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.dispatchEvent(new Event('blur', { bubbles: true }));
  }

  // ===========================================
  // FILL FUNCTIONS
  // ===========================================

  async function fillText(selector, value, fieldName) {
    if (!value) {
      log(`Skipping ${fieldName}: no value`);
      return false;
    }

    // Try to find element
    let el = document.querySelector(selector);
    
    // If not found, try waiting briefly (eBay lazy loads)
    if (!el) {
      try {
        el = await waitForElement(selector, 2000);
      } catch (e) {
        // Ignore timeout
      }
    }

    if (!el) {
      // Fallback: search by label text (expensive but useful for eBay)
      const labels = Array.from(document.querySelectorAll('label'));
      const matchingLabel = labels.find(l => l.innerText.includes(fieldName));
      if (matchingLabel && matchingLabel.control) {
        el = matchingLabel.control;
      }
    }

    if (!el) {
      error(`${fieldName}: selector not found - ${selector}`);
      return false;
    }

    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(200);
    el.focus();
    
    // Handle React/Native inputs
    try {
      setNativeValue(el, String(value));
    } catch (e) {
      el.value = String(value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }

    await sleep(200);
    log(`✓ ${fieldName}: "${value}"`);
    return true;
  }

  async function fillDescription(value) {
    if (!value) return false;

    // Check for iframe
    const iframe = document.querySelector(SELECTORS.descriptionIframe);
    if (iframe) {
      try {
        const doc = iframe.contentDocument || iframe.contentWindow.document;
        if (doc && doc.body) {
          doc.body.innerHTML = value.replace(/\n/g, '<br>');
          log('✓ Description (iframe)');
          return true;
        }
      } catch (e) {
        error('Description iframe access error:', e);
      }
    }

    // Fallback: Standard text area
    return fillText('textarea[name="description"]', value, 'Description (Textarea)');
  }

  async function fillCondition(condition) {
    if (!condition) return false;
    
    // Mapping
    // 1000 = New
    // 3000 = Used
    // eBay UI varies. Sometimes it's a radio, sometimes a dropdown.
    
    const conditionText = condition.toLowerCase();
    let targetText = 'Used';
    if (conditionText.includes('new') || conditionText === '1000') targetText = 'New';
    if (conditionText.includes('parts')) targetText = 'For parts';

    log(`Attempting to set condition to "${targetText}"`);

    // Strategy 1: Look for radio buttons with text
    const radios = Array.from(document.querySelectorAll('div[role="radio"], input[type="radio"]'));
    for (const radio of radios) {
      // Check label or nearby text
      const label = radio.getAttribute('aria-label') || radio.nextElementSibling?.innerText || '';
      if (label.includes(targetText)) {
        radio.click();
        log('✓ Condition (Radio)');
        return true;
      }
    }

    // Strategy 2: Dropdown
    const dropdown = document.querySelector(SELECTORS.conditionDropdown);
    if (dropdown) {
      dropdown.click();
      await sleep(500);
      const options = Array.from(document.querySelectorAll(SELECTORS.conditionOptions));
      const match = options.find(o => o.innerText.includes(targetText));
      if (match) {
        match.click();
        log('✓ Condition (Dropdown)');
        return true;
      }
    }

    return false;
  }

  // ===========================================
  // MAIN FILL LOGIC
  // ===========================================

  async function fillForm(data) {
    log('Starting fill...', data);
    const results = { success: [], failed: [] };

    try {
      // 1. Title
      if (await fillText(SELECTORS.title, data.title, 'Title')) {
        results.success.push('title');
      } else {
        results.failed.push('title');
      }

      // 2. Condition
      if (await fillCondition(data.condition)) {
        results.success.push('condition');
      } else {
        results.failed.push('condition');
      }

      // 3. Photos (TODO: Drag and drop simulation is hard, skipping for now)

      // 4. Item Specifics (Brand, etc)
      // These often load LATE after category is picked.
      // We will try to fill what we see.
      
      if (data.brand) {
         if (await fillText(SELECTORS.brand, data.brand, 'Brand')) {
             results.success.push('brand');
         }
         // Fallback: Generic attribute search
         else if (await fillText(`input[value="Brand"] + input`, data.brand, 'Brand (Fallback)')) {
             results.success.push('brand');
         }
      }

      // 5. Description
      if (await fillDescription(data.description)) {
        results.success.push('description');
      } else {
        results.failed.push('description');
      }

      // 6. Price
      // Determine format (Auction vs Fixed) - assuming Fixed Price for now
      const price = data.price || data.listing_price;
      if (await fillText(SELECTORS.price, price, 'Price')) {
        results.success.push('price');
      } else {
        results.failed.push('price');
      }

      // 7. Shipping (Weight/Dims)
      // Usually requires toggling "Package weight & dimensions"
      
      // Try to find the toggle if fields aren't visible
      if (!document.querySelector(SELECTORS.shippingWeightLb)) {
          const toggle = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Package weight'));
          if (toggle) {
              toggle.click();
              await sleep(1000);
          }
      }

      let weightLb = data.weight_lb;
      let weightOz = data.weight_oz;
      
      // Handle nested weight
      if (data.weight) {
          weightLb = data.weight.pounds || data.weight.lb;
          weightOz = data.weight.ounces || data.weight.oz;
      }

      if (weightLb || weightOz) {
        await fillText(SELECTORS.shippingWeightLb, weightLb || 0, 'Weight Lb');
        await fillText(SELECTORS.shippingWeightOz, weightOz || 0, 'Weight Oz');
      }

      log('=== FILL COMPLETE ===');
      chrome.runtime.sendMessage({ type: 'FILL_COMPLETE', platform: PLATFORM, results });

    } catch (err) {
      error('Fatal error:', err);
      chrome.runtime.sendMessage({ type: 'FILL_ERROR', platform: PLATFORM, error: err.message });
    }
  }

  // ===========================================
  // INIT
  // ===========================================

  function init() {
    // Check if on a listing page
    if (!window.location.href.includes('ebay.com/sl/') && !window.location.href.includes('ebay.com/sell/')) {
      return;
    }

    log('Loaded on eBay sell page');

    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      if (msg.type === 'START_FILL' && msg.data) {
        fillForm(msg.data);
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
