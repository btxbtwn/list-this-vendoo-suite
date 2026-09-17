// Depop content script
// Fills the Depop listing form (draft only)

(function() {
  'use strict';

  const PLATFORM = 'depop';
  
  // Depop-specific selectors (PLACEHOLDERS - update with real selectors)
  // Depop is React-based with dynamic classes
  const SELECTORS = {
    // Basic info
    description: 'textarea[data-testid="description"], textarea[name="description"], textarea[placeholder*="description"]',

    // Depop doesn't have a separate title - description is primary
    // Price in various currencies
    price: 'input[data-testid="price"], input[name="price"], input[type="number"][placeholder*="price"]',

    // Category selection (multi-level picker)
    categoryButton: 'button[data-testid="category-button"], [data-testid="category-selector"]',

    // Brand (searchable dropdown)
    brandSearch: 'input[data-testid="brand-search"], input[placeholder*="Brand"]',

    // Size (depends on category)
    sizeButton: 'button[data-testid="size-button"], [data-testid="size-selector"]',

    // Condition
    conditionButton: 'button[data-testid="condition-button"], [data-testid="condition-selector"]',

    // Color picker
    colorPicker: '[data-testid="color-picker"], .color-selector',

    // Source (where you got the item)
    source: 'select[name="source"], [data-testid="source-selector"]',

    // Shipping
    shippingPrice: 'input[name="shippingPrice"], input[data-testid="shipping-price"]',

    // Depop Style tags (up to 3)
    styleTags: 'input[data-testid="style-tags"], input[placeholder*="Style"], input[placeholder*="style"]',
    styleDropdown: '[data-testid="style-dropdown"], [role="listbox"]',

    // Occasion (up to 3)
    occasionButton: 'button[data-testid="occasion-button"], [data-testid="occasion-selector"]',

    // Type/Fit/Material (Depop uses "Attributes" or similar)
    typeButton: 'button[data-testid="type-button"], [data-testid="type-selector"]',
    fitButton: 'button[data-testid="fit-button"], [data-testid="fit-selector"]',
    materialButton: 'button[data-testid="material-button"], [data-testid="material-selector"]'
  };

  // Depop's stand-in when the item's brand is not on their list
  const BRAND_FALLBACK = 'Other';

  // Depop condition options
  const CONDITION_MAP = {
    'new': 'Brand new',
    'like new': 'Like new',
    'good': 'Good',
    'fair': 'Fair',
    'poor': 'Poor'
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

  function clickAndSelect(buttonSelector, optionText) {
    const btn = document.querySelector(buttonSelector);
    if (!btn) return false;

    btn.click();
    
    setTimeout(() => {
      // Look for options in modal/dropdown
      const options = document.querySelectorAll('[role="option"], [data-testid*="option"], li[role="button"]');
      for (const opt of options) {
        if (opt.textContent.toLowerCase().includes(optionText.toLowerCase())) {
          opt.click();
          console.log(`[${PLATFORM}] Selected: ${optionText}`);
          return;
        }
      }
      console.log(`[${PLATFORM}] Option not found: ${optionText}`);
    }, 300);

    return true;
  }

  // Depop has no free-text brand field: a brand that is not on their list must
  // fall back to the "Other" option.
  function selectBrand(brand) {
    const input = document.querySelector(SELECTORS.brandSearch);
    if (!input) {
      console.log(`[${PLATFORM}] Brand input not found`);
      return false;
    }

    const search = (term, onMissing) => {
      input.focus();
      input.value = term;
      input.dispatchEvent(new Event('input', { bubbles: true }));

      setTimeout(() => {
        const options = [...document.querySelectorAll('[role="option"], [data-testid*="option"]')];
        const wanted = term.toLowerCase();
        const match = options.find(opt => opt.textContent.trim().toLowerCase() === wanted)
          || options.find(opt => opt.textContent.toLowerCase().includes(wanted));
        if (match) {
          match.click();
          console.log(`[${PLATFORM}] Selected brand: ${match.textContent.trim()}`);
          return;
        }
        onMissing();
      }, 400);
    };

    const selectOther = () => search(BRAND_FALLBACK, () => {
      console.log(`[${PLATFORM}] Brand option "${BRAND_FALLBACK}" not found`);
    });

    if (!brand) {
      selectOther();
      return true;
    }
    search(brand, () => {
      console.log(`[${PLATFORM}] Brand "${brand}" is not on Depop's list. Using ${BRAND_FALLBACK}.`);
      selectOther();
    });
    return true;
  }

  function clickAndSelectMultiple(buttonSelector, optionTexts, maxSelect = 3) {
    if (!optionTexts || optionTexts.length === 0) return false;
    
    const btn = document.querySelector(buttonSelector);
    if (!btn) return false;

    btn.click();
    
    setTimeout(() => {
      let selected = 0;
      const options = document.querySelectorAll('[role="option"], [data-testid*="option"], li[role="button"], button[role="checkbox"]');
      
      for (const opt of options) {
        if (selected >= maxSelect) break;
        
        const optText = opt.textContent.toLowerCase();
        for (const targetText of optionTexts) {
          if (optText.includes(targetText.toLowerCase())) {
            opt.click();
            console.log(`[${PLATFORM}] Selected: ${targetText}`);
            selected++;
            break;
          }
        }
      }
      
      // Close dropdown (press Escape)
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      
      if (selected === 0) {
        console.log(`[${PLATFORM}] No options matched for:`, optionTexts);
      }
    }, 400);

    return true;
  }

  function addStyleTags(styleItems) {
    if (!styleItems || styleItems.length === 0) return;
    
    const input = document.querySelector(SELECTORS.styleTags);
    if (!input) {
      console.log(`[${PLATFORM}] Style input not found`);
      return;
    }

    // Add up to 3 style tags
    const tagsToAdd = styleItems.slice(0, 3);
    
    tagsToAdd.forEach((style, index) => {
      setTimeout(() => {
        input.focus();
        input.value = style;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        
        // Wait for dropdown and click first matching option
        setTimeout(() => {
          const options = document.querySelectorAll('[role="option"], [data-testid*="option"]');
          for (const opt of options) {
            if (opt.textContent.toLowerCase().includes(style.toLowerCase())) {
              opt.click();
              console.log(`[${PLATFORM}] Added style: ${style}`);
              break;
            }
          }
          input.blur();
        }, 300);
      }, index * 600);
    });
  }

  async function fillForm(data) {
    console.log(`[${PLATFORM}] Starting form fill...`, data);

    try {
      await new Promise(r => setTimeout(r, 2000));

      // Depop uses description as primary text (no separate title)
      // Combine title and description
      const fullDesc = data.title + (data.description ? '\n\n' + data.description : '');
      fillField(SELECTORS.description, fullDesc);

      // Price
      fillField(SELECTORS.price, data.price?.toString());

      // Brand (falls back to Other when the brand is not on Depop's list)
      selectBrand(data.brand);

      // Condition
      if (data.condition) {
        const condText = CONDITION_MAP[data.condition.toLowerCase()] || data.condition;
        clickAndSelect(SELECTORS.conditionButton, condText);
      }

      // Size
      if (data.size) {
        setTimeout(() => {
          clickAndSelect(SELECTORS.sizeButton, data.size);
        }, 500);
      }

      // Color - Depop has color chips to click
      if (data.color) {
        setTimeout(() => {
          const colorChips = document.querySelectorAll('[data-testid*="color"], .color-chip, [aria-label*="color"]');
          for (const chip of colorChips) {
            if (chip.getAttribute('aria-label')?.toLowerCase().includes(data.color.toLowerCase()) ||
                chip.getAttribute('data-testid')?.toLowerCase().includes(data.color.toLowerCase())) {
              chip.click();
              console.log(`[${PLATFORM}] Selected color: ${data.color}`);
              break;
            }
          }
        }, 700);
      }

      // Style tags (up to 3) - from data.style or data.styleTags
      if (data.style || data.styleTags) {
        const styles = Array.isArray(data.style) ? data.style : 
                       Array.isArray(data.styleTags) ? data.styleTags :
                       data.style ? [data.style] : [];
        setTimeout(() => {
          addStyleTags(styles);
        }, 900);
      }

      // Occasion (up to 3)
      if (data.occasion) {
        const occasions = Array.isArray(data.occasion) ? data.occasion : [data.occasion];
        setTimeout(() => {
          clickAndSelectMultiple(SELECTORS.occasionButton, occasions, 3);
        }, 1100);
      }

      // Type (from ebay_specifics.type or data.type)
      if (data.type || data.ebay_specifics?.type) {
        const typeValue = data.type || data.ebay_specifics?.type;
        setTimeout(() => {
          clickAndSelect(SELECTORS.typeButton, typeValue);
        }, 1300);
      }

      // Fit
      if (data.fit) {
        setTimeout(() => {
          clickAndSelect(SELECTORS.fitButton, data.fit);
        }, 1500);
      }

      // Material (from ebay_specifics.outer_shell_material or data.material)
      if (data.material || data.ebay_specifics?.outer_shell_material || data.ebay_specifics?.fabric_type) {
        const materialValue = data.material || data.ebay_specifics?.outer_shell_material || data.ebay_specifics?.fabric_type;
        setTimeout(() => {
          clickAndSelect(SELECTORS.materialButton, materialValue);
        }, 1700);
      }

      chrome.runtime.sendMessage({ type: 'FILL_COMPLETE', platform: PLATFORM });
      console.log(`[${PLATFORM}] Form fill complete! Review and save as draft.`);

    } catch (error) {
      console.error(`[${PLATFORM}] Fill error:`, error);
      chrome.runtime.sendMessage({ type: 'FILL_ERROR', platform: PLATFORM, error: error.message });
    }
  }

  function init() {
    if (!window.location.href.includes('/products/create') && 
        !window.location.href.includes('/products/edit')) {
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
