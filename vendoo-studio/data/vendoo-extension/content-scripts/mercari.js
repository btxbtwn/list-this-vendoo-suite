// Mercari content script
// Fills the Mercari listing form (draft only)

(function() {
  'use strict';

  const PLATFORM = 'mercari';
  
  // Mercari-specific selectors (PLACEHOLDERS - update with real selectors)
  const SELECTORS = {
    title: 'input[name="name"], input[data-testid="ItemName"], input[placeholder*="name"]',
    description: 'textarea[name="description"], textarea[data-testid="ItemDescription"]',
    
    // Mercari uses category picker modal
    categoryButton: 'button[data-testid="CategoryButton"], .category-selector',
    
    // Condition dropdown
    condition: 'select[name="condition"], button[data-testid="ConditionButton"]',
    
    // Brand input
    brand: 'input[name="brand"], input[data-testid="BrandInput"]',
    
    // Price
    price: 'input[name="price"], input[data-testid="Price"], input[type="number"]',
    
    // Shipping - Mercari has specific shipping options
    shippingPayer: 'input[name="shippingPayer"], button[data-testid="ShippingPayerButton"]',
    shippingMethod: 'select[name="shippingMethod"]',
    
    // Item weight for shipping calculation
    weight: 'select[name="weight"], button[data-testid="WeightButton"]',
    
    // Color and size (when applicable)
    color: 'input[name="color"], select[name="color"]',
    size: 'select[name="size"], input[name="size"]'
  };

  // Mercari condition values
  const CONDITION_MAP = {
    'new': 'NEW',
    'like new': 'LIKE_NEW', 
    'good': 'GOOD',
    'fair': 'FAIR',
    'poor': 'POOR'
  };

  function waitForElement(selector, timeout = 10000) {
    return new Promise((resolve, reject) => {
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
      setTimeout(() => { observer.disconnect(); reject(new Error(`Not found: ${selector}`)); }, timeout);
    });
  }

  function fillField(selector, value) {
    if (!value) return false;
    const el = document.querySelector(selector);
    if (!el) {
      console.log(`[${PLATFORM}] Selector not found: ${selector}`);
      return false;
    }

    el.focus();
    
    // Clear existing value
    el.value = '';
    
    // Simulate typing for React
    for (const char of value.toString()) {
      el.value += char;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
    
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    console.log(`[${PLATFORM}] Filled: ${selector}`);
    return true;
  }

  function selectDropdown(selector, value) {
    const el = document.querySelector(selector);
    if (!el) return false;

    if (el.tagName === 'SELECT') {
      const options = Array.from(el.options);
      const match = options.find(opt => 
        opt.value.toLowerCase().includes(value.toLowerCase()) ||
        opt.text.toLowerCase().includes(value.toLowerCase())
      );
      if (match) {
        el.value = match.value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
    } else if (el.tagName === 'BUTTON') {
      // Modal-based selector - click to open, then find option
      el.click();
      setTimeout(() => {
        const options = document.querySelectorAll('[role="option"], [data-testid*="Option"]');
        for (const opt of options) {
          if (opt.textContent.toLowerCase().includes(value.toLowerCase())) {
            opt.click();
            break;
          }
        }
      }, 300);
      return true;
    }
    return false;
  }

  async function fillForm(data) {
    console.log(`[${PLATFORM}] Starting form fill...`, data);

    try {
      await new Promise(r => setTimeout(r, 2000));

      // Basic fields
      fillField(SELECTORS.title, data.title);
      fillField(SELECTORS.description, data.description);
      fillField(SELECTORS.price, data.price?.toString());
      
      // Brand & No Brand Logic
      fillField(SELECTORS.brand, data.brand);
      
      // Vendoo-specific Mercari 'No Brand' checkbox
      // Selector provided: input[name="listings.mercari.overrides.noBrand"]
      const NO_BRAND_SELECTOR = 'input[id="listings.mercari.overrides.noBrand"]';
      
      // Wait briefly to see if brand populated (Vendoo might clear it if invalid)
      await new Promise(r => setTimeout(r, 500));
      
      const brandInput = document.querySelector(SELECTORS.brand);
      const noBrandCheckbox = document.querySelector(NO_BRAND_SELECTOR);
      
      if (brandInput && !brandInput.value) {
        console.log(`[${PLATFORM}] Brand empty (or invalid). Clicking 'No Brand'.`);
        if (noBrandCheckbox && !noBrandCheckbox.checked) {
          noBrandCheckbox.click();
        }
      } else if (!data.brand) {
        // If no brand in data, click it immediately
        if (noBrandCheckbox && !noBrandCheckbox.checked) {
          noBrandCheckbox.click();
        }
      }

      // Condition mapping
      if (data.condition) {
        const conditionVal = CONDITION_MAP[data.condition.toLowerCase()] || data.condition;
        selectDropdown(SELECTORS.condition, conditionVal);
      }

      // Size and color if available
      if (data.size) selectDropdown(SELECTORS.size, data.size);
      if (data.color) fillField(SELECTORS.color, data.color);

      // Category - would need modal interaction
      // Placeholder: just log what category we want
      if (data.category) {
        console.log(`[${PLATFORM}] Category to select: ${data.category}`);
        // Real implementation would click categoryButton and navigate tree
      }

      chrome.runtime.sendMessage({ type: 'FILL_COMPLETE', platform: PLATFORM });
      console.log(`[${PLATFORM}] Form fill complete! Review and save as draft.`);

    } catch (error) {
      console.error(`[${PLATFORM}] Fill error:`, error);
      chrome.runtime.sendMessage({ type: 'FILL_ERROR', platform: PLATFORM, error: error.message });
    }
  }

  function init() {
    if (!window.location.href.includes('/sell') && 
        !window.location.href.includes('/create')) {
      return;
    }

    console.log(`[${PLATFORM}] Content script loaded`);
    const startType = `START_${PLATFORM.toUpperCase()}`;

    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      if (msg.type === 'PING') {
        sendResponse({ ok: true, platform: PLATFORM });
        return true;
      }

      if ((msg.type === 'START_FILL' || msg.type === startType) && msg.data) {
        fillForm(msg.data);
        sendResponse({ ok: true });
        return true;
      }

      return false;
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
