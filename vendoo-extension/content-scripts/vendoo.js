// Vendoo content script - Speed Optimized Version
// Reduced delays, parallel operations, efficient event dispatch

(function() {
  'use strict';

  const PLATFORM = 'VENDOO';
  const CONTENT_SCRIPT_VERSION = String(globalThis.CONTENT_SCRIPT_VERSION || '');

  if (CONTENT_SCRIPT_VERSION && window.__vendooStudioBridgeVersion === CONTENT_SCRIPT_VERSION) {
    return;
  }

  if (typeof window.__vendooStudioBridgeCleanup === 'function') {
    try { window.__vendooStudioBridgeCleanup(); } catch (_) {}
  }

  window.__vendooStudioBridge = true;
  window.__vendooStudioBridgeVersion = CONTENT_SCRIPT_VERSION;

  const DEBUG = true;
  let statusBox;
  let runtimeListener = null;

  window.__vendooStudioBridgeCleanup = function cleanupStudioBridge() {
    if (runtimeListener) {
      chrome.runtime.onMessage.removeListener(runtimeListener);
      runtimeListener = null;
    }
    window.__vendooStudioBridge = false;
    window.__vendooStudioBridgeVersion = '';
    window.__vendooStudioBridgeCleanup = null;
  };

  // Configuration for speed
  const CONFIG = {
    SLEEP_SHORT: 50,      // Quick operations
    SLEEP_MEDIUM: 200,    // Form interactions
    SLEEP_LONG: 500,      // Dropdown opening
    SLEEP_RETRY: 300,     // Between retries
    MAX_RETRIES: 2,       // Reduced from 3
    ENABLE_PARALLEL: true // Fill non-dependent fields in parallel
  };

  function createStatusBox() {
      if (document.getElementById('vendoo-debug-box')) {
          statusBox = document.getElementById('vendoo-debug-box');
          return;
      }
      statusBox = document.createElement('div');
      statusBox.id = 'vendoo-debug-box';
      statusBox.style.cssText = `
          position: fixed;
          bottom: 10px;
          left: 10px;
          width: 400px;
          height: 350px;
          background: rgba(0,0,0,0.92);
          color: #0f0;
          font-family: monospace;
          font-size: 11px;
          padding: 10px;
          z-index: 99999;
          overflow-y: auto;
          border-radius: 5px;
          user-select: text;
          pointer-events: auto;
          white-space: pre-wrap;
          border: 1px solid #333;
      `;
      document.body.appendChild(statusBox);
  }

  function log(msg) {
      if (DEBUG) console.log(`[${PLATFORM}]`, msg);
      if (statusBox) {
          const line = document.createElement('div');
          line.innerText = `> ${msg}`;
          line.style.marginBottom = '2px';
          statusBox.appendChild(line);
          statusBox.scrollTop = statusBox.scrollHeight;
      }
  }

  function error(msg) {
      console.error(`[${PLATFORM}]`, msg);
      if (statusBox) {
          const line = document.createElement('div');
          line.style.color = '#f55';
          line.style.fontWeight = 'bold';
          line.innerText = `ERROR: ${msg}`;
          line.style.marginBottom = '2px';
          statusBox.appendChild(line);
          statusBox.scrollTop = statusBox.scrollHeight;
      }
  }

  function warn(msg) {
      console.warn(`[${PLATFORM}]`, msg);
      if (statusBox) {
          const line = document.createElement('div');
          line.style.color = '#ff9800';
          line.innerText = `WARN: ${msg}`;
          line.style.marginBottom = '2px';
          statusBox.appendChild(line);
          statusBox.scrollTop = statusBox.scrollHeight;
      }
  }

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  // ============================================
  // FILL LEDGER — per-step field outcomes
  // ============================================

  let currentFillMarketplace = 'general';
  const fillLedger = [];
  let currentPatchEntryId = '';

  function previewValue(value) {
    if (value == null) return '';
    const text = Array.isArray(value) ? value.join(', ') : String(value);
    const compact = text.replace(/\s+/g, ' ').trim();
    return compact.length > 80 ? `${compact.slice(0, 77)}...` : compact;
  }

  function beginFillLog(marketplace) {
    fillLedger.length = 0;
    currentFillMarketplace = marketplace || 'general';
  }

  function recordFill(entry) {
    const field = String(entry.field || '').trim();
    if (!field) return;
    fillLedger.push({
      id: entry.id || currentPatchEntryId || undefined,
      marketplace: currentFillMarketplace,
      field,
      status: entry.status,
      reason: entry.reason || '',
      selector: entry.selector || '',
      value_preview: Object.prototype.hasOwnProperty.call(entry, 'value')
        ? previewValue(entry.value)
        : (entry.value_preview || ''),
    });
  }

  function summarizeFillLog(entries) {
    const summary = { filled: 0, skipped: 0, not_found: 0, failed: 0, uncertain: 0, new: 0 };
    for (const entry of entries) {
      if (summary[entry.status] != null) summary[entry.status] += 1;
    }
    return summary;
  }

  const FIELD_KEY_ALIASES = {
    'listing price': 'price',
    'buy it now price': 'price',
    'pounds': 'weight (lbs)',
    'ounces': 'weight (oz)',
    'us size': 'size',
    'vendoo labels': 'labels',
    'vendoo internal notes': 'notes',
    'internal notes': 'notes',
    'who made it': 'who made',
    'what is it': 'what is it',
    'when was it made': 'when made',
    'when made': 'when made',
    'primary color': 'color',
    'cost of goods': 'cost of goods',
  };

  function normalizeFieldKey(value) {
    const key = String(value || '')
      .replace(/^(ebay|etsy|poshmark|mercari|depop)\s+/i, '')
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/[_*?-]+/g, ' ')
      .replace(/[^\w\s]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
    return FIELD_KEY_ALIASES[key] || key;
  }

  function selectorFor(el, fallback) {
    if (el && el.id) return `#${el.id}`;
    return fallback || '';
  }

  function fieldLabelForControl(el) {
    if (!el) return '';
    if (el.labels && el.labels.length) {
      const text = (el.labels[0].textContent || '').replace(/\s+/g, ' ').trim();
      if (text) return text;
    }
    const aria = el.getAttribute && el.getAttribute('aria-label');
    if (aria) return String(aria).replace(/\s+/g, ' ').trim();
    if (el.id) {
      const escaped = (window.CSS && typeof window.CSS.escape === 'function')
        ? window.CSS.escape(el.id)
        : String(el.id).replace(/"/g, '\\"');
      const lab = document.querySelector(`label[for="${escaped}"]`);
      if (lab) {
        const text = (lab.textContent || '').replace(/\s+/g, ' ').trim();
        if (text) return text;
      }
    }
    let container = el.parentElement;
    for (let depth = 0; depth < 4 && container; depth += 1) {
      const nearby = container.querySelector('label, legend, [class*="Label"], [class*="label"]');
      if (nearby && nearby !== el) {
        const text = (nearby.textContent || '').replace(/\s+/g, ' ').trim();
        if (text && text.length <= 80) return text;
      }
      container = container.parentElement;
    }
    if (el.id) {
      return String(el.id.split('.').pop() || '').replace(/[_-]+/g, ' ').trim();
    }
    return '';
  }

  function isListingFormControl(el) {
    if (!el) return false;
    const id = el.id || '';
    const name = el.name || '';
    if (/generalDetails|listings\.|categoryV2|^labels$/i.test(id) || /generalDetails|listings\./i.test(name)) return true;
    if (el.getAttribute && el.getAttribute('role') === 'category-search-field') return true;
    const parent = el.closest('[id]');
    const parentId = parent ? parent.id : '';
    return /listings|generalDetails|category/i.test(parentId);
  }

  function isCurrentMarketplaceControl(el) {
    if (!isListingFormControl(el)) return false;
    const id = el.id || '';
    const name = el.name || '';
    const parent = el.closest('[id]');
    const parentId = parent ? parent.id : '';
    const marketplace = String(currentFillMarketplace || 'general').toLowerCase();
    if (marketplace === 'general') {
      if (/^listings\./i.test(id) || /^listings\./i.test(name)) return false;
      return /generalDetails|categoryV2|^labels$/i.test(`${id} ${name} ${parentId}`) ||
        (el.getAttribute && el.getAttribute('role') === 'category-search-field');
    }
    const prefix = `listings.${marketplace}.`;
    return id.startsWith(prefix) || name.startsWith(prefix) || parentId.startsWith(prefix);
  }

  function selectorMatchesControl(selector, el) {
    if (!selector || !el) return false;
    if (el.id) {
      const raw = `#${el.id}`;
      const escaped = `#${String(el.id).replace(/\./g, '\\.')}`;
      if (selector === raw || selector === escaped) return true;
    }
    return false;
  }

  function controlAlreadyLogged(el, labelKey) {
    for (const entry of fillLedger) {
      if (normalizeFieldKey(entry.field) === labelKey) return true;
      if (selectorMatchesControl(entry.selector, el)) return true;
    }
    return false;
  }

  function appendUnmappedFields() {
    const seen = new Set();
    const controls = document.querySelectorAll('input, textarea, select, [role="combobox"]');

    for (const el of controls) {
      if (el.closest && el.closest('#vendoo-debug-box')) continue;
      const type = String(el.type || '').toLowerCase();
      if (['hidden', 'submit', 'button', 'reset', 'file', 'image'].includes(type)) continue;
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) === 0) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (!isCurrentMarketplaceControl(el)) continue;

      const label = fieldLabelForControl(el);
      const key = normalizeFieldKey(label);
      if (!key || seen.has(key) || controlAlreadyLogged(el, key)) continue;
      if (fieldLooksFilled(el)) continue;
      seen.add(key);
      recordFill({
        field: label,
        status: 'new',
        reason: 'Visible on form, not filled by automation',
        selector: selectorFor(el, ''),
        value: el.value || displayedFieldValue(el) || '',
      });
    }
  }

  function finishFillLog(options) {
    if (!options || !options.skipUnmapped) {
      appendUnmappedFields();
    }
    const summary = summarizeFillLog(fillLedger);
    log(`=== FILL LOG ${currentFillMarketplace} ===`);
    log(`filled ${summary.filled} · skipped ${summary.skipped} · not found ${summary.not_found} · failed ${summary.failed} · uncertain ${summary.uncertain} · new ${summary.new}`);
    fillLedger
      .filter((entry) => entry.status === 'failed' || entry.status === 'not_found')
      .forEach((entry) => warn(`  ${entry.field}: ${entry.reason || entry.status}`));
    fillLedger
      .filter((entry) => entry.status === 'new')
      .forEach((entry) => log(`  NEW FIELD: ${entry.field}${entry.selector ? ` (${entry.selector})` : ''}`));
    return {
      marketplace: currentFillMarketplace,
      summary,
      entries: fillLedger.slice(),
    };
  }

  // ============================================
  // SELECTOR MAPS
  // ============================================

  const VENDOO_SELECTORS = {
    title: '#generalDetails\\.title',
    description: '#generalDetails\\.description',
    brand: '#generalDetails\\.brand',
    condition: '#generalDetails\\.condition',
    primaryColor: '#generalDetails\\.primaryColor',
    secondaryColor: '#generalDetails\\.secondaryColor',
    zipCode: '#generalDetails\\.zipCode',
    tags: '#generalDetails\\.tags',
    quantity: '#generalDetails\\.quantity',
    size: '#generalDetails\\.size\\.option\\.value',
    sizeType: '#generalDetails\\.size\\.scale\\.value',
    sku: '#generalDetails\\.sku',
    weightLb: '#generalDetails\\.weight\\.pounds',
    weightOz: '#generalDetails\\.weight\\.ounces',
    length: '#generalDetails\\.dimensions\\.length',
    width: '#generalDetails\\.dimensions\\.width',
    height: '#generalDetails\\.dimensions\\.height',
    price: '#generalDetails\\.price',
    cost: '#generalDetails\\.cost',
    labels: '#labels',
    notes: '#generalDetails\\.notes',
    category: '#categoryV2, [role="category-input"]',
  };

  const CATEGORY_RESULT_SELECTORS = [
    '[role="option"]',
    '[role="treeitem"]',
    '.MuiAutocomplete-option',
    '[role="listbox"] [role="option"]',
    'li[role="option"]',
  ].join(', ');

  const CATEGORY_POPUP_SELECTORS = [
    '[role="presentation"]',
    '.MuiAutocomplete-popper',
    '[role="listbox"]',
    '[class*="popover"]',
    '[class*="menu"]',
  ].join(', ');

  // ============================================
  // OPTIMIZED HELPER FUNCTIONS
  // ============================================

  function setReactValue(element, value) {
    if (!element) return;
    
    // Single efficient property set
    const prototype = Object.getPrototypeOf(element);
    const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
    
    if (descriptor && descriptor.set) {
      descriptor.set.call(element, value);
    } else {
      element.value = value;
    }
    
    // Minimal event dispatch - input and change usually sufficient
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  }

  async function clearInput(element) {
      if (!element || !element.value) return;
      element.focus();
      setReactValue(element, '');
      await sleep(CONFIG.SLEEP_SHORT);
  }

  function normalizeText(text) {
      return (text || '')
          .toString()
          .replace(/([a-z])([A-Z])/g, '$1 $2')
          .replace(/[_-]+/g, ' ')
          .replace(/\s+/g, ' ')
          .trim()
          .toLowerCase();
  }

  function optionMatchText(el) {
      const labelled = (el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('title'))) || '';
      return (el.innerText || el.textContent || labelled || '').trim().split('\n')[0].trim();
  }

  // Live Vendoo dropdown labels as of 2026-09-08.
  // See skills/list-this/references/vendoo-dropdown-options.md
  const MARKETPLACE_CONDITION_MAP = {
      vendoo: {
          'New With Tags/Box': 'New With Tags/Box',
          'New Without Tags/Box': 'New Without Tags/Box',
          'New With Imperfections': 'New With Imperfections',
          'Pre-Owned - Excellent': 'Pre-Owned - Excellent',
          'Pre-Owned - Good': 'Pre-Owned - Good',
          'Pre-Owned - Fair': 'Pre-Owned - Fair',
          'Poor (Major flaws)': 'Poor (Major flaws)',
      },
      ebay: {
          'New With Tags/Box': 'New with tags',
          'New Without Tags/Box': 'New without tags',
          'New With Imperfections': 'New with imperfections',
          'Pre-Owned - Excellent': 'Pre-owned - Excellent',
          'Pre-Owned - Good': 'Pre-owned - Good',
          'Pre-Owned - Fair': 'Pre-owned - Fair',
          'Poor (Major flaws)': 'Pre-owned - Fair',
      },
      poshmark: {
          'New With Tags/Box': 'New With Tags (NWT)',
          'New Without Tags/Box': 'Like New',
          'New With Imperfections': 'Good',
          'Pre-Owned - Excellent': 'Like New',
          'Pre-Owned - Good': 'Good',
          'Pre-Owned - Fair': 'Fair',
          'Poor (Major flaws)': 'Fair',
      },
      mercari: {
          'New With Tags/Box': 'New (New with tags)',
          'New Without Tags/Box': 'Like new (New without tags)',
          'New With Imperfections': 'Good (Gently used)',
          'Pre-Owned - Excellent': 'Like new (New without tags)',
          'Pre-Owned - Good': 'Good (Gently used)',
          'Pre-Owned - Fair': 'Fair (Used)',
          'Poor (Major flaws)': 'Poor (Major flaws)',
      },
      depop: {
          'New With Tags/Box': 'Brand new',
          'New Without Tags/Box': 'Like new',
          'New With Imperfections': 'Used - Good',
          'Pre-Owned - Excellent': 'Used - Excellent',
          'Pre-Owned - Good': 'Used - Good',
          'Pre-Owned - Fair': 'Used - Fair',
          'Poor (Major flaws)': 'Used - Fair',
      },
  };

  function canonicalizeCondition(raw) {
      if (raw == null) return raw;
      const original = String(raw).trim();
      if (!original) return original;
      if (MARKETPLACE_CONDITION_MAP.vendoo[original]) return original;

      const t = original.toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();

      if (t.includes('imperfection')) return 'New With Imperfections';
      if (t.includes('poor') || t.includes('major flaw')) return 'Poor (Major flaws)';
      if (/\bnwt\b/.test(t) || (t.includes('new') && t.includes('tag') && !t.includes('without'))) {
          return 'New With Tags/Box';
      }
      if (t.includes('brand new')) return 'New With Tags/Box';
      if (t.includes('like new') || (t.includes('new') && t.includes('without'))) {
          return 'New Without Tags/Box';
      }
      if (t.includes('excellent')) return 'Pre-Owned - Excellent';
      if (t.includes('fair')) return 'Pre-Owned - Fair';
      if (t.includes('good') || t.includes('used') || t.includes('pre owned')) {
          return 'Pre-Owned - Good';
      }
      if (t.includes('new')) return 'New Without Tags/Box';
      return original;
  }

  function mapCondition(raw, marketplace) {
      if (raw == null || String(raw).trim() === '') return raw;
      const canonical = canonicalizeCondition(raw);
      const table = MARKETPLACE_CONDITION_MAP[marketplace] || MARKETPLACE_CONDITION_MAP.vendoo;
      const mapped = table[canonical] || canonical;
      if (mapped !== String(raw).trim()) {
          log(`  Condition ${marketplace}: "${raw}" → "${mapped}"`);
      }
      return mapped;
  }

  const VENDOO_COLORS = [
      'Beige', 'Black', 'Blue', 'Brown', 'Cream', 'Gold', 'Gray', 'Green',
      'Orange', 'Multicolor', 'Pink', 'Purple', 'Red', 'Silver', 'Yellow', 'Tan', 'White',
  ];

  const COLOR_ALIASES = {
      grey: 'Gray',
      gray: 'Gray',
      multi: 'Multicolor',
      multicolor: 'Multicolor',
      'multi color': 'Multicolor',
      'multi-color': 'Multicolor',
      navy: 'Navy',
      burgundy: 'Burgundy',
      maroon: 'Burgundy',
      wine: 'Burgundy',
      khaki: 'Khaki',
      camel: 'Beige',
      beige: 'Beige',
      tan: 'Tan',
      cream: 'Cream',
      ivory: 'Cream',
      'off white': 'Cream',
      teal: 'Blue',
      turquoise: 'Blue',
      aqua: 'Blue',
      charcoal: 'Gray',
      slate: 'Gray',
      mint: 'Green',
      sage: 'Green',
      olive: 'Green',
      coral: 'Orange',
      salmon: 'Orange',
      peach: 'Orange',
      lavender: 'Purple',
      lilac: 'Purple',
      mauve: 'Purple',
  };

  const VENDOO_COLOR_IDENTITY = Object.fromEntries(VENDOO_COLORS.map(c => [c, c]));

  const MARKETPLACE_COLOR_MAP = {
      vendoo: {
          ...VENDOO_COLOR_IDENTITY,
          Grey: 'Gray',
          Multi: 'Multicolor',
          Navy: 'Blue',
          Burgundy: 'Red',
          Khaki: 'Beige',
      },
      ebay: {
          ...VENDOO_COLOR_IDENTITY,
          Grey: 'Gray',
          Multi: 'Multicolor',
          Navy: 'Blue',
          Burgundy: 'Red',
          Khaki: 'Beige',
      },
      etsy: {
          ...VENDOO_COLOR_IDENTITY,
          Grey: 'Gray',
          Multi: 'Multicolor',
          Navy: 'Blue',
          Burgundy: 'Red',
          Khaki: 'Beige',
      },
      poshmark: {
          ...VENDOO_COLOR_IDENTITY,
          Beige: 'Tan',
          Multicolor: null,
          Grey: 'Gray',
          Multi: null,
          Navy: 'Blue',
          Burgundy: 'Red',
          Khaki: 'Tan',
      },
      depop: {
          ...VENDOO_COLOR_IDENTITY,
          Gray: 'Grey',
          Grey: 'Grey',
          Multicolor: 'Multi',
          Multi: 'Multi',
          Beige: 'Tan',
          Navy: 'Navy',
          Burgundy: 'Burgundy',
          Khaki: 'Khaki',
      },
  };

  function canonicalizeColor(raw) {
      if (raw == null) return raw;
      const original = String(raw).trim();
      if (!original) return original;

      const namedColors = [...VENDOO_COLORS, 'Grey', 'Multi', 'Navy', 'Burgundy', 'Khaki'];
      const exact = namedColors.find(c => c.toLowerCase() === original.toLowerCase());
      if (exact) return exact === 'Grey' ? 'Gray' : exact === 'Multi' ? 'Multicolor' : exact;

      const t = original.toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
      if (COLOR_ALIASES[t]) return COLOR_ALIASES[t];

      const words = new Set(t.split(' '));
      const contained = namedColors
          .filter(c => words.has(c.toLowerCase()))
          .sort((a, b) => b.length - a.length)[0];
      if (contained) {
          return contained === 'Grey' ? 'Gray' : contained === 'Multi' ? 'Multicolor' : contained;
      }

      return original;
  }

  function mapColor(raw, marketplace) {
      if (raw == null || String(raw).trim() === '') return raw;
      const canonical = canonicalizeColor(raw);
      const table = MARKETPLACE_COLOR_MAP[marketplace] || MARKETPLACE_COLOR_MAP.vendoo;
      if (Object.prototype.hasOwnProperty.call(table, canonical)) {
          const mapped = table[canonical];
          if (!mapped) {
              warn(`Color ${marketplace}: "${raw}" has no ${marketplace} option; skipping`);
              return null;
          }
          if (mapped !== String(raw).trim()) {
              log(`  Color ${marketplace}: "${raw}" → "${mapped}"`);
          }
          return mapped;
      }
      return canonical;
  }

  function mappingMarketplace(marketplace) {
      const mp = String(marketplace || currentFillMarketplace || 'vendoo').toLowerCase();
      if (!mp || mp === 'general' || mp === 'unknown') return 'vendoo';
      return mp;
  }

  function mapPatchValue(marketplace, fieldName, value) {
      if (value == null || String(value).trim() === '') return value;
      const key = normalizeFieldKey(fieldName);
      const mp = mappingMarketplace(marketplace);
      if (/\bcolou?rs?\b/.test(key) || key === 'color' || /color$/i.test(key)) {
          return mapColor(value, mp);
      }
      if (/\bcondition\b/.test(key)) {
          return mapCondition(value, mp);
      }
      if (key === 'when made') {
          return normalizeEtsyWhenMade(value);
      }
      if (mp === 'ebay' && key === 'type') {
          return normalizeEbaySpecificValue('type', value);
      }
      if (mp === 'ebay' && key === 'year manufactured') {
          return normalizeEbaySpecificValue('yearManufactured', value) || value;
      }
      return value;
  }

  const ETSY_CATEGORY_VALUE_MAPS = {
      clothingStyle: [
          ['western', 'Western & cowboy'],
          ['cowboy', 'Western & cowboy'],
          ['minimalist', 'Minimalist'],
          ['minimal', 'Minimalist'],
          ['workwear', 'Minimalist'],
          ['office', 'Minimalist'],
          ['business', 'Minimalist'],
          ['boho', 'Boho & hippie'],
          ['hippie', 'Boho & hippie'],
          ['goth', 'Gothic'],
          ['harajuku', 'Harajuku'],
          ['lolita', 'Lolita'],
          ['military', 'Military'],
          ['mod', 'Mod'],
          ['preppy', 'Preppy'],
          ['prep', 'Preppy'],
          ['rave', 'Rave'],
          ['pin up', 'Pin-up & rockabilly'],
          ['pin-up', 'Pin-up & rockabilly'],
          ['rockabilly', 'Pin-up & rockabilly'],
          ['rocker', 'Rocker'],
          ['grunge', 'Rocker'],
          ['graphic', 'Streetwear'],
          ['casual', 'Streetwear'],
          ['streetwear', 'Streetwear'],
          ['street', 'Streetwear'],
          ['menswear', 'Menswear'],
          ['tailored', 'Menswear'],
          ['suiting', 'Menswear']
      ],
      closure: [
          ['button', 'Buttons'],
          ['zip', 'Zipper'],
          ['hook & eye', 'Hook & eye'],
          ['hook and eye', 'Hook & eye'],
          ['drawstring', 'Drawstring'],
          ['lace up', 'Lace-up'],
          ['lace-up', 'Lace-up'],
          ['pullover', 'Pullover'],
          ['elastic', 'Elastic'],
          ['snap', 'Snap'],
          ['tie', 'Tie'],
          ['toggle', 'Toggle'],
          ['velcro', 'Velcro']
      ],
      collarStyle: [
          ['mandarin', 'Band'],
          ['band', 'Band'],
          ['peter pan', 'Peter Pan'],
          ['ruffle', 'Ruffle'],
          ['sailor', 'Sailor'],
          ['shawl', 'Shawl'],
          ['wing', 'Wing tip'],
          ['jabot', 'Jabot'],
          ['high neck', 'High neck'],
          ['funnel', 'Funnel'],
          ['cutaway', 'Cutaway'],
          ['tab', 'Tab'],
          ['bow', 'Bow'],
          ['butterfly', 'Butterfly'],
          ['cape', 'Cape'],
          ['rolled', 'Rolled'],
          ['button down', 'Straight'],
          ['button-down', 'Straight'],
          ['point', 'Straight'],
          ['spread', 'Straight'],
          ['collared', 'Straight'],
          ['collar', 'Straight']
      ]
  };

  function mapByIncludes(rawValue, mappings) {
      if (!rawValue || !Array.isArray(mappings) || mappings.length === 0) {
          return rawValue;
      }

      const normalizedValue = normalizeText(rawValue);
      for (const [needle, mappedValue] of mappings) {
          if (normalizedValue.includes(needle)) {
              return mappedValue;
          }
      }

      return rawValue;
  }

  function normalizeEtsyWhenMade(rawValue) {
      if (!rawValue) return rawValue;

      const value = String(rawValue).trim();
      const normalizedValue = normalizeText(value);
      const explicitMappings = [
          ['made to order', 'Made To Order (Not Yet Made)'],
          ['not yet made', 'Made To Order (Not Yet Made)'],
          ['2020 - 2026', '2020 - 2026 (Recently)'],
          ['2020s', '2020 - 2026 (Recently)'],
          ['2010 - 2019', '2010 - 2019 (Recently)'],
          ['2010s', '2010 - 2019 (Recently)'],
          ['2007 - 2009', '2007 - 2009 (Recently)'],
          ['2000 - 2006', '2000 - 2006 (Vintage)'],
          ['2000s', '2000 - 2006 (Vintage)'],
          ['before 2007', 'Before 2007 (Vintage)'],
          ['vintage', 'Before 2007 (Vintage)'],
          ['1990s', '1990s (Vintage)'],
          ['1980s', '1980s (Vintage)'],
          ['1970s', '1970s (Vintage)'],
          ['1960s', '1960s (Vintage)'],
          ['1950s', '1950s (Vintage)'],
          ['1940s', '1940s (Vintage)'],
          ['1930s', '1930s (Vintage)'],
          ['1920s', '1920s (Vintage)'],
          ['1910s', '1910s (Vintage)'],
          ['1900', '1900 - 1909 (Vintage)'],
          ['1800s', '1800s (Vintage)'],
          ['1700s', '1700s (Vintage)'],
          ['before 1700', 'Before 1700 (Vintage)'],
          ['unknown', '2020 - 2026 (Recently)'],
          ['does not apply', '2020 - 2026 (Recently)'],
          ['n/a', '2020 - 2026 (Recently)'],
          ['not sure', '2020 - 2026 (Recently)']
      ];

      for (const [needle, mappedValue] of explicitMappings) {
          if (normalizedValue.includes(normalizeText(needle))) {
              return mappedValue;
          }
      }

      const yearMatch = normalizedValue.match(/\b(17\d{2}|18\d{2}|19\d{2}|20\d{2})\b/);
      if (!yearMatch) {
          return value;
      }

      const year = Number(yearMatch[1]);
      if (year >= 2020) return '2020 - 2026 (Recently)';
      if (year >= 2010) return '2010 - 2019 (Recently)';
      if (year >= 2007) return '2007 - 2009 (Recently)';
      if (year >= 2000) return '2000 - 2006 (Vintage)';
      if (year >= 1990) return '1990s (Vintage)';
      if (year >= 1980) return '1980s (Vintage)';
      if (year >= 1970) return '1970s (Vintage)';
      if (year >= 1960) return '1960s (Vintage)';
      if (year >= 1950) return '1950s (Vintage)';
      if (year >= 1940) return '1940s (Vintage)';
      if (year >= 1930) return '1930s (Vintage)';
      if (year >= 1920) return '1920s (Vintage)';
      if (year >= 1910) return '1910s (Vintage)';
      if (year >= 1900) return '1900 - 1909 (Vintage)';
      if (year >= 1800) return '1800s (Vintage)';
      if (year >= 1700) return '1700s (Vintage)';
      return 'Before 1700 (Vintage)';
  }

  function normalizeEtsyCategorySpecificValue(fieldName, rawValue) {
      if (!rawValue) return rawValue;

      const skipUnmapped = {
          occasion: ['everyday', 'casual', 'n/a'],
          graphic: ['graphic', 'n/a'],
          fabric: ['cotton', 'cotton blend'],
          pattern: ['graphic', 'graphic print'],
      };
      const skipValues = skipUnmapped[fieldName];
      if (skipValues && skipValues.includes(normalizeText(rawValue))) {
          return null;
      }

      const mappings = ETSY_CATEGORY_VALUE_MAPS[fieldName];
      if (!mappings) {
          return rawValue;
      }

      return mapByIncludes(rawValue, mappings);
  }

  function isVisibleElement(el) {
      return Boolean(el) && (el.offsetParent !== null || el.getClientRects().length > 0);
  }

  function isAttachedElement(el) {
      return Boolean(el) && el.isConnected !== false;
  }

  function isEtsyCategorySpecificInput(input) {
      return Boolean(input?.id) && input.id.startsWith('listings.etsy.categorySpecifics.');
  }

  function isEbayCategorySpecificInput(input) {
      if (!input) return false;
      const id = String(input.id || '');
      const name = String(input.name || '');
      return id.startsWith('listings.ebay.categorySpecifics.') ||
          name.startsWith('listings.ebay.categorySpecifics.');
  }

  function isDepopSpecificInput(input) {
      if (!input) return false;
      const id = String(input.id || '');
      const name = String(input.name || '');
      return id.startsWith('listings.depop.') || name.startsWith('listings.depop.');
  }

  function findInputsNearLabel(labelEl, filterFn = () => true) {
      if (!labelEl) return [];

      const forId = labelEl.getAttribute?.('for');
      if (forId) {
          const directInput = document.getElementById(forId);
          if (isVisibleElement(directInput) && filterFn(directInput)) {
              return [directInput];
          }
      }

      let container = labelEl;
      for (let depth = 0; depth < 6 && container; depth++) {
          const candidates = Array.from(
              container.querySelectorAll('input:not([type="hidden"]), textarea, select, [role="combobox"]')
          ).filter(candidate => isVisibleElement(candidate) && filterFn(candidate));

          if (candidates.length > 0) return candidates;

          container = container.parentElement;
      }

      return [];
  }

  function findInputNearLabel(labelEl, filterFn = () => true) {
      return findInputsNearLabel(labelEl, filterFn)[0] || null;
  }

  function findInputByLabelPatterns(labelPatterns, filterFn = () => true) {
      const normalizedPatterns = labelPatterns.map(normalizeText).filter(Boolean);
      if (normalizedPatterns.length === 0) return null;

      const labels = Array.from(document.querySelectorAll(
          'label, legend, div[class*="Label"], span[class*="Label"], span[class*="label"], div[class*="label"], h3, h4, p, span[class*="title"], div[class*="title"]'
      ));

      for (const labelEl of labels) {
          if (!isVisibleElement(labelEl)) continue;

          const labelText = normalizeText(labelEl.innerText || labelEl.textContent || '');
          if (!labelText) continue;
          if (!normalizedPatterns.some(pattern => labelText.includes(pattern))) continue;

          const input = findInputNearLabel(labelEl, filterFn);
          if (input) return input;
      }

      return null;
  }

  function findInputByExactLabel(labelText, filterFn = () => true) {
      const want = normalizeText(labelText).replace(/\s*\*$/, '');
      if (!want) return null;

      const labels = Array.from(document.querySelectorAll(
          'label, legend, div[class*="Label"], span[class*="Label"], span[class*="label"], div[class*="label"], h3, h4, p, span[class*="title"], div[class*="title"]'
      ));

      for (const labelEl of labels) {
          if (!isVisibleElement(labelEl)) continue;
          const text = normalizeText(labelEl.innerText || labelEl.textContent || '').replace(/\s*\*$/, '');
          if (text !== want) continue;
          const input = findInputNearLabel(labelEl, filterFn);
          if (input) return input;
      }

      return null;
  }

  function isEnabledField(el) {
      if (!el) return false;
      if (el.disabled) return false;
      if (el.getAttribute('aria-disabled') === 'true') return false;
      return true;
  }

  function isMarketplaceInput(marketplace) {
      return (input) => {
          const id = String(input?.id || '');
          const name = String(input?.name || '');
          const prefix = `listings.${marketplace}.`;
          return id.startsWith(prefix) || name.startsWith(prefix);
      };
  }

  function resolveMarketplaceField(marketplace, labelPatterns, selectors = []) {
      let fallback = null;
      for (const sel of selectors) {
          try {
              const el = document.querySelector(sel);
              if (!el) continue;
              if (isVisibleElement(el) && isEnabledField(el)) return el;
              if (isVisibleElement(el) && !fallback) fallback = el;
          } catch (_) {}
      }
      const labeled = findInputByLabelPatterns(labelPatterns, isMarketplaceInput(marketplace));
      if (labeled && isEnabledField(labeled)) return labeled;
      return labeled || fallback;
  }

  async function waitForMarketplaceField(marketplace, labelPatterns, selectors, attempts = 8) {
      for (let i = 0; i < attempts; i++) {
          const el = resolveMarketplaceField(marketplace, labelPatterns, selectors);
          if (el && isEnabledField(el)) return el;
          await sleep(CONFIG.SLEEP_RETRY);
      }
      return resolveMarketplaceField(marketplace, labelPatterns, selectors);
  }

  async function closeOpenMenus() {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
      await sleep(CONFIG.SLEEP_SHORT);
  }

  function displayedFieldValue(el) {
      if (!el) return '';
      const direct = (el.value || '').trim();
      if (direct) return direct;
      const chips = listedChipValues(el);
      if (chips.length) return chips.join(', ');
      const selectShown = el.closest?.('.MuiSelect-root, .MuiInputBase-root, .MuiAutocomplete-root')
          ?.querySelector('.MuiSelect-select, [class*="MuiSelect-select"]');
      if (selectShown) {
          const text = (selectShown.innerText || selectShown.textContent || '').replace(/\u200b/g, '').trim();
          if (text) return text.split('\n')[0].trim();
      }
      const combo = (el.getAttribute && el.getAttribute('role') === 'combobox') ? el : el.closest?.('[role="combobox"]');
      if (combo) {
          const text = (combo.textContent || '').replace(/\u200b/g, '').trim().split('\n')[0].trim();
          if (text && text.length < 80) return text;
      }
      return '';
  }

  function listedChipValues(el) {
      const root = el?.closest?.('.MuiAutocomplete-root, .MuiFormControl-root') || el?.parentElement;
      if (!root) return [];
      return uniqueStrings(Array.from(root.querySelectorAll('.MuiChip-label')).map((chip) =>
          (chip.textContent || '').replace(/\u00a0/g, ' ').trim()
      ));
  }

  function fieldHasChip(el, value) {
      const want = normalizeOptionValue(value);
      if (!want) return false;
      return listedChipValues(el).some((chip) => normalizeOptionValue(chip) === want);
  }

  function fieldLooksFilled(el) {
      if (!el) return false;
      const value = displayedFieldValue(el);
      if (!value) return false;
      const placeholder = (el.getAttribute && el.getAttribute('placeholder')) || '';
      if (placeholder && normalizeOptionValue(value) === normalizeOptionValue(placeholder)) return false;
      return !/^(select|choose|size|primary color|secondary color|condition|brand|shipping label)\b/i.test(value);
  }

  function normalizeOptionValue(text) {
      return String(text || '')
          .replace(/[–—]/g, '-')
          .replace(/[*?]+/g, '')
          .replace(/[_/]+/g, ' ')
          .replace(/-/g, ' ')
          .replace(/\s+/g, ' ')
          .trim()
          .toLowerCase();
  }

  function optionMatchesValue(optionText, value, isStrict) {
      const got = normalizeOptionValue(optionText);
      const want = normalizeOptionValue(value);
      if (!got || !want || got === '----' || got === 'select') return false;
      if (got === want) return true;
      const sizeWant = want.replace(/\s+/g, '');
      if (/^(xxs|xs|s|m|l|xl|xxl|xxxl|os|onesize)$/.test(sizeWant)) {
          const sizeGot = got.split(' ')[0].replace(/\s+/g, '');
          if (sizeGot === sizeWant) return true;
      }
      if (isStrict) return false;
      const shorter = got.length <= want.length ? got : want;
      const longer = got.length <= want.length ? want : got;
      // Require at least 3 chars on the shorter side so values like "US" do not
      // fuzzy-match "Plus size" via the embedded "us" substring.
      if (shorter.length < 3) return false;
      return longer.includes(shorter);
  }

  function isDropdownLike(el) {
      if (!el) return false;
      if (el instanceof HTMLSelectElement) return true;
      const role = el.getAttribute && el.getAttribute('role');
      if (role === 'combobox' || role === 'listbox' || role === 'menu') return true;
      const popup = el.getAttribute && el.getAttribute('aria-haspopup');
      if (popup === 'listbox' || popup === 'true' || popup === 'menu') return true;
      const autocomplete = el.getAttribute && el.getAttribute('aria-autocomplete');
      if (autocomplete === 'list' || autocomplete === 'both') return true;
      if (el instanceof HTMLInputElement && (el.readOnly || el.getAttribute('aria-expanded') != null)) return true;
      if (el.closest?.('[role="combobox"], [role="listbox"], .MuiAutocomplete-root, .MuiSelect-root, .react-select__control, [class*="MuiSelect"], [class*="MuiAutocomplete"]')) {
          return true;
      }
      const inputRoot = el.closest?.('.MuiInputBase-root, [class*="MuiInputBase-root"]');
      return Boolean(inputRoot?.querySelector('.MuiSelect-select, [class*="MuiSelect-icon"], [class*="MuiAutocomplete-endAdornment"], [class*="MuiArrowDropDown"]'));
  }

  const DROPDOWN_FIELD_HINT = /\b(condition|brand|color|size|category|shipping|occasion|style|department|type|who made|when made|source|scale|material|pattern|features|sleeve|neckline|fit|rise|inseam|wash|closure)\b/i;
  const MULTI_CHIP_FIELD_HINT = /\b(tags?|labels?|materials?|features?|accents?|occasions?|seasons?|themes?)\b/i;

  function shouldFillAsDropdown(el, fieldName) {
      return isDropdownLike(el) || DROPDOWN_FIELD_HINT.test(String(fieldName || ''));
  }

  function isMultiChipField(fieldName) {
      return MULTI_CHIP_FIELD_HINT.test(String(fieldName || ''));
  }

  function splitChipValues(value) {
      const parts = Array.isArray(value) ? value : [value];
      return uniqueStrings(parts.flatMap((part) =>
          String(part == null ? '' : part).split(',').map((item) => item.trim()).filter(Boolean)
      ));
  }

  const DROPDOWN_OPTION_SELECTOR = [
      '[role="option"]',
      '.MuiAutocomplete-option',
      '.react-select__option',
      'li[role="option"]',
      '.MuiMenuItem-root',
      '.MuiListItem-root',
  ].join(', ');

  function listOpenDropdownOptions() {
      const roots = document.querySelectorAll(
          '[role="listbox"], .MuiAutocomplete-popper, .MuiMenu-paper, .MuiPopover-paper, .react-select__menu, .react-select__menu-list, [role="presentation"]'
      );
      const collect = (requireVisible) => {
          const seen = new Set();
          const options = [];
          const usable = requireVisible ? isVisibleElement : isAttachedElement;
          const addNode = (node) => {
              if (seen.has(node) || !usable(node)) return;
              const text = optionMatchText(node);
              const lower = (text || '').toLowerCase();
              if (!text || lower.includes('create your description') || lower.includes('description with ai')) return;
              seen.add(node);
              options.push({ el: node, text });
          };
          for (const root of roots) {
              if (!usable(root)) continue;
              root.querySelectorAll(DROPDOWN_OPTION_SELECTOR).forEach(addNode);
          }
          if (options.length === 0) {
              document.querySelectorAll(DROPDOWN_OPTION_SELECTOR).forEach(addNode);
          }
          return options;
      };
      const visible = collect(true);
      return visible.length ? visible : collect(false);
  }

  function findMatchingOption(value, isStrict) {
      const options = listOpenDropdownOptions();
      const exact = options.find((option) => optionMatchesValue(option.text, value, true));
      if (exact) return exact.el;
      if (isStrict) return null;
      const fuzzy = options.find((option) => optionMatchesValue(option.text, value, false));
      return fuzzy ? fuzzy.el : null;
  }

  function findHighlightedOption(value, isStrict) {
      const options = listOpenDropdownOptions();
      const highlighted = options.find((option) =>
          option.el.getAttribute('aria-selected') === 'true' ||
          option.el.classList.contains('Mui-focused') ||
          option.el.classList.contains('Mui-focusVisible') ||
          option.el.getAttribute('data-focus') === 'true'
      );
      if (highlighted && optionMatchesValue(highlighted.text, value, isStrict)) return highlighted.el;
      if (!isStrict && options.length === 1 && optionMatchesValue(options[0].text, value, false)) {
          return options[0].el;
      }
      return null;
  }

  function dispatchKey(el, key) {
      if (!el) return;
      const keyCode = key === 'Enter' ? 13 : key === 'Escape' ? 27 : key === 'ArrowDown' ? 40 : key === ',' ? 188 : 0;
      const code = key === ',' ? 'Comma' : key;
      const opts = { key, code, keyCode, which: keyCode, bubbles: true, cancelable: true };
      el.dispatchEvent(new KeyboardEvent('keydown', opts));
      el.dispatchEvent(new KeyboardEvent('keyup', opts));
  }

  async function commitChipValue(el, value) {
      if (!el || value == null || String(value).trim() === '') return;
      el.focus();
      await clearInput(el);
      setReactValue(el, String(value).trim());
      await sleep(CONFIG.SLEEP_SHORT);
      dispatchKey(el, ',');
      await sleep(CONFIG.SLEEP_SHORT);
      if ((el.value || '').trim()) {
          dispatchKey(el, 'Enter');
          await sleep(CONFIG.SLEEP_SHORT);
      }
      if (el.value) await clearInput(el);
  }

  async function clickDropdownOption(optionEl) {
      if (!optionEl) return;
      optionEl.scrollIntoView({ block: 'nearest', behavior: 'instant' });
      const mouseEventOptions = { bubbles: true, cancelable: true, view: window };
      try {
          optionEl.dispatchEvent(new PointerEvent('pointerdown', mouseEventOptions));
      } catch (_) {}
      optionEl.dispatchEvent(new MouseEvent('mousedown', mouseEventOptions));
      try {
          optionEl.dispatchEvent(new PointerEvent('pointerup', mouseEventOptions));
      } catch (_) {}
      optionEl.dispatchEvent(new MouseEvent('mouseup', mouseEventOptions));
      optionEl.dispatchEvent(new MouseEvent('click', mouseEventOptions));
      if (typeof optionEl.click === 'function') optionEl.click();
      await sleep(CONFIG.SLEEP_MEDIUM);
  }

  function uniqueStrings(values) {
      const seen = new Set();
      const out = [];
      for (const value of values) {
          const trimmed = String(value || '').trim();
          if (!trimmed) continue;
          const key = trimmed.toLowerCase();
          if (seen.has(key)) continue;
          seen.add(key);
          out.push(trimmed);
      }
      return out;
  }

  function brandFillCandidates(brand) {
      const candidates = [];
      if (brand) {
          candidates.push(brand);
          String(brand).split(/[\s/&,]+/).forEach(part => {
              if (part && part.length > 2 && !/^(the|and|co|inc|llc)$/i.test(part)) {
                  candidates.push(part);
              }
          });
      }
      candidates.push('Other');
      return uniqueStrings(candidates);
  }

  function getInputContextTexts(input) {
      const texts = new Set();
      const addText = value => {
          const normalized = normalizeText(value);
          if (normalized) texts.add(normalized);
      };

      if (!input) return [];

      addText(input.getAttribute('aria-label'));
      addText(input.getAttribute('placeholder'));
      addText(input.name);
      addText(input.id);

      ['aria-labelledby', 'aria-describedby'].forEach(attr => {
          const ids = (input.getAttribute(attr) || '').split(/\s+/).filter(Boolean);
          for (const id of ids) {
              addText(document.getElementById(id)?.innerText);
          }
      });

      if (input.id) {
          addText(document.querySelector(`label[for="${input.id}"]`)?.innerText);
      }

      let current = input;
      for (let depth = 0; depth < 6 && current; depth++) {
          addText(current.previousElementSibling?.innerText);
          addText(current.parentElement?.previousElementSibling?.innerText);
          current = current.parentElement;
      }

      return Array.from(texts);
  }

  function findInputByContext(inputs, labelPatterns) {
      const normalizedPatterns = labelPatterns.map(normalizeText).filter(Boolean);
      if (normalizedPatterns.length === 0) return null;

      return inputs.find(input => {
          const contextTexts = getInputContextTexts(input);
          return normalizedPatterns.some(pattern => contextTexts.some(text => text.includes(pattern)));
      }) || null;
  }

  async function clickRightEdge(el) {
      const clickTarget = el.closest?.('.react-select__control, [class*="MuiAutocomplete-root"], [class*="MuiInputBase-root"], [role="combobox"]') || el;
      if (typeof el.focus === 'function') el.focus();
      const rect = clickTarget.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      const x = Math.max(rect.left + 4, rect.right - Math.min(15, rect.width / 2));
      const y = rect.top + (rect.height / 2);

      const mouseEventOptions = {
          view: window,
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y
      };

      const pointTarget = document.elementFromPoint(x, y);
      const finalTarget = pointTarget && clickTarget.contains(pointTarget) ? pointTarget : clickTarget;

      finalTarget.dispatchEvent(new MouseEvent('mousedown', mouseEventOptions));
      finalTarget.dispatchEvent(new MouseEvent('mouseup', mouseEventOptions));
      finalTarget.dispatchEvent(new MouseEvent('click', mouseEventOptions));
      if (typeof finalTarget.click === 'function') finalTarget.click();

      if (el !== finalTarget && typeof el.focus === 'function') {
          el.focus();
      }
  }

  // ============================================
  // OPTIMIZED DROPDOWN FILLING
  // ============================================

  async function fillCombobox(el, value, isStrict = false, isMulti = false) {
      if (!value || !el) return { ok: false, method: 'skipped' };

      el.scrollIntoView({ block: 'center', behavior: 'instant' });
      await sleep(CONFIG.SLEEP_MEDIUM);

      if (el instanceof HTMLSelectElement) {
          const targetOption = Array.from(el.options).find((opt) =>
              optionMatchesValue(opt.textContent, value, true) ||
              (!isStrict && optionMatchesValue(opt.textContent, value, false))
          );
          if (targetOption) {
              el.value = targetOption.value;
              el.dispatchEvent(new Event('change', { bubbles: true }));
              await sleep(CONFIG.SLEEP_SHORT);
              return { ok: true, method: 'option_click' };
          }
          return { ok: false, method: 'no_option' };
      }

      const dropdownLike = isDropdownLike(el);
      await clickRightEdge(el);
      await sleep(CONFIG.SLEEP_LONG);

      const resolveOpenOption = () => findMatchingOption(value, isStrict) || findHighlightedOption(value, isStrict);
      let targetOption = resolveOpenOption();
      const supportsSearch = el instanceof HTMLInputElement ||
          el.getAttribute('role') === 'combobox' ||
          el.classList.contains('react-select__input');
      const maxAttempts = Math.max(CONFIG.MAX_RETRIES, 3);

      for (let attempt = 1; !targetOption && attempt <= maxAttempts; attempt++) {
          if (supportsSearch) {
              el.focus();
              await clearInput(el);
              setReactValue(el, value);
              dispatchKey(el, 'ArrowDown');
              await sleep(CONFIG.SLEEP_LONG);
              targetOption = resolveOpenOption();
          }

          if (!targetOption && listOpenDropdownOptions().length === 0) {
              await clickRightEdge(el);
              await sleep(CONFIG.SLEEP_LONG);
              targetOption = resolveOpenOption();
          } else if (!targetOption) {
              await sleep(CONFIG.SLEEP_RETRY);
              targetOption = resolveOpenOption();
          }
      }

      if (targetOption) {
          await clickDropdownOption(targetOption);
          if (isMulti && el.value) await clearInput(el);
          return { ok: true, method: 'option_click' };
      }

      const openOptions = listOpenDropdownOptions();
      if (dropdownLike && openOptions.length > 0 && !isMulti) {
          await closeOpenMenus();
          if (el.value) await clearInput(el);
          return { ok: false, method: 'no_option' };
      }
      if (openOptions.length > 0) await closeOpenMenus();

      if (!dropdownLike) {
          if (isMulti) {
              await commitChipValue(el, value);
              return { ok: true, method: 'typed_fallback' };
          }
          await clearInput(el);
          setReactValue(el, value);
          await sleep(CONFIG.SLEEP_SHORT);
          return { ok: true, method: 'option_click' };
      }

      if (isMulti) {
          await commitChipValue(el, value);
          return { ok: true, method: 'typed_fallback' };
      }

      await closeOpenMenus();
      if (el.value) await clearInput(el);
      return { ok: false, method: 'no_option' };
  }

  // ============================================
  // FIELD FILLING FUNCTIONS
  // ============================================

  async function fillTextField(selector, value, fieldName) {
      const selectorText = typeof selector === 'string' ? selector : selectorFor(selector, '');
      if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) {
          recordFill({ field: fieldName, status: 'skipped', reason: 'No value in listing', selector: selectorText, value });
          return { status: 'skipped' };
      }
      
      const el = resolveWithRegistry(selector, fieldName);
      if (!el) {
          warn(`${fieldName}: Element not found`);
          recordFill({ field: fieldName, status: 'not_found', reason: 'Element not found', selector: selectorText, value });
          return { status: 'not_found' };
      }
      
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
      await clearInput(el);
      setReactValue(el, value);
      await sleep(CONFIG.SLEEP_SHORT);
      log(`  ✓ ${fieldName}: "${value}"`);
      recordFill({ field: fieldName, status: 'filled', selector: selectorFor(el, selectorText), value });
      return { status: 'filled' };
  }

  async function fillDropdownField(selectorOrEl, value, fieldName, isStrict = false, isMulti = false) {
      const selectorText = typeof selectorOrEl === 'string' ? selectorOrEl : selectorFor(selectorOrEl, '');
      value = mapPatchValue(currentFillMarketplace, fieldName, value);
      if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) {
          recordFill({ field: fieldName, status: 'skipped', reason: 'No value in listing', selector: selectorText, value });
          return { status: 'skipped' };
      }

      await closeOpenMenus();
      
      let el;
      if (typeof selectorOrEl === 'string') {
          el = resolveWithRegistry(selectorOrEl, fieldName);
      } else if (selectorOrEl instanceof Element) {
          el = selectorOrEl;
      } else {
          el = null;
      }
      if (!el) {
          warn(`${fieldName}: Element not found`);
          recordFill({ field: fieldName, status: 'not_found', reason: 'Element not found', selector: selectorText, value });
          return { status: 'not_found' };
      }

      const chipField = isMulti || isMultiChipField(fieldName);
      const values = chipField ? splitChipValues(value) : [value];
      if (chipField && values.length === 0) {
          recordFill({ field: fieldName, status: 'skipped', reason: 'No value in listing', selector: selectorText, value });
          return { status: 'skipped' };
      }

      if (chipField) {
          log(`Filling ${fieldName}...`);
          if (values.length > 1) await clearChipContainer(el);
          let filledCount = 0;
          let lastMethod = '';
          for (const item of values) {
              if (fieldHasChip(el, item) || optionMatchesValue(displayedFieldValue(el), item, true)) {
                  filledCount += 1;
                  continue;
              }
              const result = await fillCombobox(el, item, true, true);
              lastMethod = result && result.method;
              if ((result && result.ok) || fieldHasChip(el, item)) filledCount += 1;
              await sleep(CONFIG.SLEEP_MEDIUM);
          }
          const filledValue = values.length > 1 ? values : values[0];
          if (filledCount > 0) {
              recordFill({ field: fieldName, status: 'filled', selector: selectorFor(el, selectorText), value: filledValue });
              return { status: 'filled' };
          }
          if (lastMethod === 'typed_fallback' || fieldLooksFilled(el)) {
              recordFill({
                field: fieldName,
                status: 'uncertain',
                reason: 'Typed fallback; dropdown option was not clicked',
                selector: selectorFor(el, selectorText),
                value: filledValue,
              });
              return { status: 'uncertain' };
          }
          recordFill({
            field: fieldName,
            status: 'failed',
            reason: 'Option not found and value did not stick',
            selector: selectorFor(el, selectorText),
            value: filledValue,
          });
          return { status: 'failed' };
      }

      if (optionMatchesValue(displayedFieldValue(el), value, false)) {
          log(`  ✓ ${fieldName} already set: "${displayedFieldValue(el)}"`);
          recordFill({
            field: fieldName,
            status: 'filled',
            reason: 'Already set',
            selector: selectorFor(el, selectorText),
            value,
          });
          return { status: 'filled' };
      }
      
      log(`Filling ${fieldName}...`);
      const result = await fillCombobox(el, value, isStrict, isMulti);
      const method = result && result.method;
      if (method === 'option_click') {
          recordFill({ field: fieldName, status: 'filled', selector: selectorFor(el, selectorText), value });
          return { status: 'filled' };
      }
      if (fieldLooksFilled(el)) {
          recordFill({
            field: fieldName,
            status: 'uncertain',
            reason: 'Typed fallback; dropdown option was not clicked',
            selector: selectorFor(el, selectorText),
            value,
          });
          return { status: 'uncertain' };
      }
      recordFill({
        field: fieldName,
        status: 'failed',
        reason: 'Option not found and value did not stick',
        selector: selectorFor(el, selectorText),
        value,
      });
      return { status: 'failed' };
  }

  // Try registry selectors before falling back to hardcoded selector
  function resolveWithRegistry(selector, fieldName) {
    if (!currentRegistrySelectors || !fieldName) {
      return document.querySelector(selector);
    }
    for (const mp of Object.keys(currentRegistrySelectors)) {
      const field = currentRegistrySelectors[mp][fieldName.toLowerCase()];
      if (field && field.selectors) {
        for (const regSel of field.selectors) {
          try {
            const el = document.querySelector(regSel);
            if (el) {
              log(`  [registry] ${fieldName}: using ${mp}/${fieldName} → ${regSel}`);
              return el;
            }
          } catch (_) {}
        }
      }
    }
    return document.querySelector(selector);
  }

  // Global registry selectors store set by FILL_GENERAL/FILL_MARKETPLACE
  let currentRegistrySelectors = {};

  function getRegistryField(marketplace, fieldName) {
    const mp = currentRegistrySelectors[marketplace] || {};
    return mp[fieldName] || null;
  }

  // ============================================
  // PARALLEL BATCH FILLING
  // ============================================

  async function batchFillFields(fields) {
      // Fill all fields in parallel where they don't depend on each other
      const promises = fields.map(({fn, args}) => fn(...args));
      await Promise.all(promises);
  }

  // ============================================
  // CATEGORY SELECTION
  // ============================================

  function listCategoryOptions() {
      const seen = new Set();
      const options = [];
      for (const el of document.querySelectorAll(CATEGORY_RESULT_SELECTORS)) {
          if (seen.has(el) || !isVisibleElement(el)) continue;
          const text = optionMatchText(el);
          if (!text) continue;
          seen.add(el);
          options.push({ el, text, lower: normalizeText(text) });
      }
      return options;
  }

  function scoreCategoryOption(option, segment) {
      const needle = normalizeText(segment);
      if (!needle || !option.lower) return 0;
      if (option.lower === needle) return 4;
      if (option.lower.startsWith(needle) || needle.startsWith(option.lower)) return 3;
      if (option.lower.includes(needle) || needle.includes(option.lower)) return 1;
      return 0;
  }

  function findCategoryOption(segment, options = listCategoryOptions(), minScore = 1) {
      let best = null;
      let bestScore = 0;
      for (const option of options) {
          const score = scoreCategoryOption(option, segment);
          if (score > bestScore) {
              best = option;
              bestScore = score;
          }
      }
      return bestScore >= minScore ? best : null;
  }

  const VENDOO_WOMEN_TOPS = "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops";
  const VENDOO_MEN_TSHIRTS = "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts";
  const CATEGORY_SEGMENT_ALIASES = {
      clothing: ['Clothing, Shoes & Accessories', 'Clothing'],
      women: ["Women's Clothing", 'Women'],
      men: ["Men's Clothing", 'Men'],
      "shirts & blouses": ['Tops', 'Shirts'],
      't-shirts': ['T-Shirts', 'Tops', 'Tees - Short Sleeve', 'Tees - Long Sleeve'],
      't shirts': ['T-Shirts', 'Tops', 'Tees - Short Sleeve', 'Tees - Long Sleeve'],
      shirts: ['Shirts', 'Tops'],
      tees: ['Tees - Short Sleeve', 'Tees - Long Sleeve'],
      'tees - short sleeve': ['Tees - Short Sleeve'],
      'tees - long sleeve': ['Tees - Long Sleeve'],
  };

  function categoryHaystack(data, categoryPath) {
      const department = data.department || data.ebay_specifics?.department || '';
      const type = data.ebay_specifics?.type || data.type || '';
      const sleeve = data.sleeveLength || data.ebay_specifics?.sleeveLength || '';
      return `${categoryPath} ${department} ${type} ${sleeve} ${data.title || ''}`;
  }

  function explicitPoshmarkCategoryPath(data) {
      const specs = data?.poshmark_specifics;
      if (!specs || typeof specs !== 'object') return '';
      const explicit = specs.category_path || specs.categoryPath;
      if (Array.isArray(explicit)) {
          return explicit.map((part) => String(part || '').trim()).filter(Boolean).join(' > ');
      }
      return String(explicit || '').trim();
  }

  function normalizePoshmarkCategoryPath(data) {
      const explicit = explicitPoshmarkCategoryPath(data);
      const categoryPath = String(data?.category_path || '').trim();
      const hay = categoryHaystack(data, categoryPath);
      const hayLower = normalizeText(hay);
      const isWomen = /\bwomen/.test(hayLower);
      const isMen = /\bmen/.test(hayLower) && !/\bwomen/.test(hayLower);
      if (explicit) {
          const explicitLower = normalizeText(explicit);
          const staleWomen = isMen && /\bwomen/.test(explicitLower);
          const staleMen = isWomen && /\bmen/.test(explicitLower) && !/\bwomen/.test(explicitLower);
          if (!staleWomen && !staleMen) return explicit;
      }
      if (/^(men|women|kids|pets|home|electronics)\s*>/i.test(categoryPath)) return categoryPath;
      const isTee = /t-?shirts?|\btees?\b|graphic tee/.test(hayLower);
      const isBlouse = /\bblouses?\b/.test(hayLower) && !isTee;
      const longSleeve = /long\s*sleeve/.test(hayLower);
      const teeLeaf = longSleeve ? 'Tees - Long Sleeve' : 'Tees - Short Sleeve';
      if (isMen && isTee) return `Men > Shirts > ${teeLeaf}`;
      if (isWomen && isTee) return `Women > Tops > ${teeLeaf}`;
      if (isWomen && isBlouse) return 'Women > Tops > Blouses';
      return categoryPath;
  }

  function normalizeVendooCategoryPath(data) {
      const categoryPath = data.category_path || '';
      const hay = categoryHaystack(data, categoryPath);
      const hayLower = normalizeText(hay);
      const pathLower = normalizeText(categoryPath);
      const isWomen = /\bwomen/.test(hayLower);
      const isMen = /\bmen/.test(hayLower) && !/\bwomen/.test(hayLower);
      const isTop = /t-?shirts?|\btees?\b|\btops?\b|\bshirts?\b|\bblouses?\b/.test(hayLower);
      const pathIsOtherItem = /dresses?|pants?|jeans?|skirts?|shorts?|jackets?|coats?|sweaters?|hoodies?/.test(pathLower)
          && !/t-?shirts?|\btees?\b|\btops?\b|\bshirts?\b|\bblouses?\b/.test(pathLower);
      if (pathIsOtherItem) return categoryPath;
      if (isWomen && isTop) return VENDOO_WOMEN_TOPS;
      if (isMen && /t-?shirts?|\btees?\b/.test(hayLower)) return VENDOO_MEN_TSHIRTS;
      return categoryPath;
  }

  function categorySegmentNames(segment) {
      const key = normalizeText(segment);
      return CATEGORY_SEGMENT_ALIASES[key] || [segment];
  }

  function findStrongCategoryOption(segment, options = listCategoryOptions()) {
      for (const name of categorySegmentNames(segment)) {
          const match = findCategoryOption(name, options, 3);
          if (match) return match;
      }
      return null;
  }

  function rankCategorySearchResults(options, segments) {
      const needles = segments.map((segment) => normalizeText(segment)).filter(Boolean);
      const leaf = needles[needles.length - 1] || '';
      return options
          .map((option) => {
              let score = scoreCategoryOption(option, leaf);
              for (const needle of needles.slice(0, -1)) {
                  if (option.lower.includes(needle) || needle.includes(option.lower)) {
                      score += 2;
                  }
              }
              return { ...option, score };
          })
          .filter((option) => option.score > 0)
          .sort((a, b) => b.score - a.score);
  }

  async function clickCategoryOption(option) {
      log(`  Clicking: "${option.text}"`);
      option.el.scrollIntoView({ block: 'center', behavior: 'instant' });
      await sleep(CONFIG.SLEEP_SHORT);
      const mouseEventOptions = { bubbles: true, cancelable: true, view: window };
      option.el.dispatchEvent(new MouseEvent('mousedown', mouseEventOptions));
      option.el.dispatchEvent(new MouseEvent('mouseup', mouseEventOptions));
      option.el.click();
      await sleep(CONFIG.SLEEP_LONG * 2);
  }

  async function waitForCategorySearch() {
      for (let attempt = 0; attempt < 8; attempt++) {
          const el = document.querySelector('input[role="category-search-field"]');
          if (el) return el;
          await sleep(CONFIG.SLEEP_LONG);
      }
      return document.querySelector('input[role="category-search-field"]');
  }

  function findCategoryClearControl(catBtn) {
      const root = catBtn.closest('.MuiAutocomplete-root, .MuiFormControl-root, .MuiInputBase-root, [class*="category"]')
          || catBtn.parentElement;
      if (!root) return null;
      const selectors = [
          '.MuiAutocomplete-clearIndicator',
          'button[aria-label="Clear"]',
          'button[aria-label*="clear" i]',
          '.MuiChip-deleteIcon',
          '[data-testid*="clear" i]',
      ];
      for (const sel of selectors) {
          const el = root.querySelector(sel);
          if (el && isVisibleElement(el)) return el.closest('button') || el;
      }
      return Array.from(root.querySelectorAll('button, [role="button"]')).find((el) => {
          if (!isVisibleElement(el)) return false;
          const label = normalizeText(el.getAttribute('aria-label') || el.getAttribute('title') || '');
          return label.includes('clear') || label.includes('remove') || label.includes('delete');
      }) || null;
  }

  async function clearExistingCategorySelection(catBtn) {
      const shown = (displayedFieldValue(catBtn) || catBtn.innerText || catBtn.textContent || '')
          .trim().split('\n')[0].trim();
      if (!shown || /click to select|select category/i.test(shown)) return;
      log(`Clearing existing category: "${shown}"`);
      await closeOpenMenus();
      const clearBtn = findCategoryClearControl(catBtn);
      if (!clearBtn) return;
      clearBtn.click();
      await sleep(CONFIG.SLEEP_MEDIUM);
  }

  async function resetCategoryPickerToRoot() {
      const search = document.querySelector('input[role="category-search-field"]');
      if (!search) return;
      const root = search.closest('[role="dialog"], [class*="Popover"], [class*="Modal"], [class*="paper"]') || search.parentElement;
      const clickVisible = (predicate) => {
          const match = Array.from((root || document).querySelectorAll('button, a, span, div, p, [role="button"]')).find((el) => {
              if (!isVisibleElement(el)) return false;
              return predicate(el);
          });
          if (!match) return false;
          match.click();
          return true;
      };
      if (clickVisible((el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() === 'All')) {
          log('Resetting category picker to All');
          await sleep(CONFIG.SLEEP_LONG);
      }
      for (let i = 0; i < 8; i++) {
          const wentBack = clickVisible((el) => {
              const label = normalizeText(el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || '');
              return label === 'back' || label === 'go back' || label === 'previous';
          });
          if (!wentBack) break;
          log('Category picker: going back');
          await sleep(CONFIG.SLEEP_LONG);
      }
  }

  function categoryDisplayMatches(shown, path) {
      const shownNorm = normalizeText(String(shown || '').replace(/[▸▶]/g, ' '));
      const segs = String(path || '').split('>').map((part) => normalizeText(part)).filter(Boolean);
      return segs.length > 0 && segs.every((seg) => shownNorm.includes(seg));
  }

  function findMarketplaceCategoryControl(marketplace) {
      const labeled = findInputByExactLabel('Category', isMarketplaceInput(marketplace));
      if (labeled) return labeled;
      return resolveMarketplaceField(marketplace, ['category'], [
          `#listings\\.${marketplace}\\.overrides\\.category`,
          `#listings\\.${marketplace}\\.overrides\\.categoryV2`,
          `#listings\\.${marketplace}\\.category`,
      ]);
  }

  async function fillCategoryPath(data, options = {}) {
      const originalPath = data.category_path || '';
      const categoryPath = options.categoryPath || normalizeVendooCategoryPath(data);
      if (!categoryPath) return { ok: true, filled: false };
      if (categoryPath !== originalPath) {
          log(`Mapped category "${originalPath}" → "${categoryPath}"`);
      }

      log(`Setting category: ${categoryPath}`);

      const segments = categoryPath.split('>').map(s => s.trim()).filter(Boolean);
      if (segments.length === 0) return { ok: true, filled: false };

      const catBtn = options.catBtn || document.querySelector('#categoryV2, [role="category-input"]');
      if (!catBtn) {
          warn('Category button #categoryV2 not found');
          return { ok: false, filled: false, error: 'Category button not found' };
      }

      const alreadyShown = displayedFieldValue(catBtn) || catBtn.innerText || catBtn.textContent || '';
      if (categoryDisplayMatches(alreadyShown, categoryPath)) {
          log(`Category already set: "${alreadyShown}"`);
          return { ok: true, filled: true, result: alreadyShown };
      }

      await clearExistingCategorySelection(catBtn);
      await closeOpenMenus();
      catBtn.scrollIntoView({ block: 'center', behavior: 'instant' });
      await sleep(CONFIG.SLEEP_MEDIUM);
      log('Opening category selector...');
      catBtn.click();
      await sleep(CONFIG.SLEEP_LONG * 2);

      let searchInput = await waitForCategorySearch();
      await resetCategoryPickerToRoot();
      searchInput = document.querySelector('input[role="category-search-field"]') || searchInput;
      if (searchInput) {
          const query = segments.slice(-2).join(' ');
          log(`Searching categories for: "${query}"`);
          searchInput.focus();
          await clearInput(searchInput);
          setReactValue(searchInput, query);
          searchInput.dispatchEvent(new Event('input', { bubbles: true }));
          searchInput.dispatchEvent(new KeyboardEvent('input', { bubbles: true }));
          searchInput.dispatchEvent(new Event('change', { bubbles: true }));
          await sleep(CONFIG.SLEEP_LONG * 2);

          const ranked = rankCategorySearchResults(listCategoryOptions(), segments);
          if (ranked.length > 0) {
              await clickCategoryOption(ranked[0]);
          } else {
              const visible = listCategoryOptions().map((option) => option.text).slice(0, 20);
              warn(`Category search had no match for "${query}". Visible: ${JSON.stringify(visible)}`);
          }
      }

      const searchStillOpen = () => {
          const el = document.querySelector('input[role="category-search-field"]');
          return Boolean(el && document.contains(el));
      };

      if (searchStillOpen()) {
          for (let i = 0; i < segments.length; i++) {
              const segment = segments[i];
              const isLeaf = i === segments.length - 1;
              log(`  Drilling into: "${segment}" (${i + 1}/${segments.length})`);

              let targetOption = null;
              for (let attempt = 0; attempt < 8 && !targetOption; attempt++) {
                  await sleep(CONFIG.SLEEP_LONG);
                  targetOption = findStrongCategoryOption(segment);
              }

              if (!targetOption) {
                  const visible = listCategoryOptions().map((option) => option.text).slice(0, 20);
                  const laterVisible = !isLeaf && segments.slice(i + 1).some((later) => (
                      findStrongCategoryOption(later, listCategoryOptions())
                  ));
                  if (laterVisible) {
                      warn(`Category option "${segment}" not found, skipping; a later segment is visible. Visible: ${JSON.stringify(visible)}`);
                      continue;
                  }
                  warn(`Category option "${segment}" not found. Visible: ${JSON.stringify(visible)}`);
                  return { ok: false, filled: false, error: `Category option "${segment}" not found` };
              }

              await clickCategoryOption(targetOption);
          }
      }

      await sleep(CONFIG.SLEEP_LONG * 2);

      const terminalSearch = document.querySelector('input[role="category-search-field"]');
      if (terminalSearch && document.contains(terminalSearch)) {
          log('Category modal still open, searching for terminal child...');

          const children = listCategoryOptions();
          const childLabels = children.map((option) => option.text);
          log(`  Visible children: ${JSON.stringify(childLabels)}`);

          if (children.length > 0) {
              const type = data.ebay_specifics?.type || data.type || '';
              const typeLower = type.toLowerCase().trim();

              const TYPE_MAP = {
                  't-shirt': 't-shirts',
                  'tee': 't-shirts',
                  'polo': 'polos',
                  'dress shirt': 'dress shirts',
                  'button-down': 'casual button-down shirts',
                  'button down': 'casual button-down shirts',
                  'henley': 'henleys',
                  'tank': 'tank tops',
                  'tank top': 'tank tops',
                  'sweatshirt': 'sweatshirts',
                  'hoodie': 'hoodies',
                  'long sleeve': 'long sleeve t-shirts',
              };

              let targetType = '';
              for (const [key, val] of Object.entries(TYPE_MAP)) {
                  if (typeLower.includes(key)) {
                      targetType = val;
                      break;
                  }
              }

              const rankedChildren = rankCategorySearchResults(children, [
                  ...segments,
                  targetType || type,
              ].filter(Boolean));
              const childOption = rankedChildren[0] || null;

              if (childOption) {
                  await clickCategoryOption(childOption);
              } else {
                  warn(`No terminal child match. Children: ${JSON.stringify(childLabels)}`);
              }
          }
      }

      await sleep(CONFIG.SLEEP_LONG);

      const searchInputAfter = document.querySelector('input[role="category-search-field"]');
      if (searchInputAfter && document.contains(searchInputAfter)) {
          warn('Category modal still open after selecting all segments');
          return { ok: false, filled: false, error: 'Category modal did not close after selection' };
      }

      const catBtnText = (displayedFieldValue(catBtn) || catBtn.innerText || catBtn.textContent || '')
          .trim().split('\n')[0].trim();
      log(`Category selected. Button text: "${catBtnText}"`);

      if (!catBtnText || catBtnText.toLowerCase().includes('click to select')) {
          return { ok: false, filled: false, error: 'Category button not updated after selection' };
      }
      if (!categoryDisplayMatches(catBtnText, categoryPath)) {
          return { ok: false, filled: false, error: `Category stayed "${catBtnText}" instead of "${categoryPath}"` };
      }

      return { ok: true, filled: true, result: catBtnText };
  }

  async function fillMarketplaceCategory(marketplace, data) {
      const categoryPath = marketplace === 'poshmark'
          ? normalizePoshmarkCategoryPath(data)
          : String(data?.category_path || '').trim();
      if (!categoryPath) {
          recordFill({ field: 'Category', status: 'skipped', reason: 'No value in listing' });
          return { status: 'skipped' };
      }
      const catBtn = findMarketplaceCategoryControl(marketplace);
      if (!catBtn) {
          warn(`${marketplace} category field not found`);
          recordFill({
            field: 'Category',
            status: 'not_found',
            reason: 'Category field not found',
            value: categoryPath,
          });
          return { status: 'not_found' };
      }
      const result = await fillCategoryPath(data, { catBtn, categoryPath });
      recordFill({
        field: 'Category',
        status: result.ok ? (result.filled ? 'filled' : 'skipped') : 'failed',
        reason: result.error || '',
        selector: selectorFor(catBtn, ''),
        value: categoryPath,
      });
      return { status: result.ok ? (result.filled ? 'filled' : 'skipped') : 'failed' };
  }

  // ============================================
  // MAIN VENDOO FORM FILLER - OPTIMIZED
  // ============================================

  async function fillMainForm(data) {
      beginFillLog('general');
      log('=== Filling Main Vendoo Form ===');

      try {
      // Category must be set FIRST (before size, which depends on it)
      if (data.category_path) {
          const catResult = await fillCategoryPath(data);
          if (!catResult.ok) {
              recordFill({
                field: 'Category',
                status: 'failed',
                reason: catResult.error || 'Category selection failed',
                selector: VENDOO_SELECTORS.category,
                value: data.category_path,
              });
              return { ok: false, error: catResult.error || 'Category selection failed', fill_log: finishFillLog() };
          }
          recordFill({
            field: 'Category',
            status: catResult.filled ? 'filled' : 'skipped',
            selector: VENDOO_SELECTORS.category,
            value: data.category_path,
          });
          await sleep(CONFIG.SLEEP_LONG);
      } else {
          recordFill({ field: 'Category', status: 'skipped', reason: 'No value in listing', selector: VENDOO_SELECTORS.category });
      }
      
      // Text fields (parallel)
      const textFields = [
          {fn: fillTextField, args: [VENDOO_SELECTORS.title, data.title, 'Title']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.description, data.description, 'Description']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.zipCode, data.zipCode || '70125', 'Zip Code']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.sku, data.sku, 'SKU']},
      ];
      await batchFillFields(textFields);
      
      await fillDropdownField(
          VENDOO_SELECTORS.condition,
          data.condition ? mapCondition(data.condition, 'vendoo') : data.condition,
          'Condition',
          true
      );
      
      // Dropdown fields (sequential for stability)
      await fillDropdownField(VENDOO_SELECTORS.brand, data.brand, 'Brand');
      await fillDropdownField(VENDOO_SELECTORS.primaryColor, mapColor(data.primaryColor || data.color, 'vendoo'), 'Primary Color');
      await fillDropdownField(VENDOO_SELECTORS.secondaryColor, mapColor(data.secondaryColor, 'vendoo'), 'Secondary Color');
      const sizeTypeValue = data.sizeType || data.ebay_specifics?.sizeType;
      const sizeTypeEl = document.querySelector(VENDOO_SELECTORS.sizeType) ||
          findInputByLabelPatterns(['size type'], (input) => String(input.id || '').startsWith('generalDetails'));
      if (sizeTypeEl && sizeTypeValue) {
          await fillDropdownField(sizeTypeEl, sizeTypeValue, 'Size Type');
      }
      if (data.size) {
          const sizeEl = document.querySelector(VENDOO_SELECTORS.size);
          if (sizeEl) {
              await fillDropdownField(sizeEl, data.size, 'Size', true);
          } else {
              warn('Size input not found after category');
              recordFill({
                field: 'Size',
                status: 'not_found',
                reason: 'Size input not found after category',
                selector: VENDOO_SELECTORS.size,
                value: data.size,
              });
          }
      } else {
          recordFill({ field: 'Size', status: 'skipped', reason: 'No value in listing', selector: VENDOO_SELECTORS.size });
      }
      
      // Multi-value fields
      if (data.tags) {
          const tagsEl = document.querySelector(VENDOO_SELECTORS.tags);
          if (tagsEl) {
              const tags = Array.isArray(data.tags) ? data.tags : data.tags.split(',').map(t => t.trim());
              for (const tag of tags) await fillCombobox(tagsEl, tag, false, true);
              recordFill({ field: 'Tags', status: 'filled', selector: VENDOO_SELECTORS.tags, value: tags });
          } else {
              recordFill({ field: 'Tags', status: 'not_found', reason: 'Tags input not found', selector: VENDOO_SELECTORS.tags, value: data.tags });
          }
      } else {
          recordFill({ field: 'Tags', status: 'skipped', reason: 'No value in listing', selector: VENDOO_SELECTORS.tags });
      }
      
      if (data.labels) {
          const labelsEl = document.querySelector(VENDOO_SELECTORS.labels);
          if (labelsEl) {
              const labels = Array.isArray(data.labels) ? data.labels : data.labels.split(',').map(l => l.trim());
              for (const label of labels) await fillCombobox(labelsEl, label, false, true);
              recordFill({ field: 'Labels', status: 'filled', selector: VENDOO_SELECTORS.labels, value: labels });
          } else {
              recordFill({ field: 'Labels', status: 'not_found', reason: 'Labels input not found', selector: VENDOO_SELECTORS.labels, value: data.labels });
          }
      } else {
          recordFill({ field: 'Labels', status: 'skipped', reason: 'No value in listing', selector: VENDOO_SELECTORS.labels });
      }
      
      // Numeric fields (parallel)
      const numericFields = [
          {fn: fillTextField, args: [VENDOO_SELECTORS.quantity, data.quantity, 'Quantity']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.price, data.price, 'Price']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.cost, data.cost, 'Cost of Goods']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.weightLb, data.weight_lb, 'Weight (lbs)']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.weightOz, data.weight_oz, 'Weight (oz)']},
      ];
      await batchFillFields(numericFields);
      
      // Package dimensions
      const packageDims = data.package_dimensions_in || '13x10x3';
      const dims = packageDims.split('x');
      if (dims.length === 3) {
          const dimFields = [
              {fn: fillTextField, args: [VENDOO_SELECTORS.length, dims[0].trim(), 'Length']},
              {fn: fillTextField, args: [VENDOO_SELECTORS.width, dims[1].trim(), 'Width']},
              {fn: fillTextField, args: [VENDOO_SELECTORS.height, dims[2].trim(), 'Height']},
          ];
          await batchFillFields(dimFields);
      }
      
      await fillTextField(VENDOO_SELECTORS.notes, data.internal_notes, 'Notes');
      log('=== Main form filled ===');
      return { ok: true, fill_log: finishFillLog() };
      } catch (err) {
          recordFill({ field: 'form', status: 'failed', reason: err.message });
          error(`Fill Error: ${err.message}`);
          return { ok: false, error: err.message, fill_log: finishFillLog() };
      }
  }

  // ============================================
  // CLICK SAVE BUTTON - OPTIMIZED
  // ============================================

  async function clickSave() {
      log('Looking for Save button...');
      
      const saveBtn = document.querySelector('[data-testid="save-item-button"]');
      if (saveBtn) {
          saveBtn.scrollIntoView({ block: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_MEDIUM);
          saveBtn.click();
          return true;
      }

      const PROHIBITED_TERMS = ['list', 'publish', 'activate', 'sell'];
      const buttons = Array.from(document.querySelectorAll('button, div[role="button"]'));
      
      let target = null;
      for (const b of buttons) {
          const t = (b.innerText || '').trim().toLowerCase();
          if (!t || t.length > 20) continue;
          if (!t.includes('save')) continue;
          if (PROHIBITED_TERMS.some(pt => t.includes(pt))) {
              warn(`Skipping prohibited button: "${b.innerText}"`);
              continue;
          }
          target = b;
          break;
      }
      
      if (target) {
          log(`Clicking save button: "${target.innerText.trim()}"`);
          target.scrollIntoView({ block: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_MEDIUM);
          target.click();
          return true;
      }
      
      warn('Save button not found');
      return false;
  }

  // ============================================
  // EXPAND OPTIONAL FIELDS - OPTIMIZED
  // ============================================

  async function expandOptionalFields() {
      const texts = ['Show Optional Fields', 'Optional Fields', 'Show more', 'More options', 'Advanced'];
      const buttons = Array.from(document.querySelectorAll('button, span[role="button"], a, div[role="button"]'));
      
      for (const btn of buttons) {
          if (!btn.innerText) continue;
          const btnText = btn.innerText.toLowerCase();
          if (texts.some(t => btnText.includes(t.toLowerCase()))) {
              log(`Expanding optional fields: "${btn.innerText}"`);
              btn.scrollIntoView({ block: 'center', behavior: 'instant' });
              await sleep(CONFIG.SLEEP_SHORT);
              btn.click();
              await sleep(CONFIG.SLEEP_LONG); // Reduced from 2000ms
              return true;
          }
      }
      return false;
  }

  // ============================================
  // PLATFORM-SPECIFIC FILLERS - OPTIMIZED
  // ============================================

  function normalizeEbaySpecificValue(key, value) {
      if (value == null || value === '') return value;
      const raw = Array.isArray(value) ? value.join(', ') : String(value).trim();
      if (key === 'yearManufactured') {
          const yearMatch = raw.match(/(?:19|20)\d{2}/);
          if (!yearMatch) return raw;
          const decade = Math.floor(Number(yearMatch[0]) / 10) * 10;
          if (decade >= 2020) return '2020-2029';
          if (decade >= 2010) return '2010-2019';
          if (decade >= 2000) return '2000-2009';
          if (decade >= 1990) return '1990-1999';
          if (decade >= 1980) return '1980-1989';
          if (decade >= 1970) return '1970-1979';
          if (decade >= 1960) return '1960-1969';
          if (decade >= 1950) return '1950-1959';
          if (decade >= 1940) return '1940-1949';
          if (decade >= 1930) return '1930-1939';
          if (decade >= 1920) return '1920-1929';
          if (decade >= 1910) return '1910-1919';
          if (decade >= 1900) return '1900-1909';
          return 'Pre-1900s';
      }
      if (key === 'type' && /t[\s-]?shirt/i.test(raw)) return 'T-Shirt';
      if (key === 'season') {
          const allowed = ['Fall', 'Spring', 'Summer', 'Winter'];
          return allowed.find((item) => item.toLowerCase() === raw.toLowerCase()) || null;
      }
      if (key === 'countryOfOrigin' && /^unknown$/i.test(raw)) return null;
      return value;
  }

  async function fillEbayForm(data) {
      log('Filling eBay form...');

      await fillDropdownField(
          '#listings\\.ebay\\.overrides\\.condition',
          mapCondition(data.condition, 'ebay'),
          'eBay Condition',
          true
      );
      await fillDropdownField('#listings\\.ebay\\.overrides\\.brand', data.brand, 'eBay Brand');
      await fillDropdownField(
          '#listings\\.ebay\\.overrides\\.primaryColor',
          mapColor(data.primaryColor || data.color, 'ebay'),
          'eBay Color'
      );

      await Promise.all([
          fillTextField('#listings\\.ebay\\.overrides\\.quantity', data.quantity, 'eBay Quantity'),
          fillTextField('#listings\\.ebay\\.overrides\\.sku', data.sku, 'eBay SKU'),
      ]);
      
      // Price
      const ebayPriceEl = document.querySelector('#listings\\.ebay\\.marketplaceSpecifics\\.pricingFormatDetails\\.fixedPrice\\.buyItNowPrice') || 
                          document.querySelector('#listings\\.ebay\\.overrides\\.price');
      if (ebayPriceEl) {
          await fillTextField(`#${ebayPriceEl.id.replace(/\./g, '\\.')}`, data.price, 'eBay Price');
      }
      
      // Category specifics
      if (data.ebay_specifics) {
          log('Expanding optional fields for eBay...');
          await expandOptionalFields();
          await sleep(CONFIG.SLEEP_LONG * 2); // 1 second for fields to load
          
          log('Filling eBay category specifics...');
          
          const fieldNameMap = {
              'type': 'Type', 'department': 'Department', 'size': 'Size',
              'sizeType': 'Size Type', 'style': 'Style', 'brand': 'Brand',
              'color': 'Color', 'material': 'Material', 'pattern': 'Pattern',
              'fit': 'Fit', 'sleeveLength': 'Sleeve Length', 'sleeveType': 'Sleeve Type',
              'neckline': 'Neckline', 'closure': 'Closure', 'accents': 'Accents',
              'features': 'Features', 'theme': 'Theme', 'season': 'Season',
              'occasion': 'Occasion', 'strapType': 'Strap Type',
              'countryOfOrigin': 'Country of Origin', 'fabricType': 'Fabric Type',
              'fabricWeight': 'Fabric Weight',
              'vintage': 'Vintage', 'handmade': 'Handmade', 'personalize': 'Personalize',
              'garmentCare': 'Garment Care', 'unitQuantity': 'Unit Quantity',
              'unitType': 'Unit Type', 'mpn': 'MPN', 'upc': 'UPC',
              'character': 'Character', 'characterFamily': 'Character Family',
              'performanceActivity': 'Performance Activity', 'yearManufactured': 'Year Manufactured',
              'collarStyle': 'Collar Style', 'rise': 'Rise', 'inseam': 'Inseam',
              'waist': 'Waist'
          };

          function ebaySpecificFieldToken(idOrName) {
              const afterDot = String(idOrName || '').split('.').pop() || '';
              return normalizeText(afterDot.replace(/^\d+_/, ''));
          }

          function collectEbayCategoryInputs(requireVisible = true) {
              const usable = requireVisible ? isVisibleElement : isAttachedElement;
              return Array.from(document.querySelectorAll(
                  'input[id^="listings.ebay.categorySpecifics."], select[id^="listings.ebay.categorySpecifics."], [id^="listings.ebay.categorySpecifics."][role="combobox"], input[name^="listings.ebay.categorySpecifics."], select[name^="listings.ebay.categorySpecifics."]'
              )).filter(usable);
          }

          function findEbaySpecificInput(fieldName, inputs) {
              const want = normalizeText(fieldName);
              for (const input of inputs) {
                  const token = ebaySpecificFieldToken(input.id) || ebaySpecificFieldToken(input.name);
                  if (token === want) return input;
              }
              return findInputByExactLabel(fieldName, isEbayCategorySpecificInput);
          }

          let allInputs = collectEbayCategoryInputs();
          if (allInputs.length === 0) {
              for (let attempt = 0; attempt < 6 && allInputs.length === 0; attempt++) {
                  await sleep(CONFIG.SLEEP_RETRY);
                  allInputs = collectEbayCategoryInputs();
              }
          }
          if (allInputs.length === 0) {
              allInputs = collectEbayCategoryInputs(false);
          }
          log(`Found ${allInputs.length} category specific fields`);

          const specs = { ...data.ebay_specifics };
          const seasonRaw = specs.season;
          if (/all seasons/i.test(String(seasonRaw || ''))) {
              const features = Array.isArray(specs.features) ? specs.features.slice() : String(specs.features || '').split(',').map((item) => item.trim()).filter(Boolean);
              if (!features.some((item) => /all seasons/i.test(item))) features.push('All Seasons');
              specs.features = features;
          }
          const fillOrder = [
              'sizeType', 'type', 'department', 'size',
              ...Object.keys(specs).filter(key => !['sizeType', 'type', 'department', 'size'].includes(key)),
          ];

          for (const key of fillOrder) {
              const mapped = normalizeEbaySpecificValue(key, specs[key]);
              const fieldName = fieldNameMap[key] || key;
              if (specs[key] && (mapped == null || mapped === '')) {
                  recordFill({
                    field: fieldName,
                    status: 'skipped',
                    reason: 'No matching eBay option',
                    value: specs[key],
                  });
                  continue;
              }
              if (!mapped) continue;
              if ((key === 'brand' || key === 'color') && fillLedger.some((entry) => normalizeFieldKey(entry.field) === key && entry.status === 'filled')) {
                  continue;
              }

              allInputs = collectEbayCategoryInputs();
              const foundEl = findEbaySpecificInput(fieldName, allInputs);

              if (!foundEl) {
                  warn(`Could not find field for ${key}`);
                  recordFill({
                    field: fieldName,
                    status: 'skipped',
                    reason: 'Not on this category form',
                    value: mapped,
                  });
                  continue;
              }

              let valuesToFill = isMultiChipField(fieldName)
                  ? splitChipValues(mapped)
                  : Array.isArray(mapped) ? mapped :
                  (typeof mapped === 'string' && mapped.includes(',') && !['yearManufactured', 'mpn', 'upc'].includes(key)) ?
                  mapped.split(',').map(v => v.trim()) : [mapped];

              if (key === 'color') {
                  valuesToFill = valuesToFill.map(item => mapColor(item, 'ebay')).filter(Boolean);
              }
              if (key === 'type') {
                  valuesToFill = uniqueStrings([
                      ...(/t[\s-]?shirt/i.test(String(mapped)) ? ['T-Shirt'] : []),
                      ...valuesToFill,
                  ]);
              }

              const isSizeField = key.toLowerCase() === 'size';
              log(`  Filling eBay ${fieldName}: ${valuesToFill.join(', ')}`);

              if (isMultiChipField(fieldName)) {
                  await fillDropdownField(foundEl, valuesToFill, fieldName, isSizeField, true);
              } else if (valuesToFill.length > 1 && key !== 'type') {
                  for (const item of valuesToFill) {
                      await fillDropdownField(foundEl, item, fieldName, isSizeField, true);
                      await sleep(CONFIG.SLEEP_MEDIUM);
                  }
              } else if (key === 'type') {
                  let filled = false;
                  for (const item of valuesToFill) {
                      const result = await fillDropdownField(foundEl, item, fieldName, false, false);
                      if (result && result.status === 'filled') {
                          filled = true;
                          break;
                      }
                  }
                  if (!filled) {
                      warn(`eBay Type could not be set from ${valuesToFill.join(', ')}`);
                  }
              } else {
                  await fillDropdownField(foundEl, valuesToFill[0], fieldName, isSizeField, false);
              }
          }
      }
  }

  async function fillEtsyForm(data) {
      log('Filling Etsy form...');

      const specs = data.etsy_specifics || {};
      const ebaySpecifics = data.ebay_specifics || {};
      const normalizedWhenMade = normalizeEtsyWhenMade(
          specs.when_made || specs.whenMade || ebaySpecifics.yearManufactured
      );

      await fillDropdownField(
          resolveMarketplaceField('etsy', ['primary color', 'color'], [
              '#listings\\.etsy\\.overrides\\.primaryColor',
              '#listings\\.etsy\\.marketplaceSpecifics\\.primaryColor',
          ]),
          mapColor(data.primaryColor || data.color, 'etsy'),
          'Etsy Color'
      );
      await fillDropdownField(
          resolveMarketplaceField('etsy', ['secondary color'], [
              '#listings\\.etsy\\.overrides\\.secondaryColor',
              '#listings\\.etsy\\.marketplaceSpecifics\\.secondaryColor',
          ]),
          mapColor(data.secondaryColor, 'etsy'),
          'Etsy Secondary Color'
      );

      await Promise.all([
          fillTextField('#listings\\.etsy\\.overrides\\.quantity', data.quantity, 'Etsy Quantity'),
          fillTextField('#listings\\.etsy\\.overrides\\.price', data.price, 'Etsy Price'),
          fillTextField('#listings\\.etsy\\.overrides\\.sku', data.sku, 'Etsy SKU'),
      ]);
      
      if (data.etsy_specifics) {
          await expandOptionalFields();
          await sleep(CONFIG.SLEEP_LONG);

          await fillDropdownField('#listings\\.etsy\\.marketplaceSpecifics\\.whoMade', specs.who_made || specs.whoMade, 'Who Made');
          await fillDropdownField('#listings\\.etsy\\.marketplaceSpecifics\\.whatIsIt', specs.what_is || specs.whatIsIt, 'What Is It');
          await fillDropdownField('#listings\\.etsy\\.marketplaceSpecifics\\.whenMade', normalizedWhenMade, 'When Made');
          
          // Tags and materials
          if (specs.tags || specs.materials) {
              const tagsEl = document.querySelector('#listings\\.etsy\\.marketplaceSpecifics\\.tags');
              const materialsEl = document.querySelector('#listings\\.etsy\\.marketplaceSpecifics\\.materials');
              
              if (tagsEl && specs.tags) {
                  const tags = Array.isArray(specs.tags) ? specs.tags : specs.tags.split(',').map(t => t.trim());
                  for (const tag of tags) await fillCombobox(tagsEl, tag, false, true);
                  recordFill({ field: 'Tags', status: 'filled', value: tags });
              } else if (specs.tags) {
                  recordFill({ field: 'Tags', status: 'not_found', reason: 'Etsy tags field not found', value: specs.tags });
              }
              
              if (materialsEl && specs.materials) {
                  const materials = Array.isArray(specs.materials) ? specs.materials : specs.materials.split(',').map(m => m.trim());
                  for (const material of materials) await fillCombobox(materialsEl, material, false, true);
                  recordFill({ field: 'Materials', status: 'filled', value: materials });
              } else if (specs.materials) {
                  recordFill({ field: 'Materials', status: 'not_found', reason: 'Etsy materials field not found', value: specs.materials });
              }
          }
          
          // Category specifics - find by label text matching
          log('Filling Etsy category specifics...');
          
          // Map of field names to label text patterns
          const etsyCategoryFieldMap = {
              'sleeveLength': ['sleeve length', 'sleeve'],
              'neckline': ['neckline', 'neck'],
              'clothingStyle': ['clothing style', 'clothing_style', 'style'],
              'closure': ['closure'],
              'collarStyle': ['collar style', 'collar_style', 'collar'],
              'pattern': ['pattern'],
              'occasion': ['occasion'],
              'holiday': ['holiday'],
              'sustainability': ['sustainability'],
              'fabric': ['fabric', 'fabric type'],
              'graphic': ['graphic', 'print'],
              'materials': ['materials', 'material'],
              'size': ['size']
          };
          
          // Get all category specific inputs
          const etsyCategoryInputs = Array.from(document.querySelectorAll(
              '[id^="listings\.etsy\.categorySpecifics\."], [name^="listings.etsy.categorySpecifics."]'
          )).filter(isVisibleElement);
          const categorySpecifics = { ...(specs.category_specifics || {}) };
          const rootLevelEtsyCategoryFields = [
              'sleeveLength', 'neckline', 'clothingStyle', 'closure', 'collarStyle',
              'pattern', 'occasion', 'holiday', 'sustainability', 'fabric', 'graphic', 'size'
          ];

          for (const fieldName of rootLevelEtsyCategoryFields) {
              if (specs[fieldName] && categorySpecifics[fieldName] == null) {
                  categorySpecifics[fieldName] = specs[fieldName];
              }
          }

          const etsyFallbackCategoryFields = {
              closure: ebaySpecifics.closure,
              collarStyle: ebaySpecifics.collarStyle || ebaySpecifics.collar_style || ebaySpecifics.neckline,
              sleeveLength: ebaySpecifics.sleeveLength,
              neckline: ebaySpecifics.neckline,
              occasion: ebaySpecifics.occasion,
              pattern: ebaySpecifics.pattern,
              size: data.size || ebaySpecifics.size,
          };

          for (const [fieldName, fallbackValue] of Object.entries(etsyFallbackCategoryFields)) {
              if (fallbackValue && categorySpecifics[fieldName] == null) {
                  categorySpecifics[fieldName] = fallbackValue;
              }
          }
          
          // Find each field by its label text and fill it
          for (const [jsonField, rawValue] of Object.entries(categorySpecifics)) {
              if (!rawValue) continue;

              const labelPatterns = etsyCategoryFieldMap[jsonField] || [normalizeText(jsonField)];
              const valuesToFill = (Array.isArray(rawValue)
                  ? rawValue.map(value => normalizeEtsyCategorySpecificValue(jsonField, value))
                  : (typeof rawValue === 'string' && rawValue.includes(','))
                      ? rawValue.split(',').map(value => normalizeEtsyCategorySpecificValue(jsonField, value.trim()))
                      : [normalizeEtsyCategorySpecificValue(jsonField, rawValue)]
              ).filter(Boolean);

              if (valuesToFill.length === 0) {
                  recordFill({
                    field: jsonField,
                    status: 'skipped',
                    reason: 'No matching Etsy option',
                    value: rawValue,
                  });
                  continue;
              }

              const foundEl = findInputByLabelPatterns(labelPatterns, isEtsyCategorySpecificInput) ||
                  findInputByContext(etsyCategoryInputs, labelPatterns);
              
              if (foundEl) {
                  const isMulti = jsonField === 'materials' || valuesToFill.length > 1;
                  log(`  Filling Etsy ${jsonField}: ${valuesToFill.join(', ')}`);
                  for (const value of valuesToFill) {
                      if (!value) continue;
                      await fillDropdownField(foundEl, value, jsonField, false, isMulti);
                      if (isMulti) await sleep(CONFIG.SLEEP_MEDIUM);
                  }
              } else {
                  warn(`  Could not find Etsy category field for ${jsonField}`);
                  recordFill({
                    field: jsonField,
                    status: 'skipped',
                    reason: 'Not on this category form',
                    value: valuesToFill.join(', '),
                  });
              }
          }
          
          // Handle materials field (category specific version)
          if (specs.materials && categorySpecifics.materials == null) {
              const materialsCatEl = findInputByLabelPatterns(['materials', 'material'], isEtsyCategorySpecificInput) ||
                  findInputByContext(etsyCategoryInputs, ['materials', 'material']);
              
              if (materialsCatEl) {
                  const materials = Array.isArray(specs.materials) ? specs.materials : specs.materials.split(',').map(m => m.trim());
                  log(`  Filling Etsy materials (category): ${materials.join(', ')}`);
                  for (const material of materials) {
                      await fillCombobox(materialsCatEl, material, false, true);
                  }
                  recordFill({ field: 'Materials', status: 'filled', value: materials });
              }
          }
      }
      
  }

  function listingSizeValue(data) {
      const value = data?.size || data?.size_us || data?.ebay_specifics?.size;
      return value == null ? '' : String(value).trim();
  }

  function listingTagValues(data) {
      const raw = data?.tags;
      if (!raw) return [];
      return (Array.isArray(raw) ? raw : String(raw).split(','))
          .map((tag) => String(tag).trim())
          .filter(Boolean);
  }

  function marketplaceSizeSelectors(marketplace) {
      return [
          `#listings\\.${marketplace}\\.overrides\\.size\\.option\\.value`,
          `#listings\\.${marketplace}\\.overrides\\.size`,
          `#listings\\.${marketplace}\\.marketplaceSpecifics\\.size`,
          `#listings\\.${marketplace}\\.categorySpecifics\\.size`,
      ];
  }

  function isSizeScaleControl(el) {
      if (!el) return false;
      const hay = `${el.id || ''} ${el.name || ''}`;
      if (/size\.scale|sizeType|size[_-]?scale|size[_-]?system/i.test(hay)) return true;
      const shown = displayedFieldValue(el);
      return /^(us standard|numeric|alpha|uk|eu|au)$/i.test(shown.trim());
  }

  function sizeControlToken(el) {
      const idToken = String(el?.id || el?.name || '').split('.').pop() || '';
      return normalizeFieldKey(idToken.replace(/^[0-9a-f]{8,}_/i, '').replace(/^\d+_/, ''));
  }

  function isMarketplaceSizeValueControl(el, marketplace) {
      if (!el || !isMarketplaceInput(marketplace)(el) || isSizeScaleControl(el)) return false;
      const id = String(el.id || '');
      if (sizeControlToken(el) === 'size') return true;
      return /(?:^|[._])size(?:\.option(?:\.value)?)?$/i.test(id) || /_size$/i.test(id);
  }

  function pickSizeValueControl(candidates) {
      const usable = (candidates || []).filter((el) =>
          el && isEnabledField(el) && !isSizeScaleControl(el) && (isVisibleElement(el) || isAttachedElement(el))
      );
      const visible = usable.filter(isVisibleElement);
      const pool = visible.length ? visible : usable;
      const empty = pool.filter((el) => !fieldLooksFilled(el));
      return empty[0] || pool[pool.length - 1] || null;
  }

  function queryMarketplaceSizeControls(marketplace) {
      const controls = document.querySelectorAll('input, textarea, select, [role="combobox"]');
      return Array.from(controls).filter((el) => isMarketplaceSizeValueControl(el, marketplace));
  }

  function findSizeControlsNearLabel(marketplace) {
      const labels = Array.from(document.querySelectorAll(
          'label, legend, div[class*="Label"], span[class*="Label"], span[class*="label"], div[class*="label"], h3, h4, p, span[class*="title"], div[class*="title"]'
      ));
      const inMarketplace = isMarketplaceInput(marketplace);
      for (const labelEl of labels) {
          if (!isVisibleElement(labelEl)) continue;
          const text = normalizeText(labelEl.innerText || labelEl.textContent || '').replace(/\s*\*$/, '');
          if (text !== 'size') continue;
          let container = labelEl;
          for (let depth = 0; depth < 6 && container; depth++) {
              const candidates = Array.from(
                  container.querySelectorAll('input:not([type="hidden"]), textarea, select, [role="combobox"]')
              ).filter((candidate) => isVisibleElement(candidate) && inMarketplace(candidate) && !isSizeScaleControl(candidate));
              if (candidates.length > 0) return candidates;
              container = container.parentElement;
          }
      }
      return [];
  }

  function findMarketplaceSizeControl(marketplace, preferredSelector = '') {
      if (preferredSelector) {
          const preferred = queryByRecordedSelector(preferredSelector);
          if (preferred && isEnabledField(preferred) && !isSizeScaleControl(preferred)) return preferred;
      }
      const hashed = pickSizeValueControl(queryMarketplaceSizeControls(marketplace));
      if (hashed) return hashed;
      for (const sel of marketplaceSizeSelectors(marketplace)) {
          try {
              const candidate = document.querySelector(sel);
              if (candidate && isEnabledField(candidate) && !isSizeScaleControl(candidate)
                  && (isVisibleElement(candidate) || isAttachedElement(candidate))) {
                  return candidate;
              }
          } catch (_) {}
      }
      return pickSizeValueControl(findSizeControlsNearLabel(marketplace));
  }

  async function fillMarketplaceSize(marketplace, data, preferredSelector = '') {
      const size = listingSizeValue(data);
      const attempts = size ? 8 : 1;
      let el = null;
      for (let attempt = 0; attempt < attempts; attempt++) {
          el = findMarketplaceSizeControl(marketplace, preferredSelector);
          if (el && isEnabledField(el)) break;
          el = null;
          await sleep(CONFIG.SLEEP_RETRY);
      }
      await fillDropdownField(el, size, 'Size', true);
  }

  async function fillMarketplaceTagField(marketplace, data, fieldName, labelPatterns, selectors = []) {
      const tags = listingTagValues(data);
      const el = resolveMarketplaceField(marketplace, labelPatterns, selectors);
      if (!tags.length) {
          recordFill({
            field: fieldName,
            status: 'skipped',
            reason: 'No value in listing',
            selector: selectorFor(el, ''),
            value: '',
          });
          return;
      }
      if (!el) {
          recordFill({
            field: fieldName,
            status: 'not_found',
            reason: `${fieldName} field not found`,
            value: tags,
          });
          return;
      }
      for (const tag of tags) await fillCombobox(el, tag, false, true);
      recordFill({ field: fieldName, status: 'filled', selector: selectorFor(el, ''), value: tags });
  }

  async function fillPoshmarkForm(data) {
      log('Filling Poshmark form...');
      await fillMarketplaceCategory('poshmark', data);
      await sleep(CONFIG.SLEEP_LONG);

      await fillDropdownField(
          '#listings\\.poshmark\\.overrides\\.condition',
          mapCondition(data.condition, 'poshmark'),
          'Poshmark Condition',
          true
      );
      await fillDropdownField('#listings\\.poshmark\\.overrides\\.brand', data.brand, 'Poshmark Brand');
      await fillDropdownField(
          '#listings\\.poshmark\\.overrides\\.primaryColor',
          mapColor(data.primaryColor || data.color, 'poshmark'),
          'Poshmark Color',
          true
      );
      await fillDropdownField(
          resolveMarketplaceField('poshmark', ['secondary color'], [
              '#listings\\.poshmark\\.overrides\\.secondaryColor',
              '#listings\\.poshmark\\.marketplaceSpecifics\\.secondaryColor',
          ]),
          mapColor(data.secondaryColor, 'poshmark'),
          'Secondary Color'
      );

      await Promise.all([
          fillTextField('#listings\\.poshmark\\.overrides\\.quantity', data.quantity, 'Poshmark Quantity'),
          fillTextField('#listings\\.poshmark\\.overrides\\.price', data.price, 'Poshmark Price'),
          fillTextField('#listings\\.poshmark\\.overrides\\.sku', data.sku, 'Poshmark SKU'),
      ]);

      await fillMarketplaceSize('poshmark', data);
      await fillMarketplaceTagField(
          'poshmark',
          data,
          'Style Tags',
          ['style tags', 'style tag'],
          [
              '#listings\\.poshmark\\.marketplaceSpecifics\\.styleTags',
              '#listings\\.poshmark\\.overrides\\.styleTags',
          ]
      );
      
      if (data.poshmark_specifics) {
          await fillTextField('#listings\\.poshmark\\.marketplaceSpecifics\\.originalPrice', data.poshmark_specifics.originalPrice, 'Original Price');
      }
      
  }

  async function setMercariNoBrandChecked(checked, reason = '') {
      const el = resolveMarketplaceField('mercari', ['no brand', 'not sure', 'no brand/not sure'], [
          '#listings\\.mercari\\.overrides\\.noBrand',
          'input[name="listings.mercari.overrides.noBrand"]',
      ]);
      if (!el) {
          if (checked) {
              warn('No Brand/Not Sure: Element not found');
              recordFill({
                field: 'No Brand/Not Sure',
                status: 'not_found',
                reason: 'Element not found',
                selector: '#listings.mercari.overrides.noBrand',
              });
          }
          return { status: 'not_found' };
      }

      const want = Boolean(checked);
      if (Boolean(el.checked) === want) {
          if (want) {
              recordFill({
                field: 'No Brand/Not Sure',
                status: 'filled',
                reason: reason || 'Already set',
                selector: selectorFor(el, ''),
                value: true,
              });
          }
          return { status: 'filled' };
      }

      const label = el.id ? document.querySelector(`label[for="${el.id}"]`) : null;
      const clickTarget = label || el.closest('label') || el;
      clickTarget.click();
      await sleep(CONFIG.SLEEP_SHORT);
      if (Boolean(el.checked) !== want) {
          el.click();
          await sleep(CONFIG.SLEEP_SHORT);
      }
      if (Boolean(el.checked) !== want) {
          el.checked = want;
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
      }

      if (!want) return { status: Boolean(el.checked) === want ? 'filled' : 'failed' };

      const ok = Boolean(el.checked) === want;
      if (ok) log(`Mercari brand missing from list. Checking No Brand/Not Sure.`);
      else warn('No Brand/Not Sure: checkbox did not toggle');
      recordFill({
        field: 'No Brand/Not Sure',
        status: ok ? 'filled' : 'failed',
        reason: ok ? (reason || 'Brand not in Mercari list') : 'Checkbox did not toggle',
        selector: selectorFor(el, ''),
        value: true,
      });
      return { status: ok ? 'filled' : 'failed' };
  }

  async function fillMercariBrand(data) {
      const el = resolveMarketplaceField('mercari', ['brand'], [
          '#listings\\.mercari\\.overrides\\.brand',
      ]);
      if (!el) {
          warn('Mercari Brand: Element not found');
          recordFill({ field: 'Mercari Brand', status: 'not_found', reason: 'Element not found' });
          await setMercariNoBrandChecked(true, 'Brand field not found');
          return;
      }
      if (fieldLooksFilled(el)) await clearInput(el);

      const candidates = brandFillCandidates(data.brand).filter(
          (candidate) => normalizeOptionValue(candidate) !== 'other'
      );
      if (candidates.length === 0) {
          recordFill({
            field: 'Mercari Brand',
            status: 'skipped',
            reason: 'No value in listing',
            selector: selectorFor(el, ''),
          });
          await setMercariNoBrandChecked(true, 'No brand in listing');
          return;
      }
      for (const candidate of candidates) {
          log(`Trying Mercari Brand: "${candidate}"`);
          const result = await fillDropdownField(el, candidate, 'Mercari Brand', true);
          if (result.status === 'filled') {
              log(`  ✓ Mercari Brand: "${el.value || candidate}"`);
              await setMercariNoBrandChecked(false);
              return;
          }
      }

      if (fieldLooksFilled(el)) await clearInput(el);
      await setMercariNoBrandChecked(true, 'Brand not in Mercari list');
  }

  async function fillMercariForm(data) {
      log('Filling Mercari form...');

      await fillDropdownField(
          resolveMarketplaceField('mercari', ['condition'], [
              '#listings\\.mercari\\.overrides\\.condition',
          ]),
          mapCondition(data.condition, 'mercari'),
          'Mercari Condition',
          true
      );
      await fillMercariBrand(data);

      await Promise.all([
          fillTextField('#listings\\.mercari\\.overrides\\.quantity', data.quantity, 'Mercari Quantity'),
          fillTextField('#listings\\.mercari\\.overrides\\.price', data.price, 'Mercari Price'),
      ]);

      await fillMarketplaceSize('mercari', data);

      const shippingLabel = (data.mercari_specifics && data.mercari_specifics.shippingLabel) || 'USPS Ground Advantage';
      const shippingEl = await waitForMarketplaceField('mercari', ['shipping label'], [
          '#listings\\.mercari\\.marketplaceSpecifics\\.shipping\\.carrierId',
          '#listings\\.mercari\\.marketplaceSpecifics\\.shippingLabel',
          '#listings\\.mercari\\.marketplaceSpecifics\\.shipping\\.shippingLabel',
          '#listings\\.mercari\\.overrides\\.shippingLabel',
      ]);
      if (shippingEl) {
          const currentVal = (shippingEl.value || '').trim().toLowerCase();
          if (!currentVal.includes('usps ground advantage')) {
              log(`Setting Mercari shipping to ${shippingLabel}`);
              await fillDropdownField(shippingEl, shippingLabel, 'Shipping Label', false);
          } else {
              log('Mercari shipping already USPS Ground Advantage');
              recordFill({
                field: 'Shipping Label',
                status: 'filled',
                reason: 'Already set',
                selector: selectorFor(shippingEl, ''),
                value: shippingLabel,
              });
          }
      } else {
          warn('Mercari shipping label field not found');
          recordFill({
            field: 'Shipping Label',
            status: 'not_found',
            reason: 'Shipping label field not found',
            value: shippingLabel,
          });
      }
      
  }

  const DEPOP_SIZE_GROUPINGS = {
      maternity: 'Maternity',
      petite: 'Petite',
      'plus size': 'Plus size',
      tall: 'Tall',
  };

  const SIZE_TYPE_TO_DEPOP_GROUPING = {
      maternity: 'Maternity',
      petite: 'Petite',
      petites: 'Petite',
      'plus size': 'Plus size',
      plus: 'Plus size',
      tall: 'Tall',
  };

  function resolveDepopSizeGrouping(specs, data) {
      const raw = specs.size_grouping || specs.sizeGrouping;
      if (raw) {
          const normalized = normalizeOptionValue(raw);
          if (DEPOP_SIZE_GROUPINGS[normalized]) {
              return DEPOP_SIZE_GROUPINGS[normalized];
          }
          const canonical = Object.values(DEPOP_SIZE_GROUPINGS).find(
              (value) => normalizeOptionValue(value) === normalized
          );
          if (canonical) return canonical;
          return null;
      }

      const sizeType = normalizeOptionValue(data.sizeType || data.ebay_specifics?.sizeType);
      if (!sizeType || sizeType === 'regular') return null;
      return SIZE_TYPE_TO_DEPOP_GROUPING[sizeType] || null;
  }

  async function fillDepopBrand(data) {
      const el = resolveMarketplaceField('depop', ['brand'], [
          '#listings\\.depop\\.overrides\\.brand',
      ]);
      if (!el) {
          warn('Depop Brand: Element not found');
          recordFill({ field: 'Depop Brand', status: 'not_found', reason: 'Element not found' });
          return;
      }
      if (fieldLooksFilled(el)) await clearInput(el);

      for (const candidate of brandFillCandidates(data.brand)) {
          log(`Trying Depop Brand: "${candidate}"`);
          const result = await fillDropdownField(el, candidate, 'Depop Brand', true);
          if (result.status === 'filled') {
              log(`  ✓ Depop Brand: "${el.value || candidate}"`);
              return;
          }
      }
      if (optionMatchesValue(displayedFieldValue(el), 'Other', true)) return;
      log('Depop brand missing from list. Selecting Other.');
      const fallback = await fillDropdownField(el, 'Other', 'Depop Brand', true);
      if (fallback.status === 'filled') {
          log(`  ✓ Depop Brand: "Other"`);
          return;
      }
      warn('Depop Brand: could not select a list brand or Other');
  }

  async function fillDepopForm(data) {
      log('Filling Depop form...');

      await fillDropdownField(
          resolveMarketplaceField('depop', ['condition'], [
              '#listings\\.depop\\.overrides\\.condition',
          ]),
          mapCondition(data.condition || data.depop_specifics?.condition, 'depop'),
          'Depop Condition',
          true
      );
      await fillDropdownField(
          resolveMarketplaceField('depop', ['primary color'], [
              '#listings\\.depop\\.overrides\\.primaryColor',
          ]),
          mapColor(data.primaryColor || data.color, 'depop'),
          'Depop Color',
          true
      );
      await fillDropdownField(
          resolveMarketplaceField('depop', ['secondary color'], [
              '#listings\\.depop\\.overrides\\.secondaryColor',
          ]),
          mapColor(data.secondaryColor, 'depop'),
          'Depop Secondary Color'
      );

      await Promise.all([
          fillTextField('#listings\\.depop\\.overrides\\.quantity', data.quantity, 'Depop Quantity'),
          fillTextField('#listings\\.depop\\.overrides\\.price', data.price, 'Depop Price'),
          fillTextField('#listings\\.depop\\.overrides\\.sku', data.sku, 'Depop SKU'),
      ]);

      await fillDepopBrand(data);
      await fillMarketplaceSize('depop', data);
      await fillMarketplaceTagField(
          'depop',
          data,
          'Tags',
          ['tags'],
          [
              '#listings\\.depop\\.marketplaceSpecifics\\.tags',
              '#listings\\.depop\\.overrides\\.tags',
          ]
      );
      
      if (data.depop_specifics) {
          log('Expanding optional fields for Depop...');
          await expandOptionalFields();
          const specs = data.depop_specifics;
          const getVisibleDepopInputs = () => Array.from(
              document.querySelectorAll('input:not([type="hidden"]), textarea, select, [role="combobox"]')
          ).filter(isVisibleElement);
          const findDepopField = (labelPatterns, directSelector = null) => {
              if (directSelector) {
                  const directEl = document.querySelector(directSelector);
                  if (isVisibleElement(directEl)) {
                      return directEl;
                  }
              }

              const depopScopedEl = findInputByLabelPatterns(
                  labelPatterns,
                  input => isVisibleElement(input) && isDepopSpecificInput(input)
              );
              if (depopScopedEl) {
                  return depopScopedEl;
              }

              return findInputByContext(getVisibleDepopInputs(), labelPatterns);
          };
          
          // Marketplace specifics — sequential so dropdowns don't steal each other's menus
          await fillDropdownField(findDepopField(['source'], '#listings\\.depop\\.marketplaceSpecifics\\.source'), specs.source, 'Source');
          await fillDropdownField(findDepopField(['age'], '#listings\\.depop\\.marketplaceSpecifics\\.age'), specs.age, 'Age');
          
          // Style (multi-value)
          if (specs.style) {
              const styles = Array.isArray(specs.style) ? specs.style : specs.style.split(',').map(s => s.trim());
              const styleEl = findDepopField(['style'], '#listings\\.depop\\.marketplaceSpecifics\\.style');
              if (styleEl) {
                  log(`Filling ${styles.length} style tags...`);
                  for (const style of styles) await fillCombobox(styleEl, style, false, true);
                  recordFill({ field: 'Style', status: 'filled', value: styles });
              } else {
                  warn('Style field not found for Depop');
                  recordFill({ field: 'Style', status: 'not_found', reason: 'Style field not found', value: styles });
              }
          }
          
          const occasionData = specs.occasion || data.ebay_specifics?.occasion;
          if (occasionData) {
              const occasionMap = {
                  'workwear': 'Work', 'activewear': 'Workout', 'formal': 'Special Occasion',
                  'party/cocktail': 'Party', 'everyday': 'Casual', 'travel': 'Vacation', 'business': 'Work'
              };
              let rawOccasions = Array.isArray(occasionData) ? occasionData : String(occasionData).split(',').map(o => o.trim()).filter(Boolean);
              const occasions = rawOccasions.map(o => {
                  const lower = o.toLowerCase();
                  for (let key in occasionMap) {
                      if (lower.includes(key)) return occasionMap[key];
                  }
                  return o;
              });
              const occasionEl = findDepopField(['occasion'], '#listings\\.depop\\.marketplaceSpecifics\\.occasion');
              if (occasionEl) {
                  log(`Filling ${occasions.length} occasion tags...`);
                  for (const occasion of occasions) await fillCombobox(occasionEl, occasion, false, true);
                  recordFill({ field: 'Occasion', status: 'filled', value: occasions });
              } else {
                  warn('Occasion field not found for Depop');
                  recordFill({ field: 'Occasion', status: 'not_found', reason: 'Occasion field not found', value: occasions });
              }
          }

          const materialData = specs.material || data.ebay_specifics?.material || data.ebay_specifics?.fabricType;

          if (resolveDepopSizeGrouping(specs, data) || materialData) {
              log('Filling Depop category specifics...');
          }

          const sizeGroupingValue = resolveDepopSizeGrouping(specs, data);
          if (sizeGroupingValue) {
              const sizeGroupingEl = findDepopField(
                  ['size grouping', 'size group', 'body fit'],
                  '#listings\\.depop\\.categorySpecifics\\.sizeGrouping'
              );
              if (sizeGroupingEl) {
                  await fillDropdownField(sizeGroupingEl, sizeGroupingValue, 'Size Grouping', true);
              } else {
                  warn('Size Grouping field not found for Depop');
                  recordFill({ field: 'Size Grouping', status: 'not_found', reason: 'Size Grouping field not found', value: sizeGroupingValue });
              }
          } else if (specs.size_grouping || specs.sizeGrouping) {
              warn(`Skipping invalid Depop size grouping: "${specs.size_grouping || specs.sizeGrouping}"`);
              recordFill({
                  field: 'Size Grouping',
                  status: 'skipped',
                  reason: 'Invalid or regular sizing — omit size grouping',
                  value: specs.size_grouping || specs.sizeGrouping,
              });
          } else {
              recordFill({
                  field: 'Size Grouping',
                  status: 'skipped',
                  reason: 'Regular sizing — omit size grouping',
              });
          }

          if (materialData) {
              const materialMap = {
                  'spandex': 'Elastane / Lycra / Spandex',
                  'lycra': 'Elastane / Lycra / Spandex',
                  'elastane': 'Elastane / Lycra / Spandex',
                  'vegan leather': 'Faux leather',
                  'faux leather': 'Faux leather',
                  'genuine leather': 'Leather',
                  'real leather': 'Leather',
                  'faux fur': 'Faux fur'
              };
              let rawMaterials = Array.isArray(materialData)
                  ? materialData
                  : String(materialData).split(',').map(value => value.trim()).filter(Boolean);
              
              const materials = rawMaterials.map(m => {
                  let val = m.toLowerCase();
                  for (let key in materialMap) {
                      if (val.includes(key)) return materialMap[key];
                  }
                  val = val.replace(/ blend|pure |100% /g, '').trim();
                  return val.charAt(0).toUpperCase() + val.slice(1);
              });
              
              const materialEl = findDepopField(
                  ['material', 'materials'],
                  '#listings\\.depop\\.categorySpecifics\\.material'
              );
              if (materialEl) {
                  log(`Filling ${materials.length} material tag${materials.length === 1 ? '' : 's'}...`);
                  for (const material of materials) {
                      await fillCombobox(materialEl, material, false, materials.length > 1);
                  }
                  recordFill({ field: 'Material', status: 'filled', value: materials });
              } else {
                  warn('Material field not found for Depop');
                  recordFill({ field: 'Material', status: 'not_found', reason: 'Material field not found', value: materials });
              }
          }
      }
      
  }

  // ============================================
  // MAIN FILL FUNCTION
  // ============================================

  async function fillForm(data, platformName = 'VENDOO') {
      createStatusBox();
      const platform = platformName.toUpperCase();
      log(`🚀 STARTING FILL: ${data.title || '(no title)'} (${platform})`);
      log(`📍 Page: ${window.location.href}`);
      
      const startTime = Date.now();
      
      try {
          switch (platform) {
              case 'EBAY':
                  await fillEbayForm(data);
                  break;
              case 'ETSY':
                  await fillEtsyForm(data);
                  break;
              case 'POSHMARK':
                  await fillPoshmarkForm(data);
                  break;
              case 'MERCARI':
                  await fillMercariForm(data);
                  break;
              case 'DEPOP':
                  await fillDepopForm(data);
                  break;
              default:
                  await fillMainForm(data);
          }

          const duration = ((Date.now() - startTime) / 1000).toFixed(1);
          log(`✅ === FILL COMPLETE in ${duration}s ===`);
          chrome.runtime.sendMessage({ type: 'FILL_COMPLETE', platform, duration });
          
      } catch (err) {
          error(`Fill Error: ${err.message}`);
          console.error(err);
          chrome.runtime.sendMessage({ type: 'FILL_ERROR', platform: platform, error: err.message });
      }
  }

  // ============================================
  // STUDIO AUTOMATION COMMANDS
  // ============================================

  async function uploadStudioPhotos(photos, studioUrl, jobId) {
      if (!photos || photos.length === 0) {
          return { ok: true, count: 0 };
      }

      log(`Uploading ${photos.length} photos from Studio...`);

      let imageInput = null;
      for (let attempt = 0; attempt < 15; attempt++) {
          imageInput = document.querySelector('#imageInput, input[type="file"][accept*="image"]');
          if (imageInput) break;
          if (attempt < 14) await sleep(1000);
      }

      if (!imageInput) {
          warn('Image input not found after waiting');
          const allInputs = document.querySelectorAll('input[type="file"]');
          warn(`All file inputs on page: ${allInputs.length}`);
          allInputs.forEach((inp, i) => warn(`  [${i}] ${inp.id} accept=${inp.accept}`));
          return { ok: false, error: 'Image input not found' };
      }

      const fileObjects = [];
      for (const photo of photos) {
          try {
              const url = `${studioUrl}/api/jobs/${jobId}/photos/${photo.id || photo.stored_filename || photo.name}`;
              const response = await fetch(url);
              if (!response.ok) {
                  warn(`Failed to fetch photo: ${url} status=${response.status}`);
                  continue;
              }
              const blob = await response.blob();
              const name = photo.name || photo.original_filename || 'photo.jpg';
              const file = new File([blob], name, { type: blob.type || 'image/jpeg' });
              fileObjects.push(file);
          } catch (e) {
              warn(`Photo fetch error: ${e.message}`);
          }
      }

      if (fileObjects.length === 0) {
          return { ok: false, error: 'No photos could be fetched' };
      }

      const dt = new DataTransfer();
      fileObjects.forEach(f => dt.items.add(f));
      imageInput.files = dt.files;
      imageInput.dispatchEvent(new Event('change', { bubbles: true }));
      imageInput.dispatchEvent(new Event('input', { bubbles: true }));

      await sleep(CONFIG.SLEEP_LONG * 4);

      log(`Uploaded ${fileObjects.length} photos`);
      return { ok: true, count: fileObjects.length };
  }

  async function saveGeneralForm() {
      log('Saving form...');
      const saveBtn = document.querySelector('[data-testid="save-item-button"]');
      if (saveBtn) {
          saveBtn.scrollIntoView({ block: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_MEDIUM);
          saveBtn.click();
          await sleep(CONFIG.SLEEP_LONG * 3);
          log('Save button clicked, waiting for completion');

          for (let i = 0; i < 10; i++) {
              await sleep(1000);
              const stillLoading = document.querySelector('[data-testid="save-item-button"][disabled], button:disabled');
              if (!stillLoading) break;
          }

          const itemId = extractItemId();
          const vendooUrl = itemId ? `https://web.vendoo.co/app/item/${itemId}` : window.location.href;

          log(`Save complete. Item ID: ${itemId || 'unknown'}`);
          return { ok: true, vendoo_item_id: itemId, vendoo_url: vendooUrl };
      }

      const buttons = Array.from(document.querySelectorAll('button, div[role="button"]'));
      const PROHIBITED_TERMS = ['list', 'publish', 'activate', 'sell'];
      const target = buttons.find(b => {
          const t = (b.innerText || '').trim().toLowerCase();
          if (!t || t.length > 20) return false;
          if (!t.includes('save')) return false;
          if (PROHIBITED_TERMS.some(pt => t.includes(pt))) {
              warn(`Skipping prohibited save button: "${b.innerText}"`);
              return false;
          }
          return true;
      });

      if (target) {
          target.scrollIntoView({ block: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_MEDIUM);
          target.click();
          await sleep(CONFIG.SLEEP_LONG * 3);
          const itemId = extractItemId();
          return { ok: true, vendoo_item_id: itemId, vendoo_url: window.location.href };
      }

      warn('Save button not found');
      return { ok: false, error: 'Save button not found' };
  }

  async function auditGeneralForm(data) {
      log('Auditing general form...');
      const fields = {};

      const checks = [
          { key: 'title', selector: '#generalDetails\\.title', label: 'Title' },
          { key: 'description', selector: '#generalDetails\\.description', label: 'Description' },
          { key: 'price', selector: '#generalDetails\\.price', label: 'Price' },
          { key: 'quantity', selector: '#generalDetails\\.quantity', label: 'Quantity' },
          { key: 'category', selector: '#categoryV2, [role="category-input"]', label: 'Category' },
          { key: 'size', selector: '#generalDetails\\.size\\.option\\.value', label: 'Size' },
      ];

      for (const check of checks) {
          const el = document.querySelector(check.selector);
          const expected = data[check.key];
          const observed = el ? el.value : null;
          const state = expected != null && observed != null && String(observed) === String(expected)
              ? 'audited_complete' : 'attempted_unverified';

          fields[check.key] = { state, expected: String(expected ?? ''), observed: String(observed ?? '') };
      }

      const allOk = Object.values(fields).every(f => f.state === 'audited_complete');
      if (!allOk) {
          warn('Some audit checks are unverified - continuing');
      }
      return { ok: true, fields };
  }

  async function fillMarketplaceForm(data, platform) {
      beginFillLog(String(platform || 'unknown').toLowerCase());
      log(`Filling ${platform} marketplace...`);

      try {
      await activateMarketplaceSection(platform);

      switch (platform.toLowerCase()) {
          case 'ebay':
              await fillEbayForm(data);
              break;
          case 'etsy':
              await fillEtsyForm(data);
              break;
          case 'poshmark':
              await fillPoshmarkForm(data);
              break;
          case 'mercari':
              await fillMercariForm(data);
              break;
          case 'depop':
              await fillDepopForm(data);
              break;
          default:
              warn(`Unknown marketplace: ${platform}`);
              recordFill({ field: 'marketplace', status: 'failed', reason: `Unknown marketplace: ${platform}` });
      }

      return { ok: true, fill_log: finishFillLog() };
      } catch (err) {
          recordFill({ field: 'form', status: 'failed', reason: err.message });
          error(`Fill Error: ${err.message}`);
          return { ok: false, error: err.message, fill_log: finishFillLog() };
      }
  }

  async function activateMarketplaceSection(platform) {
      log(`Activating ${platform} marketplace section...`);

      const buttonTexts = [platform, platform.toUpperCase(), platform.charAt(0).toUpperCase() + platform.slice(1)];
      const buttons = Array.from(document.querySelectorAll(
          'button, [role="button"], div[role="tab"], a, span[role="button"]'
      ));

      for (const btn of buttons) {
          const text = (btn.innerText || btn.textContent || '').trim().toLowerCase();
          if (buttonTexts.some(t => text.includes(t.toLowerCase()))) {
              const expanded = btn.getAttribute('aria-expanded');
              if (expanded === 'true') {
                  log(`  ${platform} section already expanded`);
                  await sleep(CONFIG.SLEEP_LONG);
                  return;
              }
              log(`  Clicking "${btn.innerText}" to activate ${platform}`);
              btn.scrollIntoView({ block: 'center', behavior: 'instant' });
              await sleep(CONFIG.SLEEP_SHORT);
              btn.click();
              await sleep(CONFIG.SLEEP_LONG * 2);
              return;
          }
      }

      await expandOptionalFields();
      await sleep(CONFIG.SLEEP_LONG);

      for (const btn of buttons) {
          const text = (btn.innerText || btn.textContent || '').trim().toLowerCase();
          if (buttonTexts.some(t => text.includes(t.toLowerCase()))) {
              log(`  Clicking "${btn.innerText}" to activate ${platform}`);
              btn.scrollIntoView({ block: 'center', behavior: 'instant' });
              await sleep(CONFIG.SLEEP_SHORT);
              btn.click();
              await sleep(CONFIG.SLEEP_LONG * 2);
              return;
          }
      }

      warn(`Could not find activation button for ${platform}`);
  }

  async function auditMarketplaceForm(data, platform) {
      log(`Auditing ${platform} marketplace...`);
      const fields = {};
      let foundAnyField = false;

      const platformSelectors = {
          ebay: ['#listings\\.ebay\\.overrides\\.brand', '#listings\\.ebay\\.overrides\\.price', '#listings\\.ebay\\.overrides\\.quantity'],
          etsy: ['#listings\\.etsy\\.overrides\\.price', '#listings\\.etsy\\.overrides\\.quantity', '#listings\\.etsy\\.marketplaceSpecifics\\.whoMade'],
          poshmark: ['#listings\\.poshmark\\.overrides\\.brand', '#listings\\.poshmark\\.overrides\\.price', '#listings\\.poshmark\\.overrides\\.quantity'],
          mercari: ['#listings\\.mercari\\.overrides\\.brand', '#listings\\.mercari\\.overrides\\.price', '#listings\\.mercari\\.overrides\\.quantity'],
          depop: ['#listings\\.depop\\.overrides\\.price', '#listings\\.depop\\.overrides\\.quantity', '#listings\\.depop\\.marketplaceSpecifics\\.source'],
      };

      const selectors = platformSelectors[platform.toLowerCase()] || [];
      for (const sel of selectors) {
          const el = document.querySelector(sel);
          fields[sel] = { found: !!el, value: el ? (el.value || 'present') : 'missing' };
          if (el) foundAnyField = true;
      }

      if (!foundAnyField) {
          warn(`${platform}: No marketplace fields found. Section may not be activated.`);
          fields._error = `${platform} marketplace section appears inactive`;
      }

      return { ok: true, fields };
  }

  function extractItemId() {
      const match = window.location.href.match(/\/app\/item\/([^/?]+)/);
      if (match) return match[1];

      const draftMatch = window.location.href.match(/\/item\/([^/?]+)/);
      if (draftMatch) return draftMatch[1];

      const el = document.querySelector('[data-item-id], [data-testid="item-id"]');
      if (el) return el.getAttribute('data-item-id') || el.textContent?.trim();

      return null;
  }

  function controlValue(selector) {
      const el = document.querySelector(selector);
      if (!el) return '';
      if ('value' in el && el.value != null && String(el.value).trim()) return String(el.value).trim();
      const text = (el.innerText || el.textContent || '').trim();
      return text;
  }

  function scrapeVendooItem() {
      const itemId = extractItemId();
      if (itemId === 'new') {
          return { ok: false, error: 'This is a new item, not a saved draft', url: window.location.href, item_id: null };
      }
      const form = {
          itemID: itemId,
          generalDetails: {
              title: controlValue(VENDOO_SELECTORS.title),
              description: controlValue(VENDOO_SELECTORS.description),
              brand: controlValue(VENDOO_SELECTORS.brand),
              condition: controlValue(VENDOO_SELECTORS.condition),
              primaryColor: controlValue(VENDOO_SELECTORS.primaryColor),
              secondaryColor: controlValue(VENDOO_SELECTORS.secondaryColor),
              zipCode: controlValue(VENDOO_SELECTORS.zipCode),
              tags: controlValue(VENDOO_SELECTORS.tags),
              quantity: controlValue(VENDOO_SELECTORS.quantity),
              size: controlValue(VENDOO_SELECTORS.size),
              sku: controlValue(VENDOO_SELECTORS.sku),
              price: controlValue(VENDOO_SELECTORS.price),
              cost: controlValue(VENDOO_SELECTORS.cost),
              notes: controlValue(VENDOO_SELECTORS.notes),
              categoryV2: controlValue(VENDOO_SELECTORS.category),
              weight: {
                  pounds: controlValue(VENDOO_SELECTORS.weightLb),
                  ounces: controlValue(VENDOO_SELECTORS.weightOz),
              },
              dimensions: {
                  length: controlValue(VENDOO_SELECTORS.length),
                  width: controlValue(VENDOO_SELECTORS.width),
                  height: controlValue(VENDOO_SELECTORS.height),
              },
          },
      };
      const filled = Object.values(form.generalDetails).some((value) => {
          if (value && typeof value === 'object') return Object.values(value).some(Boolean);
          return Boolean(value);
      });
      return {
          ok: filled || Boolean(itemId),
          source: 'form',
          item_id: itemId,
          url: window.location.href,
          form,
      };
  }

  async function clearChipContainer(el) {
      const container = el.closest('.MuiAutocomplete-root, .MuiFormControl-root') || el.parentElement;
      if (!container) return;
      for (let i = 0; i < 40; i++) {
          const chipDelete = container.querySelector('.MuiChip-deleteIcon, [data-testid*="Cancel"], [aria-label="Remove"], [aria-label="delete"]');
          if (!chipDelete) break;
          chipDelete.dispatchEvent(new MouseEvent('click', { bubbles: true }));
          await sleep(CONFIG.SLEEP_SHORT);
      }
  }

  async function clearControl(el) {
      if (!el) return;
      const type = String(el.getAttribute('type') || el.type || '').toLowerCase();
      if (type === 'file' || type === 'hidden' || type === 'checkbox' || type === 'radio') return;
      await clearChipContainer(el);
      await clearInput(el);
  }

  async function clearGeneralForm() {
      log('Clearing leftover general fields (photos unchanged)');
      for (const [name, selector] of Object.entries(VENDOO_SELECTORS)) {
          if (name === 'zipCode' || name === 'category') continue;
          const el = document.querySelector(selector);
          if (!el) continue;
          await clearControl(el);
      }
      return { ok: true };
  }

  async function clearMarketplaceForm(platform) {
      const prefix = `listings.${String(platform || '').toLowerCase()}`;
      log(`Clearing leftover ${prefix} fields`);
      const controls = document.querySelectorAll('input, textarea, select, [role="combobox"]');
      for (const el of controls) {
          const id = el.id || '';
          if (!id.startsWith(prefix)) continue;
          if (/image/i.test(id)) continue;
          await clearControl(el);
      }
      return { ok: true };
  }

  function queryByRecordedSelector(selector) {
      if (!selector) return null;
      try {
          const el = document.querySelector(selector);
          if (el) return el;
      } catch (_) { /* invalid selector */ }
      if (selector.charAt(0) === '#') {
          const rawId = selector.slice(1).replace(/\\./g, '.');
          const byId = document.getElementById(rawId);
          if (byId) return byId;
          if (window.CSS && typeof window.CSS.escape === 'function') {
              try {
                  return document.querySelector(`#${window.CSS.escape(rawId)}`);
              } catch (_) { /* ignore */ }
          }
      }
      return null;
  }

  function findControlForPatch(item) {
      const bySelector = queryByRecordedSelector(item.selector);
      if (bySelector) return bySelector;
      const want = normalizeFieldKey(item.field);
      if (!want) return null;
      const marketplace = String(currentFillMarketplace || 'general').toLowerCase();
      const inMarketplace = marketplace && marketplace !== 'general' && marketplace !== 'unknown'
          ? isMarketplaceInput(marketplace)
          : (el) => isCurrentMarketplaceControl(el);
      const controls = document.querySelectorAll('input, textarea, select, [role="combobox"]');
      for (const el of controls) {
          if (!inMarketplace(el)) continue;
          if (want === 'size' && isSizeScaleControl(el)) continue;
          if (normalizeFieldKey(fieldLabelForControl(el)) === want) return el;
          const idToken = String(el.id || el.name || '').split('.').pop() || '';
          const token = normalizeFieldKey(idToken.replace(/^[0-9a-f]{8,}_/i, '').replace(/^\d+_/, ''));
          if (token === want) return el;
      }
      if (marketplace && marketplace !== 'general' && marketplace !== 'unknown') {
          return findInputByExactLabel(item.field, isMarketplaceInput(marketplace));
      }
      return null;
  }

  async function waitForPatchControl(item) {
      let seen = false;
      for (let attempt = 0; attempt < 6; attempt++) {
          const el = findControlForPatch(item);
          if (el) {
              seen = true;
              if (isEnabledField(el) && (isVisibleElement(el) || isAttachedElement(el))) return el;
          } else if (!seen && attempt >= 2) {
              break;
          }
          await sleep(CONFIG.SLEEP_RETRY);
      }
      return findControlForPatch(item);
  }

  async function fillTextFieldByElement(el, value, fieldName) {
      const selectorText = selectorFor(el, '');
      if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) {
          recordFill({ field: fieldName, status: 'skipped', reason: 'No value in listing', selector: selectorText, value });
          return { status: 'skipped' };
      }
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
      await clearInput(el);
      setReactValue(el, value);
      await sleep(CONFIG.SLEEP_SHORT);
      log(`  ✓ ${fieldName}: "${value}"`);
      recordFill({ field: fieldName, status: 'filled', selector: selectorText, value });
      return { status: 'filled' };
  }

  function reverifyPatchedFields(items) {
      for (const item of items) {
          const fieldName = item.field || 'Field';
          const intended = String(item.value || '').trim();
          const entry = [...fillLedger].reverse().find((row) =>
              (item.id && row.id === item.id) ||
              normalizeFieldKey(row.field) === normalizeFieldKey(fieldName)
          );
          if (!entry || entry.status === 'skipped' || entry.status === 'not_found') continue;
          const el = findControlForPatch(item);
          if (!el) {
              entry.status = 'failed';
              entry.reason = 'Field disappeared after fill';
              continue;
          }
          const shown = displayedFieldValue(el);
          const matches = Boolean(intended && optionMatchesValue(shown, intended, false));
          if (entry.status === 'filled') {
              if (!matches) {
                  entry.status = 'failed';
                  entry.reason = shouldFillAsDropdown(el, fieldName)
                      ? 'Dropdown option was not selected'
                      : 'Value did not stick';
              }
              continue;
          }
          if (shouldFillAsDropdown(el, fieldName) && !matches) {
              entry.status = 'failed';
              entry.reason = 'Dropdown option was not selected';
          } else if (!shouldFillAsDropdown(el, fieldName) && !fieldLooksFilled(el)) {
              entry.status = 'failed';
              entry.reason = 'Value did not stick';
          }
      }
  }

  async function fillSelectedFields(fields) {
      const items = Array.isArray(fields) ? fields : [];
      const grouped = new Map();
      for (const item of items) {
          const marketplace = String(item.marketplace || 'general').toLowerCase();
          if (!grouped.has(marketplace)) grouped.set(marketplace, []);
          grouped.get(marketplace).push(item);
      }

      const allEntries = [];
      try {
          for (const [marketplace, group] of grouped) {
              beginFillLog(marketplace);
              if (marketplace && marketplace !== 'general' && marketplace !== 'unknown') {
                  await activateMarketplaceSection(marketplace);
              }
              await expandOptionalFields();
              await sleep(CONFIG.SLEEP_LONG * 2);
              group.sort((left, right) => {
                  const leftKey = normalizeFieldKey(left.field);
                  const rightKey = normalizeFieldKey(right.field);
                  if (leftKey === 'category' && rightKey !== 'category') return -1;
                  if (rightKey === 'category' && leftKey !== 'category') return 1;
                  if (leftKey === 'size' && rightKey !== 'size') return 1;
                  if (rightKey === 'size' && leftKey !== 'size') return -1;
                  return 0;
              });
              for (const item of group) {
                  currentPatchEntryId = item.id || '';
                  const fieldName = item.field || 'Field';
                  const value = mapPatchValue(marketplace, fieldName, item.value);
                  item.value = value;
                  const fieldKey = normalizeFieldKey(fieldName);
                  if (fieldKey === 'category') {
                      if (marketplace === 'general' || marketplace === 'unknown') {
                          const result = await fillCategoryPath({ category_path: value });
                          recordFill({
                              field: fieldName,
                              status: result.ok ? (result.filled ? 'filled' : 'skipped') : 'failed',
                              reason: result.error || '',
                              selector: item.selector || VENDOO_SELECTORS.category,
                              value,
                          });
                      } else {
                          await fillMarketplaceCategory(marketplace, { category_path: value });
                      }
                      continue;
                  }
                  if (fieldKey === 'size' && marketplace !== 'general' && marketplace !== 'unknown') {
                      await fillMarketplaceSize(marketplace, { size: value }, item.selector);
                      continue;
                  }
                  const el = await waitForPatchControl(item);
                  if (!el) {
                      recordFill({
                          id: item.id,
                          field: fieldName,
                          status: 'not_found',
                          reason: 'Element not found',
                          selector: item.selector || '',
                          value,
                      });
                      continue;
                  }
                  if (shouldFillAsDropdown(el, fieldName) || isMultiChipField(fieldName)) {
                      await fillDropdownField(el, value, fieldName, false, isMultiChipField(fieldName));
                  } else {
                      await fillTextFieldByElement(el, value, fieldName);
                  }
              }
              currentPatchEntryId = '';
              reverifyPatchedFields(group);
              const log = finishFillLog({ skipUnmapped: true });
              allEntries.push(...log.entries);
          }
          await closeOpenMenus();
          return {
              ok: true,
              fill_log: {
                  marketplace: allEntries[0]?.marketplace || 'general',
                  summary: summarizeFillLog(allEntries),
                  entries: allEntries,
              },
          };
      } catch (err) {
          currentPatchEntryId = '';
          error(`Leftover fill error: ${err.message}`);
          allEntries.push({
              marketplace: currentFillMarketplace,
              field: 'form',
              status: 'failed',
              reason: err.message,
              selector: '',
              value_preview: '',
          });
          return {
              ok: false,
              error: err.message,
              fill_log: {
                  marketplace: allEntries[0]?.marketplace || 'general',
                  summary: summarizeFillLog(allEntries),
                  entries: allEntries,
              },
          };
      }
  }

  // ============================================
  // INIT
  // ============================================

  function init() {
      log(`✓ Content script loaded on ${window.location.hostname}`);
      
      runtimeListener = (msg, sender, sendResponse) => {
          if (msg.type === 'PING') {
              sendResponse({ ok: true, platform: PLATFORM, contentScriptVersion: CONTENT_SCRIPT_VERSION });
              return true;
          }

          if (msg.type === 'UPLOAD_PHOTOS') {
              uploadStudioPhotos(msg.photos || [], msg.studio_url, msg.job_id)
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'FILL_GENERAL') {
              currentRegistrySelectors = msg.registry_selectors || {};
              fillMainForm(msg.data)
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'SAVE_GENERAL') {
              saveGeneralForm()
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'AUDIT_GENERAL') {
              auditGeneralForm(msg.data)
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'FILL_MARKETPLACE') {
              currentRegistrySelectors = msg.registry_selectors || {};
              fillMarketplaceForm(msg.data, msg.platform)
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'SAVE_MARKETPLACE') {
              saveGeneralForm()
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'AUDIT_MARKETPLACE') {
              auditMarketplaceForm(msg.data, msg.platform)
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'FILL_FIELDS') {
              fillSelectedFields(msg.fields || [])
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'GET_VENDOO_ITEM') {
              try {
                  sendResponse(scrapeVendooItem());
              } catch (err) {
                  sendResponse({ ok: false, error: err.message });
              }
              return true;
          }

          if (msg.type === 'CLEAR_GENERAL') {
              clearGeneralForm()
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'CLEAR_MARKETPLACE') {
              clearMarketplaceForm(msg.platform)
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'GET_PAGE_STATE') {
              sendResponse({
                  ok: true,
                  url: window.location.href,
                  hasSaveButton: !!document.querySelector('[data-testid="save-item-button"]'),
                  itemId: extractItemId(),
              });
              return true;
          }
          
          if (msg.type === 'START_FILL' || msg.type.startsWith('START_')) {
              let platform = msg.platform || 'VENDOO';
              if (msg.type === 'START_EBAY') platform = 'EBAY';
              if (msg.type === 'START_ETSY') platform = 'ETSY';
              if (msg.type === 'START_POSHMARK') platform = 'POSHMARK';
              if (msg.type === 'START_MERCARI') platform = 'MERCARI';
              if (msg.type === 'START_DEPOP') platform = 'DEPOP';
              
              log(`Received START_FILL for ${platform}`);
              
              setTimeout(() => {
                  fillForm(msg.data, platform);
              }, 100);

              sendResponse({ ok: true });
              return true;
          }
      };
      chrome.runtime.onMessage.addListener(runtimeListener);
  }

  if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
  } else {
      init();
  }

})();
