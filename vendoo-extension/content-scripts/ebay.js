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

  function warn(...args) {
    console.warn(`[${PLATFORM}]`, ...args);
  }

  // ===========================================
  // ROBUST SELECTORS (Attribute-based)
  // ===========================================
  const SELECTORS = {
    // Title usually has a stable name or aria-label
    title: 'input[name="title"], input[aria-label="Title"], input[data-testid="textbox"]',
    
    // Condition is often a radio group or dropdown
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
    
    // Brand
    brand: 'input[aria-label="Brand"], input[name="Brand"]',
    
    // Category (Search input)
    categorySearch: 'input[role="combobox"][placeholder*="category"], input[aria-label*="category"]',
  };

  // Field name mapping: JSON key → eBay form label text
  const fieldNameMap = {
    'type': 'Type', 'department': 'Department', 'size': 'Size',
    'sizeType': 'Size Type', 'style': 'Style', 'brand': 'Brand',
    'color': 'Color', 'material': 'Material', 'pattern': 'Pattern',
    'fit': 'Fit', 'sleeveLength': 'Sleeve Length', 'sleeveType': 'Sleeve Type',
    'neckline': 'Neckline', 'closure': 'Closure', 'accents': 'Accents',
    'features': 'Features', 'theme': 'Theme', 'season': 'Season',
    'occasion': 'Occasion', 'strapType': 'Strap Type',
    'countryOfOrigin': 'Country of Origin', 'fabricType': 'Fabric Type',
    'vintage': 'Vintage', 'handmade': 'Handmade', 'personalize': 'Personalize',
    'garmentCare': 'Garment Care', 'unitQuantity': 'Unit Quantity',
    'unitType': 'Unit Type', 'mpn': 'MPN', 'upc': 'UPC',
    'character': 'Character', 'characterFamily': 'Character Family',
    'performanceActivity': 'Performance Activity', 'yearManufactured': 'Year Manufactured',
    'collarStyle': 'Collar Style', 'rise': 'Rise', 'inseam': 'Inseam',
    'waist': 'Waist'
  };

  // Label patterns for fallback matching (lowercase)
  const fieldLabelPatterns = {
    'type': ['type', 'item type'],
    'department': ['department'],
    'size': ['size'],
    'sizeType': ['size type', 'size type gender'],
    'style': ['style'],
    'brand': ['brand'],
    'color': ['color', 'primary color'],
    'material': ['material'],
    'pattern': ['pattern'],
    'fit': ['fit'],
    'sleeveLength': ['sleeve length'],
    'sleeveType': ['sleeve type'],
    'neckline': ['neckline'],
    'closure': ['closure'],
    'accents': ['accents'],
    'features': ['features'],
    'theme': ['theme'],
    'season': ['season'],
    'occasion': ['occasion'],
    'strapType': ['strap type'],
    'countryOfOrigin': ['country of origin', 'country/region'],
    'fabricType': ['fabric type', 'fabric'],
    'vintage': ['vintage'],
    'handmade': ['handmade'],
    'personalize': ['personalize', 'customized'],
    'garmentCare': ['garment care'],
    'unitQuantity': ['unit quantity'],
    'unitType': ['unit type'],
    'mpn': ['mpn', 'manufacturer part number'],
    'upc': ['upc', 'universal product code'],
    'character': ['character'],
    'characterFamily': ['character family'],
    'performanceActivity': ['performance activity', 'activity'],
    'yearManufactured': ['year manufactured', 'year'],
    'collarStyle': ['collar style'],
    'rise': ['rise'],
    'inseam': ['inseam'],
    'waist': ['waist']
  };

  // ===========================================
  // UTILITY FUNCTIONS
  // ===========================================

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

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

  // Find an input by its associated label text
  function findInputByLabel(labelText) {
    const labels = Array.from(document.querySelectorAll('label, span.field-label, div.label'));
    for (const label of labels) {
      if (label.textContent.trim().toLowerCase().includes(labelText.toLowerCase())) {
        // Try for/input control
        const forId = label.getAttribute('for');
        if (forId) {
          const input = document.getElementById(forId);
          if (input) return input;
        }
        // Try sibling input
        const parent = label.parentElement;
        if (parent) {
          const input = parent.querySelector('input, select, textarea, div[role="combobox"]');
          if (input) return input;
        }
        // Try next sibling
        let sibling = label.nextElementSibling;
        while (sibling) {
          if (sibling.matches?.('input, select, textarea, div[role="combobox"]')) return sibling;
          const inner = sibling.querySelector('input, select, textarea, div[role="combobox"]');
          if (inner) return inner;
          sibling = sibling.nextElementSibling;
        }
      }
    }
    return null;
  }

  // Find an input by aria-label
  function findInputByAriaLabel(labelText) {
    const inputs = document.querySelectorAll('input[aria-label], div[role="combobox"][aria-label], textarea[aria-label]');
    for (const input of inputs) {
      if (input.getAttribute('aria-label').toLowerCase().includes(labelText.toLowerCase())) {
        return input;
      }
    }
    return null;
  }

  // ===========================================
  // FILL FUNCTIONS
  // ===========================================

  async function fillText(selector, value, fieldName) {
    if (!value) {
      log(`Skipping ${fieldName}: no value`);
      return false;
    }

    let el = document.querySelector(selector);
    
    if (!el) {
      try {
        el = await waitForElement(selector, 2000);
      } catch (e) {
        // Ignore timeout
      }
    }

    if (!el) {
      // Fallback: search by label text
      el = findInputByLabel(fieldName) || findInputByAriaLabel(fieldName);
    }

    if (!el) {
      error(`${fieldName}: not found`);
      return false;
    }

    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(200);
    el.focus();
    
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

    return fillText('textarea[name="description"]', value, 'Description (Textarea)');
  }

  async function fillCondition(condition) {
    if (!condition) return false;
    
    const conditionText = condition.toLowerCase();
    let targetText = 'Used';
    if (conditionText.includes('new') || conditionText === '1000') targetText = 'New';
    if (conditionText.includes('parts')) targetText = 'For parts';

    log(`Attempting to set condition to "${targetText}"`);

    // Strategy 1: Radio buttons
    const radios = Array.from(document.querySelectorAll('div[role="radio"], input[type="radio"]'));
    for (const radio of radios) {
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
  // CATEGORY SPECIFICS FILLING
  // ===========================================

  async function fillDropdownField(el, value, fieldName, isStrict = false, isMulti = false) {
    if (!value || !el) return false;

    const valueStr = String(value).trim();
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(200);

    // Click to open dropdown / focus input
    el.focus();
    el.click();
    await sleep(300);

    // Type the value to filter
    setNativeValue(el, valueStr);
    await sleep(500);

    // Look for matching option in dropdown
    const options = Array.from(document.querySelectorAll(
      'div[role="option"], li[role="option"], span.dropdown-option, div.fake-menu-item'
    ));

    if (options.length > 0) {
      for (const option of options) {
        const optText = (option.textContent || '').trim().toLowerCase();
        const valLower = valueStr.toLowerCase();
        
        if (isStrict) {
          if (optText === valLower) {
            option.click();
            log(`  ✓ ${fieldName}: "${valueStr}" (exact match)`);
            return true;
          }
        } else {
          if (optText.includes(valLower) || valLower.includes(optText)) {
            option.click();
            log(`  ✓ ${fieldName}: "${valueStr}" (partial match)`);
            return true;
          }
        }
      }
      // Close dropdown if no match found (for multi-value, keep it open for next value)
      if (!isMulti) {
        el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      }
    }

    // If no dropdown options, it's a text field — value already set
    log(`  ✓ ${fieldName}: "${valueStr}" (text field)`);
    return true;
  }

  async function fillCategorySpecifics(data) {
    const specifics = data.ebay_specifics || data.categorySpecifics || {};
    if (!specifics || Object.keys(specifics).length === 0) {
      log('No category specifics to fill');
      return;
    }

    log('Filling category specifics:', Object.keys(specifics));

    // Wait a moment for category specifics to load after category selection
    await sleep(1500);

    for (const [key, value] of Object.entries(specifics)) {
      if (!value) continue;

      const fieldName = fieldNameMap[key] || key;
      const patterns = fieldLabelPatterns[key] || [fieldName.toLowerCase()];
      
      // Try multiple strategies to find the input
      let el = null;

      // Strategy 1: Find by aria-label
      for (const pattern of patterns) {
        el = findInputByAriaLabel(pattern);
        if (el) break;
      }

      // Strategy 2: Find by label text
      if (!el) {
        for (const pattern of patterns) {
          el = findInputByLabel(pattern);
          if (el) break;
        }
      }

      // Strategy 3: Find by field name in ID (categoryId_FieldName pattern)
      if (!el) {
        const allInputs = document.querySelectorAll('input, select, textarea, div[role="combobox"]');
        const fieldNameLower = fieldName.toLowerCase();
        const fieldNameUnderscored = fieldNameLower.replace(/\s+/g, '_');
        for (const input of allInputs) {
          if (!input.id) continue;
          const idLower = input.id.toLowerCase();
          // Match both: _unit quantity (with space) and _Unit_Quantity (with underscore)
          if (idLower.includes('categoryspecifics') && (
              idLower.includes('_' + fieldNameLower) ||
              idLower.includes('_' + fieldNameUnderscored)
          )) {
            el = input;
            break;
          }
        }
      }

      if (el) {
        // Handle comma-separated values (features, etc.)
        const values = (typeof value === 'string' && value.includes(','))
          ? value.split(',').map(v => v.trim())
          : [value];

        const isSizeField = key.toLowerCase().includes('size');
        
        if (values.length > 1) {
          for (const item of values) {
            await fillDropdownField(el, item, fieldName, isSizeField, true);
            await sleep(400);
          }
        } else {
          await fillDropdownField(el, values[0], fieldName, isSizeField, false);
        }
      } else {
        warn(`  ⚠ Could not find field for ${key} ("${fieldName}")`);
      }

      await sleep(300);
    }
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

      // 3. Brand
      if (data.brand) {
         if (await fillText(SELECTORS.brand, data.brand, 'Brand')) {
             results.success.push('brand');
         }
         else if (await fillText(`input[value="Brand"] + input`, data.brand, 'Brand (Fallback)')) {
             results.success.push('brand');
         }
      }

      // 4. Category Specifics (features, neckline, season, etc.)
      if (data.ebay_specifics || data.categorySpecifics) {
        await fillCategorySpecifics(data);
      }

      // 5. Description
      if (await fillDescription(data.description)) {
        results.success.push('description');
      } else {
        results.failed.push('description');
      }

      // 6. Price
      const price = data.price || data.listing_price;
      if (await fillText(SELECTORS.price, price, 'Price')) {
        results.success.push('price');
      } else {
        results.failed.push('price');
      }

      // 7. Shipping (Weight/Dims)
      if (!document.querySelector(SELECTORS.shippingWeightLb)) {
          const toggle = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Package weight'));
          if (toggle) {
              toggle.click();
              await sleep(1000);
          }
      }

      let weightLb = data.weight_lb;
      let weightOz = data.weight_oz;
      
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