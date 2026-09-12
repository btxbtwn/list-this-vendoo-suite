// Etsy content script
// Fills the Etsy listing form (draft only)

(function() {
  'use strict';

  const PLATFORM = 'etsy';
  
  // Etsy-specific selectors (PLACEHOLDERS - update with real selectors)
  // Etsy has a complex multi-section form
  const SELECTORS = {
    // Photos section (handled separately)
    photoDropzone: '.photo-upload-region, [data-region="photos"]',
    
    // Listing details
    title: 'input[name="title"], #listing-title, textarea[aria-label="Title"]',
    
    // Category picker (searchable)
    categorySearch: 'input[data-search="category"], #taxonomy-search, input[placeholder*="category"]',
    
    // About this listing
    whoMadeIt: 'select[name="who_made"], #who_made',
    whatIsIt: 'select[name="what_is_it"], #is_supply',
    whenMade: 'select[name="when_made"], #when_made',
    
    // Description (rich text editor)
    description: 'textarea[name="description"], #description-text-area-input',
    
    // Tags (comma separated)
    tags: 'input[name="tags"], #tags-input',
    
    // Price and inventory
    price: 'input[name="price"], #price-input',
    quantity: 'input[name="quantity"], #quantity-input',
    sku: 'input[name="sku"], #sku-input',
    
    // Variations (size, color, etc)
    addVariation: 'button[data-action="add-variation"]',
    
    // Shipping
    shippingProfile: 'select[name="shipping_profile"], #shipping-profile-select',
    
    // Personalization
    personalization: 'input[name="is_customizable"]'
  };

  // Etsy "who made it" options
  const WHO_MADE_MAP = {
    'handmade': 'i_did',
    'vintage': 'collective',
    'supply': 'someone_else'
  };

  // Etsy "when made" options
  const WHEN_MADE_MAP = {
    'made to order': 'made_to_order',
    '2024': '2020_2024',
    '2023': '2020_2024',
    'vintage': 'before_1999'
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
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    console.log(`[${PLATFORM}] Filled: ${selector}`);
    return true;
  }

  function selectOption(selector, value) {
    const el = document.querySelector(selector);
    if (!el || el.tagName !== 'SELECT') return false;

    const options = Array.from(el.options);
    const match = options.find(opt => 
      opt.value === value || 
      opt.value.toLowerCase().includes(value.toLowerCase()) ||
      opt.text.toLowerCase().includes(value.toLowerCase())
    );

    if (match) {
      el.value = match.value;
      el.dispatchEvent(new Event('change', { bubbles: true }));
      console.log(`[${PLATFORM}] Selected ${selector}: ${match.text}`);
      return true;
    }
    return false;
  }

  async function fillForm(data) {
    console.log(`[${PLATFORM}] Starting form fill...`, data);

    try {
      await new Promise(r => setTimeout(r, 2000));

      // Title
      fillField(SELECTORS.title, data.title);

      // Description
      fillField(SELECTORS.description, data.description);

      // Price and inventory
      fillField(SELECTORS.price, data.price?.toString());
      fillField(SELECTORS.quantity, data.quantity?.toString() || '1');
      fillField(SELECTORS.sku, data.sku);

      // Tags (Etsy loves tags)
      if (data.tags && Array.isArray(data.tags)) {
        fillField(SELECTORS.tags, data.tags.join(', '));
      } else if (data.keywords) {
        fillField(SELECTORS.tags, data.keywords);
      }

      // Who made it (default: I did)
      const whoMade = data.whoMade || 'handmade';
      selectOption(SELECTORS.whoMadeIt, WHO_MADE_MAP[whoMade.toLowerCase()] || 'i_did');

      // What is it (default: finished product)
      selectOption(SELECTORS.whatIsIt, data.isSupply ? 'supply' : 'product');

      // When made
      if (data.whenMade) {
        const whenVal = WHEN_MADE_MAP[data.whenMade.toLowerCase()] || data.whenMade;
        selectOption(SELECTORS.whenMade, whenVal);
      }

      // Category search
      if (data.category) {
        fillField(SELECTORS.categorySearch, data.category);
        // Real implementation would need to click through suggestions
        console.log(`[${PLATFORM}] Category to select: ${data.category}`);
      }

      chrome.runtime.sendMessage({ type: 'FILL_COMPLETE', platform: PLATFORM });
      console.log(`[${PLATFORM}] Form fill complete! Review and save as draft.`);

    } catch (error) {
      console.error(`[${PLATFORM}] Fill error:`, error);
      chrome.runtime.sendMessage({ type: 'FILL_ERROR', platform: PLATFORM, error: error.message });
    }
  }

  function init() {
    if (!window.location.href.includes('/listings/create') && 
        !window.location.href.includes('/listing/create') &&
        !window.location.href.includes('/listings/edit')) {
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
