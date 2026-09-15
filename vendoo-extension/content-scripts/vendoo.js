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
    const summary = { filled: 0, skipped: 0, not_found: 0, invalid: 0, failed: 0, uncertain: 0, new: 0 };
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
    'return payed by': 'return paid by',
    'starting price': 'starting price',
  };

  const ACCOUNT_SETTING_FIELDS = new Set([
    'allow best offer',
    'auto accept',
    'minimum offer',
    'minimum price',
    'primary store category',
    'secondary store category',
    'personalization instructions',
    'exclude sku from listing',
    'no brand not sure',
    'worldwide shipping',
    'custom property',
    'other info',
    'size grouping',
    'accept returns',
    'return within',
    'return refund method',
    'return paid by',
    'returns',
    'starting price',
    'payment method',
  ]);

  function isAccountSettingField(value) {
    return ACCOUNT_SETTING_FIELDS.has(normalizeFieldKey(value));
  }

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
    if (/listings|generalDetails|category/i.test(parentId)) return true;
    const root = fieldControlRoot(el);
    return Boolean(root && root.querySelector('[id^="listings."], [name^="listings."], [id^="generalDetails"]'));
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
      if (marketplaceFieldNode(el, marketplace)) return true;
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
      if (!isEnabledField(el)) continue;

      const label = fieldLabelForControl(el);
      const key = normalizeFieldKey(label);
      if (!key || seen.has(key) || controlAlreadyLogged(el, key)) continue;
      if (isAccountSettingField(key) || isAccountSettingField(label)) continue;
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
    log(`filled ${summary.filled} · skipped ${summary.skipped} · not found ${summary.not_found} · invalid ${summary.invalid} · failed ${summary.failed} · uncertain ${summary.uncertain} · new ${summary.new}`);
    fillLedger
      .filter((entry) => entry.status === 'invalid' || entry.status === 'failed' || entry.status === 'not_found')
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

  // Live dropdown options learned by the schema probe, keyed by marketplace and
  // normalized field label. Set from FILL_GENERAL/FILL_MARKETPLACE.
  let currentRegistryOptions = {};

  function knownOptionsFor(marketplace, fieldName) {
      const name = String(fieldName || '').trim();
      if (!name) return [];
      const keys = uniqueStrings([normalizeFieldKey(name), name.toLowerCase()]);
      const buckets = [currentRegistryOptions[marketplace], currentRegistryOptions.general];
      for (const bucket of buckets) {
          if (!bucket) continue;
          for (const key of keys) {
              const options = bucket[key];
              if (Array.isArray(options) && options.length) return options;
          }
      }
      return [];
  }

  // Snaps a value onto a currently-offered option. Returns undefined when the
  // registry has nothing to say, so the caller keeps its own result.
  function coerceToKnownOption(marketplace, fieldName, value) {
      const raw = String(value == null ? '' : value).trim();
      if (!raw) return undefined;
      const options = knownOptionsFor(marketplace, fieldName);
      if (!options.length) return undefined;
      const exact = options.find((option) => optionMatchesValue(option, raw, true));
      if (exact) return exact;
      const fuzzy = options.find((option) => optionMatchesValue(option, raw, false));
      return fuzzy || undefined;
  }

  function mapPatchValue(marketplace, fieldName, value) {
      if (value == null || String(value).trim() === '') return value;
      const mp = mappingMarketplace(marketplace);
      const mapped = mapPatchValueStatic(marketplace, fieldName, value);
      // A null from the static maps means "this value has no option here"; that
      // decision stands. Otherwise let the live option set repair stale output.
      if (mapped === null) return mapped;

      const corrected = coerceToKnownOption(mp, fieldName, mapped)
          ?? coerceToKnownOption(mp, fieldName, value);
      if (corrected === undefined) {
          // Known option set, no match: the fill is going to fail. Say so now so
          // the cause is visible, rather than guessing at a near-miss.
          if (knownOptionsFor(mp, fieldName).length) {
              warn(`${fieldName}: "${mapped}" is not a current ${mp} option`);
          }
          return mapped;
      }
      if (corrected !== String(mapped == null ? '' : mapped).trim()) {
          log(`  [registry] ${fieldName}: "${mapped}" → "${corrected}" (live option)`);
      }
      return corrected;
  }

  function mapPatchValueStatic(marketplace, fieldName, value) {
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
      if (mp === 'etsy') {
          const etsyPatchFields = {
              'clothing style': 'clothingStyle',
              'sleeve length': 'sleeveLength',
              'neckline': 'neckline',
              'graphic': 'graphic',
              'occasion': 'occasion',
              'holiday': 'holiday',
              'sustainability': 'sustainability',
              'fabric pattern': 'fabricPattern',
              'pattern': 'fabricPattern',
          };
          const etsyField = etsyPatchFields[key];
          if (etsyField) {
              const mapped = normalizeEtsyCategorySpecificValue(etsyField, value);
              return mapped == null ? null : mapped;
          }
      }
      if (mp === 'ebay' && key === 'type') {
          return normalizeEbaySpecificValue('type', value);
      }
      if (mp === 'ebay' && key === 'year manufactured') {
          return normalizeEbaySpecificValue('yearManufactured', value);
      }
      if (mp === 'ebay' && isDoesNotApplyValue(value) && key !== 'year manufactured') {
          return 'Does Not Apply';
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
      sleeveLength: [
          ['sleeveless', 'Sleeveless'],
          ['three quarter', '3/4 sleeve'],
          ['3/4', '3/4 sleeve'],
          ['half', 'Half sleeve'],
          ['short', 'Short sleeve'],
          ['long', 'Long sleeve']
      ],
      neckline: [
          ['henley', 'Henley'],
          ['v neck', 'V-neck'],
          ['crew', 'Crew']
      ],
      graphic: [
          ['fantasy', 'Fantasy & Sci Fi'],
          ['sci fi', 'Fantasy & Sci Fi'],
          ['food', 'Food & drink'],
          ['drink', 'Food & drink'],
          ['music', 'Music'],
          ['nautical', 'Nautical'],
          ['patriotic', 'Patriotic & flags'],
          ['flag', 'Patriotic & flags'],
          ['religious', 'Religious'],
          ['science', 'Science & tech'],
          ['sports', 'Sports & fitness'],
          ['fitness', 'Sports & fitness'],
          ['racing', 'Sports & fitness'],
          ['nhra', 'Sports & fitness'],
          ['drag', 'Sports & fitness'],
          ['travel', 'Travel & transportation'],
          ['cars', 'Travel & transportation'],
          ['car', 'Travel & transportation'],
          ['plants', 'Plants & trees'],
          ['trees', 'Plants & trees'],
          ['stars', 'Stars & celestial'],
          ['celestial', 'Stars & celestial'],
          ['animal', 'Animal'],
          ['anime', 'Anime & cartoon'],
          ['cartoon', 'Anime & cartoon'],
          ['comics', 'Comics & manga'],
          ['manga', 'Comics & manga'],
          ['superhero', 'Superhero'],
          ['video game', 'Video game'],
          ['lgbtq', 'LGBTQ pride'],
          ['pride', 'LGBTQ pride'],
          ['abstract', 'Abstract & geometric'],
          ['geometric', 'Abstract & geometric'],
          ['flowers', 'Flowers'],
          ['horror', 'Horror & gothic'],
          ['humorous', 'Humorous saying'],
          ['funny', 'Humorous saying'],
          ['inspirational', 'Inspirational saying'],
          ['literary', 'Literary'],
          ['geography', 'Geography & locale'],
          ['military', 'Military & historical'],
          ['historical', 'Military & historical'],
          ['protest', 'Protest'],
          ['surf', 'Surf & skate'],
          ['skate', 'Surf & skate'],
          ['politics', 'Politics & elections'],
          ['phrase', 'Phrase & saying'],
          ['logo', 'Brand & logo'],
          ['brand', 'Brand & logo'],
          ['movie', 'Movie']
      ],
      fabricPattern: [
          ['camouflage', 'Camouflage'],
          ['camo', 'Camouflage'],
          ['floral', 'Floral'],
          ['geometric', 'Geometric'],
          ['plaid', 'Plaid'],
          ['polka', 'Polka dot'],
          ['solid', 'Solid'],
          ['striped', 'Striped'],
          ['stripe', 'Striped'],
          ['tie dye', 'Tie dye'],
          ['ombre', 'Ombré'],
          ['ombré', 'Ombré'],
          ['check', 'Check'],
          ['graphic', 'Solid']
      ],
      holiday: [
          ['christmas', 'Christmas'],
          ['halloween', 'Halloween'],
          ['easter', 'Easter'],
          ['hanukkah', 'Hanukkah'],
          ['thanksgiving', 'Thanksgiving'],
          ['valentine', "Valentine's Day"],
          ['father', "Father's Day"],
          ['independence', 'Independence Day'],
          ['patrick', "St Patrick's Day"],
          ['kwanzaa', 'Kwanzaa'],
          ['veterans', 'Veterans Day'],
          ['diwali', 'Diwali'],
          ['holi', 'Holi'],
          ['eid', 'Eid'],
          ['cinco', 'Cinco de Mayo']
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
      const words = new Set(normalizedValue.split(/[^a-z0-9]+/).filter(Boolean));
      const ranked = mappings
          .map(([needle, mappedValue]) => [normalizeText(needle), mappedValue])
          .filter(([needle]) => needle)
          .sort((left, right) => right[0].length - left[0].length);

      for (const [needle, mappedValue] of ranked) {
          if (normalizedValue === needle) return mappedValue;
          const needleWords = needle.split(/[^a-z0-9]+/).filter(Boolean);
          if (needleWords.length > 1) {
              if (normalizedValue.includes(needle)) return mappedValue;
          } else if (words.has(needle)) {
              return mappedValue;
          }
      }

      return rawValue;
  }

  function normalizeEtsyWhenMade(rawValue) {
      if (!rawValue) return rawValue;

      const value = String(rawValue).trim();
      const normalizedValue = normalizeText(value);
          const unknownTokens = ['unknown', 'does not apply', 'n/a', 'not sure', 'not shown'];
          if (unknownTokens.some((token) => normalizedValue === token || normalizedValue.includes(token))) {
              return '';
          }
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
          ['before 1700', 'Before 1700 (Vintage)']
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

  const ETSY_CATEGORY_OPTIONS = {
      clothingStyle: ['Minimalist', 'Boho & hippie', 'Gothic', 'Steampunk', 'Athletic', 'Military', 'Preppy', 'Rave', 'Rocker', 'Streetwear', 'Utility', 'Western & cowboy', 'Harajuku', 'Lolita', 'Mod', 'Pin-up & rockabilly', 'Menswear'],
      sleeveLength: ['Short sleeve', 'Half sleeve', '3/4 sleeve', 'Long sleeve', 'Sleeveless'],
      neckline: ['Crew', 'Henley', 'V-neck'],
      graphic: ['Fantasy & Sci Fi', 'Food & drink', 'Music', 'Nautical', 'Patriotic & flags', 'Religious', 'Science & tech', 'Sports & fitness', 'Travel & transportation', 'Plants & trees', 'Stars & celestial', 'Animal', 'Anime & cartoon', 'Comics & manga', 'Superhero', 'Video game', 'LGBTQ pride', 'Abstract & geometric', 'Fitspiration', 'Flowers', 'Horror & gothic', 'Humorous saying', 'Inspirational saying', 'Literary', 'Geography & locale', 'Military & historical', 'Protest', 'Surf & skate', 'Politics & elections', 'Phrase & saying', 'Brand & logo', 'Movie', 'TV', 'Bollywood'],
      occasion: ['Anniversary', 'Baby shower', 'Bachelor party', 'Birthday', 'Engagement', 'Graduation', 'Divorce & breakup', 'Retirement', 'Wedding', 'LGBTQ pride'],
      holiday: ['Christmas', 'Cinco de Mayo', 'Easter', "Father's Day", 'Halloween', 'Hanukkah', 'Independence Day', 'Kwanzaa', "St Patrick's Day", 'Thanksgiving', "Valentine's Day", 'Veterans Day', 'Diwali', 'Holi', 'Eid'],
      sustainability: ['Hemp', 'Linen', 'Organic cotton', 'Recycled polyester'],
      fabricPattern: ['Camouflage', 'Check', 'Floral', 'Geometric', 'Plaid', 'Polka dot', 'Solid', 'Striped', 'Tie dye', 'Ombré']
  };

  function etsyCategoryValueKey(fieldName) {
      if (fieldName === 'pattern') return 'fabricPattern';
      return fieldName;
  }

  function normalizeEtsyCategorySpecificValue(fieldName, rawValue) {
      if (rawValue == null || rawValue === '') return rawValue;

      const key = etsyCategoryValueKey(fieldName);
      const raw = Array.isArray(rawValue) ? rawValue.join(', ') : String(rawValue).trim();
      if (!raw) return raw;

      const options = ETSY_CATEGORY_OPTIONS[key];
      if (options) {
          const exact = options.find((opt) => normalizeText(opt) === normalizeText(raw));
          if (exact) return exact;
          const fuzzy = options.find((opt) => optionMatchesValue(opt, raw, false));
          if (fuzzy) return fuzzy;
      }

      const mappings = ETSY_CATEGORY_VALUE_MAPS[key] || ETSY_CATEGORY_VALUE_MAPS[fieldName];
      if (mappings) {
          const mapped = mapByIncludes(raw, mappings);
          if (mapped && mapped !== raw) {
              if (!options) return mapped;
              const mappedExact = options.find((opt) => normalizeText(opt) === normalizeText(mapped));
              if (mappedExact) return mappedExact;
              const mappedFuzzy = options.find((opt) => optionMatchesValue(opt, mapped, false));
              if (mappedFuzzy) return mappedFuzzy;
              return mapped;
          }
      }

      const skipUnmapped = {
          occasion: ['everyday', 'casual', 'n/a', 'does not apply', 'none'],
          graphic: ['graphic', 'n/a', 'does not apply', 'none'],
          holiday: ['n/a', 'does not apply', 'none'],
          sustainability: ['n/a', 'does not apply', 'none', 'cotton']
      };
      const skipValues = skipUnmapped[key];
      if (skipValues && skipValues.includes(normalizeText(raw))) {
          return null;
      }

      return raw;
  }

  function isVisibleElement(el) {
      return Boolean(el) && (el.offsetParent !== null || el.getClientRects().length > 0);
  }

  function isEffectivelyVisible(el) {
      if (!isVisibleElement(el)) return false;
      if (el.closest?.('[aria-hidden="true"], [hidden], template')) return false;
      const style = window.getComputedStyle(el);
      if (!style || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) === 0) {
          return false;
      }
      const rect = el.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) return false;
      // Inactive Vendoo marketplace panels stay mounted off-screen or behind the
      // active sheet; treat those as not active so we still click the nav tab.
      if (rect.bottom < 0 || rect.top > (window.innerHeight || 0) + 80) return false;
      if (rect.right < 0 || rect.left > (window.innerWidth || 0) + 80) return false;
      return true;
  }

  function isAttachedElement(el) {
      return Boolean(el) && el.isConnected !== false;
  }

  function fieldControlRoot(el) {
      if (!el || !el.closest) return el && el.parentElement ? el.parentElement : null;
      return el.closest(
          '.MuiFormControl-root, .MuiAutocomplete-root, .MuiSelect-root, [class*="MuiFormControl-root"], [class*="MuiAutocomplete-root"], [class*="MuiSelect-root"]'
      ) || el.parentElement;
  }

  function marketplaceFieldNode(el, marketplace) {
      if (!el) return null;
      const prefix = `listings.${marketplace}.`;
      if (String(el.id || '').startsWith(prefix) || String(el.name || '').startsWith(prefix)) return el;
      const root = fieldControlRoot(el);
      if (!root || root === document.body) return null;
      return root.querySelector(`[id^="${prefix}"], [name^="${prefix}"]`);
  }

  function visibleDropdownControl(el) {
      if (!el) return null;
      if (isVisibleElement(el) && (
          el.matches?.('input:not([type="hidden"]), textarea, select, [role="combobox"], [role="button"]') ||
          isDropdownLike(el)
      )) {
          return el;
      }
      const root = fieldControlRoot(el);
      if (!root) return null;
      const candidates = Array.from(root.querySelectorAll(
          'input:not([type="hidden"]), textarea, select, [role="combobox"], [role="button"][aria-haspopup], .MuiSelect-select, [class*="MuiSelect-select"]'
      ));
      return candidates.find((candidate) => candidate !== el && isVisibleElement(candidate)) || null;
  }

  function specificFieldToken(idOrName) {
      const afterDot = String(idOrName || '').split('.').pop() || '';
      return normalizeText(afterDot.replace(/^[0-9a-f]{8,}_/i, '').replace(/^\d+_/, ''));
  }

  function controlFieldToken(el) {
      if (!el) return '';
      const sources = [el.id, el.name];
      const root = fieldControlRoot(el);
      if (root && root !== document.body) {
          for (const node of root.querySelectorAll('[id^="listings."], [name^="listings."]')) {
              sources.push(node.id, node.name);
          }
      }
      for (const source of sources) {
          const token = specificFieldToken(source);
          if (token && !/^listings /.test(token) && token !== 'category specifics') return token;
      }
      return '';
  }

  function hasPrefixInControl(input, prefix) {
      if (!input) return false;
      if (String(input.id || '').startsWith(prefix) || String(input.name || '').startsWith(prefix)) return true;
      const root = fieldControlRoot(input);
      if (!root || root === document.body) return false;
      return Boolean(root.querySelector(`[id^="${prefix}"], [name^="${prefix}"]`));
  }

  function isEtsyCategorySpecificInput(input) {
      return hasPrefixInControl(input, 'listings.etsy.categorySpecifics.');
  }

  function etsySpecificFieldToken(idOrName) {
      return specificFieldToken(idOrName);
  }

  function collectEtsyCategoryInputs(requireVisible = true) {
      const usable = requireVisible ? isVisibleElement : isAttachedElement;
      return Array.from(document.querySelectorAll(
          'input[id^="listings.etsy.categorySpecifics."], select[id^="listings.etsy.categorySpecifics."], [id^="listings.etsy.categorySpecifics."][role="combobox"], input[name^="listings.etsy.categorySpecifics."], select[name^="listings.etsy.categorySpecifics."]'
      )).filter(usable);
  }

  function findEtsyCategoryInput(fieldName, labelPatterns, inputs) {
      const wants = uniqueStrings([
          normalizeText(fieldName),
          ...(labelPatterns || []).map(normalizeText),
      ]).filter(Boolean);
      const compact = (value) => value.replace(/\s+/g, '');
      const pool = inputs && inputs.length ? inputs : collectEtsyCategoryInputs();

      for (const input of pool) {
          const token = etsySpecificFieldToken(input.id) || etsySpecificFieldToken(input.name);
          if (!token) continue;
          if (wants.some((want) => token === want || compact(token) === compact(want))) return input;
      }

      for (const label of [fieldName, ...(labelPatterns || [])]) {
          const exact = findInputByExactLabel(label, isEtsyCategorySpecificInput);
          if (exact) return exact;
      }

      return findInputByLabelPatterns(labelPatterns || [fieldName], isEtsyCategorySpecificInput) ||
          findInputByContext(pool, labelPatterns || [fieldName]);
  }

  function isEbayCategorySpecificInput(input) {
      return hasPrefixInControl(input, 'listings.ebay.categorySpecifics.');
  }

  function collectEbayCategoryInputs(requireVisible = true) {
      const nodes = Array.from(document.querySelectorAll(
          '[id^="listings.ebay.categorySpecifics."], [name^="listings.ebay.categorySpecifics."]'
      ));
      const seen = new Set();
      const out = [];
      for (const node of nodes) {
          const control = visibleDropdownControl(node) || (!requireVisible && isAttachedElement(node) ? node : null);
          if (!control || seen.has(control)) continue;
          if (requireVisible && !isVisibleElement(control) && !isDropdownLike(control)) continue;
          seen.add(control);
          out.push(control);
      }
      return out;
  }

  function findEbaySpecificInput(fieldName, inputs) {
      const want = normalizeText(fieldName);
      const compact = (value) => String(value || '').replace(/\s+/g, '');
      const pool = inputs && inputs.length ? inputs : collectEbayCategoryInputs();
      for (const input of pool) {
          const token = controlFieldToken(input) || specificFieldToken(input.id) || specificFieldToken(input.name);
          if (token && (token === want || compact(token) === compact(want))) return input;
      }
      return findInputByExactLabel(fieldName, isEbayCategorySpecificInput);
  }

  function isDepopSpecificInput(input) {
      if (!input) return false;
      const id = String(input.id || '');
      const name = String(input.name || '');
      return id.startsWith('listings.depop.') || name.startsWith('listings.depop.');
  }

  function findInputsNearLabel(labelEl, filterFn = () => true) {
      if (!labelEl) return [];

      const resolveCandidate = (node) => {
          if (!node) return null;
          const visible = visibleDropdownControl(node);
          const control = (visible && isVisibleElement(visible)) ? visible : (isVisibleElement(node) ? node : null);
          if (!control) return null;
          if (filterFn(control) || filterFn(node)) return control;
          return null;
      };

      const forId = labelEl.getAttribute?.('for');
      if (forId) {
          const resolved = resolveCandidate(document.getElementById(forId));
          if (resolved) return [resolved];
      }

      const roots = [];
      const formRoot = fieldControlRoot(labelEl);
      if (formRoot && formRoot !== document.body) roots.push(formRoot);
      if (labelEl.parentElement && !roots.includes(labelEl.parentElement)) roots.push(labelEl.parentElement);

      for (const container of roots) {
          const matches = [];
          for (const node of container.querySelectorAll(
              'input, textarea, select, [role="combobox"], [role="button"][aria-haspopup], .MuiSelect-select'
          )) {
              const resolved = resolveCandidate(node);
              if (resolved && !matches.includes(resolved)) matches.push(resolved);
          }
          if (matches.length > 0) return matches;
      }

      let container = labelEl.parentElement;
      for (let depth = 0; depth < 4 && container && container !== document.body; depth++) {
          if (container.querySelectorAll('label, [class*="MuiFormLabel"]').length > 1) break;
          const matches = [];
          for (const node of container.querySelectorAll('input, textarea, select, [role="combobox"]')) {
              const resolved = resolveCandidate(node);
              if (resolved && !matches.includes(resolved)) matches.push(resolved);
          }
          if (matches.length > 0) return matches;
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
      const compact = (value) => String(value || '').replace(/\s+/g, '');

      const labels = Array.from(document.querySelectorAll(
          'label, legend, div[class*="Label"], span[class*="Label"], span[class*="label"], div[class*="label"], h3, h4, p, span[class*="title"], div[class*="title"]'
      ));

      for (const labelEl of labels) {
          if (!isVisibleElement(labelEl)) continue;
          const text = normalizeText(labelEl.innerText || labelEl.textContent || '').replace(/\s*\*$/, '');
          if (text !== want) continue;
          const inputs = findInputsNearLabel(labelEl, filterFn);
          const exact = inputs.find((input) => {
              const token = controlFieldToken(input);
              return token === want || compact(token) === compact(want);
          });
          if (exact) return exact;
          if (inputs.length === 1) return inputs[0];
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
      return (input) => Boolean(marketplaceFieldNode(input, marketplace));
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

  function chipFieldRoot(el) {
      if (!el) return null;
      return el.closest?.('.MuiAutocomplete-root, .MuiFormControl-root, [class*="MuiAutocomplete"]') || el.parentElement || null;
  }

  function listedChipValues(el) {
      const root = chipFieldRoot(el);
      if (!root) return [];
      return uniqueStrings(Array.from(root.querySelectorAll('.MuiChip-label')).map((chip) =>
          (chip.textContent || '').replace(/\u00a0/g, ' ').trim()
      ));
  }

  function readPersistedControlValue(el) {
      if (!el) return '';
      const type = String(el.getAttribute?.('type') || el.type || '').toLowerCase();
      const role = String(el.getAttribute?.('role') || '').toLowerCase();
      if (type === 'checkbox' || type === 'radio' || role === 'checkbox' || role === 'switch') {
          const aria = el.getAttribute?.('aria-checked');
          if (aria === 'true') return true;
          if (aria === 'false') return false;
          return Boolean(el.checked);
      }
      const chips = listedChipValues(el);
      if (chips.length > 1) return chips;
      if (chips.length === 1 && !String(el.value || '').trim()) return chips[0];
      if ('value' in el && el.value != null && String(el.value).trim()) return String(el.value).trim();
      const text = (el.innerText || el.textContent || '').trim();
      if (text && fieldLooksFilled(el)) return chips.length === 1 ? chips[0] : text;
      return chips.length === 1 ? chips[0] : '';
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
      return !/^(select|choose|size|type|department|primary color|secondary color|condition|brand|shipping label)\b/i.test(value);
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

  function normalizeComparableText(text) {
      return String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function fieldValuesEqual(current, intended) {
      const got = normalizeComparableText(current);
      const want = normalizeComparableText(intended);
      if (!got || !want) return false;
      if (got === want) return true;
      if (normalizeOptionValue(got) === normalizeOptionValue(want)) return true;
      const cleanGot = got.replace(/[$,]/g, '');
      const cleanWant = want.replace(/[$,]/g, '');
      if (/^-?\d+(\.\d+)?$/.test(cleanGot) && /^-?\d+(\.\d+)?$/.test(cleanWant)) {
          return Number(cleanGot) === Number(cleanWant);
      }
      return false;
  }

  function chipsMatchValues(el, values) {
      const want = (Array.isArray(values) ? values : [values])
          .map(normalizeOptionValue)
          .filter(Boolean)
          .sort();
      const have = listedChipValues(el).map(normalizeOptionValue).filter(Boolean).sort();
      if (!want.length || have.length !== want.length) return false;
      return have.every((chip, index) => chip === want[index]);
  }

  function recordAlreadySet(fieldName, el, selectorText, value) {
      const shown = displayedFieldValue(el) || value;
      log(`  ✓ ${fieldName} already set: "${shown}"`);
      recordFill({
          field: fieldName,
          status: 'filled',
          reason: 'Already set',
          selector: selectorFor(el, selectorText),
          value,
      });
      return { status: 'filled' };
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

  const DROPDOWN_FIELD_HINT = /\b(condition|brand|color|size|category|shipping|occasion|style|department|type|who made|when made|source|scale|material|pattern|features|sleeve|neckline|fit|rise|inseam|wash|closure|vintage|theme|season|waist|strap|year|return|refund)\b/i;

  function shouldFillAsDropdown(el, fieldName) {
      return isDropdownLike(el) || DROPDOWN_FIELD_HINT.test(String(fieldName || ''));
  }

  function isChipControl(el) {
      if (!el) return false;
      const root = el.closest?.('.MuiAutocomplete-root, [class*="MuiAutocomplete"]');
      if (!root) return false;
      if (el.getAttribute('aria-multiselectable') === 'true') return true;
      return Boolean(root.querySelector('.MuiChip-root, [class*="MuiChip"], [class*="chip"]'));
  }

  function isMultiChipField(fieldName, el) {
      const name = String(fieldName || '');
      if (/\b(tags?|labels?)\b/i.test(name)) return true;
      if (/\b(materials?|features?|accents?)\b/i.test(name)) return true;
      return Boolean(el && isChipControl(el) && /\b(seasons?|themes?|occasions?)\b/i.test(name));
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

  const MAX_CAPTURED_OPTIONS = 200;

  // Search-driven pickers hold thousands of entries and only populate as you
  // type, so capturing them yields a misleading partial set.
  const OPTION_CAPTURE_SKIP = /\b(category|tags?|keywords?|search)\b/i;

  // Reads a field's full option set so Studio can learn what Vendoo currently
  // offers, instead of relying on hardcoded value maps that drift.
  async function readLiveFieldOptions(el, fieldName) {
      if (!el) return { options: [], source: 'not-applicable' };

      if (el instanceof HTMLSelectElement) {
          const native = uniqueStrings(
              Array.from(el.options)
                  .map((opt) => (opt.textContent || '').trim())
                  .filter(Boolean)
          );
          return { options: native.slice(0, MAX_CAPTURED_OPTIONS), source: 'native-select' };
      }

      if (!isDropdownLike(el)) return { options: [], source: 'not-applicable' };
      if (!isEnabledField(el)) return { options: [], source: 'disabled' };
      if (OPTION_CAPTURE_SKIP.test(String(fieldName || ''))) {
          return { options: [], source: 'skipped' };
      }

      let options = [];
      try {
          el.scrollIntoView({ block: 'center', behavior: 'instant' });
          for (let attempt = 0; attempt < 2 && options.length === 0; attempt += 1) {
              await clickRightEdge(el);
              await sleep(CONFIG.SLEEP_LONG);
              options = uniqueStrings(
                  listOpenDropdownOptions().map((option) => option.text).filter(Boolean)
              );
          }
      } catch (err) {
          warn(`Option capture failed for ${fieldName}: ${err.message}`);
      } finally {
          await closeOpenMenus();
      }

      return {
          options: options.slice(0, MAX_CAPTURED_OPTIONS),
          source: options.length ? 'live-dropdown' : 'unavailable',
      };
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
      if (isMulti && fieldHasChip(el, value)) {
          return { ok: true, method: 'already_present' };
      }

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

      if (fieldValuesEqual(displayedFieldValue(el), value)) {
          return recordAlreadySet(fieldName, el, selectorText, value);
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

      const chipField = isMulti || isMultiChipField(fieldName, el);
      const values = chipField ? splitChipValues(value) : [value];
      if (chipField && values.length === 0) {
          recordFill({ field: fieldName, status: 'skipped', reason: 'No value in listing', selector: selectorText, value });
          return { status: 'skipped' };
      }

      if (chipField) {
          const filledValue = values.length > 1 ? values : values[0];
          if (chipsMatchValues(el, values)) {
              return recordAlreadySet(fieldName, el, selectorText, filledValue);
          }
          log(`Filling ${fieldName}...`);
          const replaceChips = values.length > 1 || normalizeFieldKey(fieldName) === 'tags';
          if (replaceChips) await clearChipContainer(el);
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
            status: 'invalid',
            reason: 'Option not found and value did not stick',
            selector: selectorFor(el, selectorText),
            value: filledValue,
          });
          return { status: 'invalid' };
      }

      if (optionMatchesValue(displayedFieldValue(el), value, false)) {
          return recordAlreadySet(fieldName, el, selectorText, value);
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
        status: 'invalid',
        reason: 'Option not found and value did not stick',
        selector: selectorFor(el, selectorText),
        value,
      });
      return { status: 'invalid' };
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

  function escapeRegExp(value) {
      return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function categoryOptionLeaf(option) {
      const raw = String(option?.text || option?.lower || '');
      const parts = raw.split(/[>‣▸▶]/).map((part) => normalizeText(part)).filter(Boolean);
      return parts[parts.length - 1] || normalizeText(raw);
  }

  function scoreCategoryOption(option, segment) {
      const needle = normalizeText(segment);
      const leaf = categoryOptionLeaf(option);
      if (!needle || !option.lower) return 0;
      if (leaf === needle) return 8;
      if (option.lower === needle) return 4;
      const word = new RegExp(`\\b${escapeRegExp(needle)}\\b`);
      if (word.test(leaf)) return 3;
      if (word.test(option.lower)) return 2;
      if (leaf.startsWith(needle) || needle.startsWith(leaf)) return 2;
      if (option.lower.startsWith(needle) || needle.startsWith(option.lower)) return 1;
      if (leaf.includes(needle) || needle.includes(leaf)) return 1;
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
      blouse: ['Blouse', 'Blouses'],
      blouses: ['Blouse', 'Blouses'],
      tees: ['Tees - Short Sleeve', 'Tees - Long Sleeve'],
      'tees - short sleeve': ['Tees - Short Sleeve'],
      'tees - long sleeve': ['Tees - Long Sleeve'],
      sweatshirt: ['Sweatshirts', 'Sweats & Hoodies', 'Sweaters'],
      sweatshirts: ['Sweatshirts', 'Sweats & Hoodies', 'Sweaters'],
      hoodie: ['Hoodies', 'Sweats & Hoodies'],
      hoodies: ['Hoodies', 'Sweats & Hoodies'],
      sweater: ['Sweaters', 'Sweatshirts'],
      sweaters: ['Sweaters', 'Sweatshirts'],
  };

  function categoryHaystack(data, categoryPath) {
      const department = data.department || data.ebay_specifics?.department || '';
      const type = data.ebay_specifics?.type || data.type || '';
      const sleeve = data.sleeveLength || data.ebay_specifics?.sleeveLength || '';
      return `${categoryPath} ${department} ${type} ${sleeve} ${data.title || ''} ${data.description || ''}`;
  }

  function blouseVsTeeSignals(hayLower) {
      const isTee = /t-?shirts?|\btees?\b|graphic tee/.test(hayLower);
      const isBlouse = (
          /\bblouses?\b/.test(hayLower)
          || /button[\s-]*(up|front|down)/.test(hayLower)
      ) && !isTee;
      return { isTee, isBlouse };
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
      const { isTee, isBlouse } = blouseVsTeeSignals(hayLower);
      const longSleeve = /long\s*sleeve/.test(hayLower);
      const teeLeaf = longSleeve ? 'Tees - Long Sleeve' : 'Tees - Short Sleeve';
      if (isMen && isTee) return `Men > Shirts > ${teeLeaf}`;
      if (isWomen && isTee) return `Women > Tops > ${teeLeaf}`;
      if (isWomen && isBlouse) return 'Women > Tops > Blouses';
      return categoryPath;
  }

  function normalizeVendooCategoryPath(data) {
      if (data.marketplace_categories) return data.category_path || '';
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
      const query = needles.join(' ');
      const wantsSweat = /\bsweatshirts?\b|\bhoodies?\b|\bsweaters?\b/.test(query);
      const wantsBlouse = /\bblouses?\b/.test(leaf);
      return options
          .map((option) => {
              const shownLeaf = categoryOptionLeaf(option);
              let score = scoreCategoryOption(option, leaf);
              for (const needle of needles.slice(0, -1)) {
                  if (shownLeaf.includes(needle) || option.lower.includes(needle) || needle.includes(option.lower)) {
                      score += 1;
                  }
              }
              if (wantsSweat && /t-?shirts?|\btees?\b/.test(shownLeaf) && !/\bsweatshirts?\b/.test(shownLeaf)) {
                  score -= 5;
              }
              if (wantsBlouse && /t-?shirts?|\btees?\b/.test(shownLeaf)) {
                  score -= 10;
              }
              if (wantsBlouse && shownLeaf === 'blouses') {
                  score += 6;
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

  function readCategoryDisplay(el) {
      if (!el) return '';
      // Vendoo draws separators with CSS; textContent concatenates the spans.
      const parts = Array.from(el.children || [])
          .filter((child) => child.tagName === 'SPAN')
          .map((child) => String(child.textContent || '').trim())
          .filter(Boolean);
      const shown = parts.length ? parts.join(' > ') : String(el.innerText || el.textContent || '').trim();
      return /^(category|click to select|select category)$/i.test(shown) ? '' : normalizeCategoryDisplay(shown);
  }

  function categoryDisplayMatches(shown, path) {
      const shownNorm = normalizeText(String(shown || '').replace(/[▸▶‣\*]/g, ' '));
      const segs = String(path || '').split('>').map((part) => normalizeText(part)).filter(Boolean);
      if (!segs.length || !shownNorm) return false;
      const shownParts = String(shown || '')
          .split(/[>‣▸▶]/)
          .map((part) => normalizeText(part.replace(/^category$/i, '')))
          .filter(Boolean);
      const shownLeaf = shownParts[shownParts.length - 1] || shownNorm;
      const wantLeaf = segs[segs.length - 1];
      const leafAliases = categorySegmentNames(wantLeaf).map((name) => normalizeText(name));
      const hayHas = (seg) => {
          const token = normalizeText(seg);
          if (!token) return false;
          if (shownNorm === token || shownParts.includes(token)) return true;
          if (shownNorm.endsWith(token) || shownNorm.startsWith(token)) return true;
          try {
              return new RegExp(`(?:^|[^a-z0-9])${escapeRegExp(token)}(?:[^a-z0-9]|$)`).test(shownNorm);
          } catch (_) {
              return shownNorm.includes(token);
          }
      };
      const leafInHay = !wantLeaf || hayHas(wantLeaf) || leafAliases.includes(shownLeaf)
          || leafAliases.some((alias) => shownLeaf === alias);
      const teeLeaf = /t-?shirts?|\btees?\b/.test(shownLeaf)
          || /t[\s-]?shirts?\s*$/.test(shownNorm)
          || /tees?\s*$/.test(shownNorm)
          || /\bt\s+shirts?\b/.test(shownNorm);
      if (/\bblouses?\b/.test(wantLeaf)) {
          if (teeLeaf) return false;
          // Require a terminal blouse leaf — parent "Tops & Blouses" alone is not enough.
          const withoutParent = shownNorm.replace(/tops\s*&\s*blouses/g, 'X');
          const terminalBlouse = shownLeaf === 'blouse' || shownLeaf === 'blouses'
              || /(?:^|[^a-z0-9])blouses?$/.test(withoutParent);
          if (!terminalBlouse) return false;
      } else if (!leafInHay) {
          return false;
      }
      if (segs.length >= 2) {
          const wantParent = segs[segs.length - 2];
          if (hayHas(wantParent) || shownNorm.includes(wantParent)) return true;
      }
      return segs.every((seg) => hayHas(seg) || leafAliases.includes(seg));
  }

  function queryDeepAll(selector, root) {
      const out = [];
      const visit = (node) => {
          if (!node || !node.querySelectorAll) return;
          try { out.push(...node.querySelectorAll(selector)); } catch (_) {}
          try {
              for (const el of node.querySelectorAll('*')) {
                  if (el.shadowRoot) visit(el.shadowRoot);
              }
          } catch (_) {}
      };
      visit(root || document);
      try {
          for (const iframe of (root || document).querySelectorAll('iframe')) {
              try {
                  const doc = iframe.contentDocument;
                  if (doc) visit(doc);
              } catch (_) {}
          }
      } catch (_) {}
      return out;
  }

  function isGeneralCategoryControl(el) {
      if (!el) return false;
      if (el.id === 'categoryV2') return true;
      const id = String(el.id || '');
      if (/^generalDetails/i.test(id)) return true;
      try {
          if (el.closest && el.closest('#categoryV2, [id^="generalDetails."]')) return true;
      } catch (_) {}
      return false;
  }

  function labelledByText(el) {
      const ids = String(el?.getAttribute?.('aria-labelledby') || '').trim();
      if (!ids) return '';
      return ids.split(/\s+/).map((id) => {
          const node = document.getElementById(id);
          return (node && (node.innerText || node.textContent)) || '';
      }).join(' ');
  }

  function findCategoryControlNearHeading(marketplace) {
      const headings = queryDeepAll('h1, h2, h3, h4, h5, h6, [role="heading"], label, legend, p, span');
      for (const heading of headings) {
          const text = normalizeText(String(heading.innerText || heading.textContent || '').split('\n')[0]);
          if (text !== 'category') continue;
          if (isGeneralCategoryControl(heading)) continue;
          const section = heading.closest
              ? heading.closest(`section, [id*="${marketplace}"], [class*="Field"], [class*="MuiFormControl"], [class*="MuiAutocomplete"], form`)
              : heading.parentElement;
          const scope = section || heading.parentElement;
          if (!scope || !scope.querySelectorAll) continue;
          const candidates = Array.from(scope.querySelectorAll(
              'button, [role="button"], [role="combobox"], [role="category-input"]'
          )).filter((el) => !isGeneralCategoryControl(el));
          const visible = candidates.find((el) => isVisibleElement(el) || isAttachedElement(el));
          if (visible) return visible;
          const sibling = heading.nextElementSibling;
          if (sibling) {
              if (sibling.matches?.('button, [role="button"], [role="combobox"], [role="category-input"]')
                  && !isGeneralCategoryControl(sibling)) {
                  return sibling;
              }
              const nested = sibling.querySelector?.('button, [role="button"], [role="combobox"], [role="category-input"]');
              if (nested && !isGeneralCategoryControl(nested)) return nested;
          }
      }
      return null;
  }

  function nearestMarketplaceCategoryClickable(start) {
      if (!start) return null;
      let sib = start.nextElementSibling;
      while (sib) {
          if (sib.matches?.('button, [role="button"], [role="combobox"], [role="category-input"]')
              && !isGeneralCategoryControl(sib)) {
              return visibleDropdownControl(sib) || sib;
          }
          const nested = sib.querySelector?.('[role="category-input"], [role="combobox"], [aria-haspopup="listbox"], button, [role="button"]');
          if (nested && !isGeneralCategoryControl(nested)) return visibleDropdownControl(nested) || nested;
          sib = sib.nextElementSibling;
      }
      let node = start;
      for (let depth = 0; depth < 10 && node && node !== document.body; depth++) {
          const nodes = node.querySelectorAll
              ? node.querySelectorAll('[role="category-input"], [role="combobox"], [aria-haspopup="listbox"], button, [role="button"]')
              : [];
          const following = Array.from(nodes).filter((el) => {
              if (isGeneralCategoryControl(el) || el === start) return false;
              const label = String(el.getAttribute?.('aria-label') || el.getAttribute?.('title') || '');
              if (/clear|remove|delete/i.test(label)) return false;
              if (start.compareDocumentPosition && (start.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) === 0) {
                  return false;
              }
              return true;
          });
          const named = following.find((el) => {
              const text = normalizeText(el.innerText || el.textContent || el.getAttribute?.('aria-label') || '');
              return text === 'category' || text.startsWith('category') || /\bwomen\b/.test(text);
          });
          if (named) return visibleDropdownControl(named) || named;
          if (following[0]) return visibleDropdownControl(following[0]) || following[0];
          node = node.parentElement;
      }
      return null;
  }

  function findMarketplaceCategoryControl(marketplace) {
      const scoped = document.querySelector(`[aria-label="Category Selector for ${marketplace}"] [role="category-input"]`);
      if (scoped) return scoped;
      const prefix = `listings.${marketplace}.overrides.category`;
      const exactIds = [
          `${prefix}V2`,
          `${prefix}V2-label`,
          `${prefix}V2-formGroupLabel`,
          `${prefix}V2-formGroup`,
          prefix,
          `${prefix}-label`,
          `${prefix}-formGroupLabel`,
          `listings.${marketplace}.category`,
      ];
      for (const id of exactIds) {
          const el = document.getElementById(id);
          if (!el || isGeneralCategoryControl(el)) continue;
          const clickable = nearestMarketplaceCategoryClickable(el)
              || visibleDropdownControl(el)
              || el.closest('button, [role="button"], [role="combobox"], [role="category-input"], .MuiAutocomplete-root, .MuiFormControl-root');
          if (clickable && !isGeneralCategoryControl(clickable)) return clickable;
          if (el && !isGeneralCategoryControl(el)) return el;
      }
      const labeled = findInputByExactLabel('Category', isMarketplaceInput(marketplace));
      if (labeled) return labeled;
      const resolved = resolveMarketplaceField(marketplace, ['category'], [
          `#listings\\.${marketplace}\\.overrides\\.category`,
          `#listings\\.${marketplace}\\.overrides\\.categoryV2`,
          `#listings\\.${marketplace}\\.category`,
      ]);
      if (resolved) return resolved;
      const headingHit = findCategoryControlNearHeading(marketplace);
      if (headingHit) return headingHit;
      const candidates = queryDeepAll(
          'button, [role="button"], [role="combobox"], [role="category-input"], [aria-label="Category"]'
      );
      const matches = [];
      for (const btn of candidates) {
          if (isGeneralCategoryControl(btn)) continue;
          const aria = normalizeText(btn.getAttribute('aria-label') || btn.getAttribute('title') || '');
          const labelled = normalizeText(labelledByText(btn));
          const text = normalizeText(btn.innerText || btn.textContent || '');
          const looksNamed = aria === 'category' || aria.startsWith('category ')
              || labelled === 'category' || labelled.startsWith('category ')
              || text === 'category' || text.startsWith('category ');
          const looksBreadcrumb = text.length < 180
              && /\bwomen\b|\bmen\b/.test(text)
              && /tops|blouses|shirts|tees/.test(text);
          if (!looksNamed && !looksBreadcrumb) continue;
          if (!isVisibleElement(btn) && !isAttachedElement(btn)) continue;
          matches.push(btn);
      }
      return matches.find((btn) => /women|men|tops|blouses|shirts|tees/i.test(btn.innerText || ''))
          || matches[0]
          || findMarketplaceCategoryBreadcrumb(marketplace);
  }

  function findMarketplaceCategoryBreadcrumb(marketplace) {
      const nodes = Array.from(document.querySelectorAll(
          'button, [role="button"], [role="combobox"], [role="category-input"], [aria-label="Category"], [tabindex="0"], div'
      ));
      const scored = [];
      for (const el of nodes) {
          if (!isVisibleElement(el)) continue;
          if (el.id === 'categoryV2') continue;
          const text = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          if (!text || text.length > 180) continue;
          if (!/\bwomen\b|\bmen\b/i.test(text)) continue;
          if (!/tops|blouses|shirts|tees/i.test(text)) continue;
          scored.push(el);
      }
      scored.sort((a, b) => String(a.innerText || '').length - String(b.innerText || '').length);
      const leaf = scored[0];
      if (!leaf) return null;
      return leaf.closest('button, [role="button"], [role="combobox"], [role="category-input"]') || leaf;
  }

  async function waitForMarketplaceCategoryControl(marketplace, attempts = 40) {
      for (let i = 0; i < attempts; i++) {
          const el = findMarketplaceCategoryControl(marketplace);
          if (el) return el;
          await sleep(CONFIG.SLEEP_LONG);
      }
      return findMarketplaceCategoryControl(marketplace);
  }

  function findGeneralCategoryControl() {
      const scoped = document.querySelector('[aria-label="Category Selector for vendoo"] [role="category-input"]');
      if (scoped) return scoped;
      const direct = document.querySelector('#categoryV2, [role="category-input"]');
      if (direct) return direct;
      return findInputByExactLabel('Category', (el) => {
          const id = String(el.id || '');
          if (/^listings\./i.test(id)) return false;
          return /category/i.test(id) || el.getAttribute('role') === 'combobox' || el.tagName === 'BUTTON';
      });
  }

  function isGeneralSizeValueControl(el) {
      if (!el || isSizeScaleControl(el)) return false;
      const id = String(el.id || el.name || '');
      if (/^listings\./i.test(id)) return false;
      return true;
  }

  function findGeneralSizeControl() {
      const hashed = queryByRecordedSelector(VENDOO_SELECTORS.size)
          || document.querySelector('[id="generalDetails.size.option.value"]')
          || document.querySelector('[name="generalDetails.size.option.value"]')
          || document.querySelector('[id*="generalDetails.size.option"]')
          || document.querySelector('[name*="generalDetails.size.option"]');
      if (hashed && isGeneralSizeValueControl(hashed)) {
          return visibleDropdownControl(hashed) || hashed;
      }

      const aria = document.querySelector('[aria-label="US Size"], [aria-label="Size"]');
      if (aria && isGeneralSizeValueControl(aria)) {
          return visibleDropdownControl(aria) || aria;
      }

      const labeled = findInputByExactLabel('US Size', isGeneralSizeValueControl)
          || findInputByExactLabel('Size', isGeneralSizeValueControl);
      if (labeled) return visibleDropdownControl(labeled) || labeled;

      const patched = findControlForPatch({ field: 'Size', selector: VENDOO_SELECTORS.size });
      if (patched && isGeneralSizeValueControl(patched)) return patched;
      return null;
  }

  async function waitForGeneralSizeControl(attempts = 10) {
      for (let i = 0; i < attempts; i++) {
          if (i === 1 || i === 4) await expandOptionalFields();
          const el = findGeneralSizeControl();
          if (el) return el;
          await sleep(CONFIG.SLEEP_RETRY);
      }
      return findGeneralSizeControl();
  }

  async function waitForGeneralCategoryControl(attempts = 12) {
      for (let i = 0; i < attempts; i++) {
          const el = findGeneralCategoryControl();
          if (el) return el;
          if (i % 4 === 0) await activateMarketplaceSection('general');
          await sleep(CONFIG.SLEEP_LONG);
      }
      return findGeneralCategoryControl();
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

      const catBtn = options.catBtn || await waitForGeneralCategoryControl();
      if (!catBtn) {
          warn('Category button #categoryV2 not found');
          return { ok: false, filled: false, error: 'Category button not found' };
      }

      const alreadyShown = readCategoryDisplay(catBtn);
      if (categoryDisplayMatches(alreadyShown, categoryPath)) {
          log(`Category already set: "${alreadyShown}"`);
          return { ok: true, filled: true, already: true, result: alreadyShown };
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
      if (searchInput && !data.marketplace_categories) {
          const leaf = segments[segments.length - 1] || '';
          const query = /\bblouses?\b/i.test(leaf) ? leaf : segments.slice(-2).join(' ');
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
                  'blouse': 'blouses',
                  'henley': 'henleys',
                  'tank': 'tank tops',
                  'tank top': 'tank tops',
                  'sweatshirt': 'sweatshirts',
                  'hoodie': 'hoodies',
                  'long sleeve': 'long sleeve t-shirts',
              };

              const wantLeaf = segments[segments.length - 1] || '';
              let targetType = '';
              if (/\bblouses?\b/i.test(wantLeaf) || /\bblouse/.test(typeLower)) {
                  targetType = 'Blouse';
              } else {
                  for (const [key, val] of Object.entries(TYPE_MAP)) {
                      if (typeLower.includes(key)) {
                          targetType = val;
                          break;
                      }
                  }
              }

              const rankedChildren = rankCategorySearchResults(children, [
                  wantLeaf,
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

      const currentButton = options.marketplace
          ? findMarketplaceCategoryControl(options.marketplace) : findGeneralCategoryControl();
      const catBtnText = readCategoryDisplay(currentButton);
      log(`Category selected. Button text: "${catBtnText}"`);

      if (!catBtnText || catBtnText.toLowerCase().includes('click to select')) {
          return { ok: false, filled: false, error: 'Category button not updated after selection' };
      }
      if (!categoryDisplayMatches(catBtnText, categoryPath)) {
          return { ok: false, filled: false, error: `Category stayed "${catBtnText}" instead of "${categoryPath}"` };
      }

      return { ok: true, filled: true, result: catBtnText };
  }

  function normalizeCategoryDisplay(shown) {
      return String(shown || '')
          .replace(/[▸▶›]/g, '>')
          .replace(/\s*>\s*/g, ' > ')
          .replace(/\s+/g, ' ')
          .trim();
  }

  function categoryOptionRecord(option) {
      const text = option.text || '';
      const full = option.el
          ? String(option.el.innerText || option.el.textContent || text).replace(/\u00a0/g, ' ').trim()
          : text;
      const path = normalizeCategoryDisplay(full.includes('>') || full.includes('▸') ? full : text);
      return { text, path, score: option.score || 0 };
  }

  async function searchCategoryPicker(query) {
      const q = String(query || '').trim();
      if (!q) return { ok: false, error: 'No category search query' };

      const catBtn = await waitForGeneralCategoryControl();
      if (!catBtn) {
          return { ok: false, error: 'Category button not found' };
      }

      await closeOpenMenus();
      catBtn.scrollIntoView({ block: 'center', behavior: 'instant' });
      await sleep(CONFIG.SLEEP_MEDIUM);
      log(`Searching Vendoo category picker for: "${q}"`);
      catBtn.click();
      await sleep(CONFIG.SLEEP_LONG * 2);

      let searchInput = await waitForCategorySearch();
      await resetCategoryPickerToRoot();
      searchInput = document.querySelector('input[role="category-search-field"]') || searchInput;
      if (!searchInput) {
          await closeOpenMenus();
          return { ok: false, error: 'Category search field not found' };
      }

      searchInput.focus();
      await clearInput(searchInput);
      setReactValue(searchInput, q);
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      searchInput.dispatchEvent(new KeyboardEvent('input', { bubbles: true }));
      searchInput.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(CONFIG.SLEEP_LONG * 2);

      const segments = q.split(/[>\s]+/).map((part) => part.trim()).filter(Boolean);
      const ranked = rankCategorySearchResults(listCategoryOptions(), segments);
      const matches = ranked.slice(0, 12).map(categoryOptionRecord);
      log(`Category search matches: ${JSON.stringify(matches.map((item) => item.path || item.text))}`);

      if (!ranked.length) {
          await closeOpenMenus();
          return { ok: false, query: q, matches, error: 'No matching Vendoo category' };
      }

      await clickCategoryOption(ranked[0]);
      await sleep(CONFIG.SLEEP_LONG * 2);

      const terminalSearch = document.querySelector('input[role="category-search-field"]');
      if (terminalSearch && document.contains(terminalSearch)) {
          const children = listCategoryOptions();
          const childRanked = rankCategorySearchResults(children, segments);
          if (childRanked.length) {
              await clickCategoryOption(childRanked[0]);
              await sleep(CONFIG.SLEEP_LONG);
          } else {
              await closeOpenMenus();
          }
      }

      const shown = normalizeCategoryDisplay(
          displayedFieldValue(catBtn) || catBtn.innerText || catBtn.textContent || '',
      ).split('\n')[0].trim();
      if (!shown || /click to select|select category/i.test(shown)) {
          const fallback = matches.find((item) => item.path.includes('>')) || matches[0];
          return {
              ok: Boolean(fallback?.path),
              query: q,
              path: fallback?.path || '',
              matches,
              error: fallback?.path ? null : 'Category picker did not keep a selection',
          };
      }

      return { ok: true, query: q, path: shown, matches };
  }

  function normalizeMercariCategoryPath(data) {
      const specs = data?.mercari_specifics;
      const explicit = specs && (specs.category_path || specs.categoryPath);
      if (explicit) {
          return Array.isArray(explicit) ? explicit.map((part) => String(part || '').trim()).filter(Boolean).join(' > ') : String(explicit).trim();
      }
      const categoryPath = String(data?.category_path || '').trim();
      // Leftover fills pass the Mercari path directly in category_path.
      if (/tops\s*&\s*blouses/i.test(categoryPath) && /\bblouses?\b/i.test(categoryPath.split('>').pop() || '')) {
          return 'Women > Tops & Blouses > Blouse';
      }
      if (/tops\s*&\s*blouses/i.test(categoryPath) && /t-?shirts?/i.test(categoryPath.split('>').pop() || '')) {
          return 'Women > Tops & Blouses > T-shirts';
      }
      const hay = categoryHaystack(data, categoryPath);
      const hayLower = normalizeText(hay);
      const isWomen = /\bwomen/.test(hayLower);
      const { isTee, isBlouse } = blouseVsTeeSignals(hayLower);
      if (isWomen && isBlouse) return 'Women > Tops & Blouses > Blouse';
      if (isWomen && isTee) return 'Women > Tops & Blouses > T-shirts';
      return categoryPath;
  }

  async function fillMarketplaceCategory(marketplace, data) {
      const categoryPath = data.marketplace_categories?.[marketplace] || (marketplace === 'poshmark'
          ? normalizePoshmarkCategoryPath(data)
          : marketplace === 'mercari'
              ? normalizeMercariCategoryPath(data)
          : String(data?.category_path || '').trim());
      if (!categoryPath) {
          recordFill({ field: 'Category', status: 'skipped', reason: 'No value in listing' });
          return { status: 'skipped' };
      }
      const catBtn = await waitForMarketplaceCategoryControl(marketplace);
      if (!catBtn) {
          const ids = Array.from(document.querySelectorAll('[id*="category" i], [name*="category" i], [role="category-input"], [aria-label="Category"]'))
              .map((el) => el.id || el.getAttribute('name') || el.getAttribute('role') || el.tagName)
              .filter(Boolean)
              .slice(0, 40);
          warn(`${marketplace} category field not found`);
          recordFill({
            field: 'Category',
            status: 'not_found',
            reason: `Category field not found (${ids.join(', ') || 'no mercari/category ids'})`,
            value: categoryPath,
          });
          return { status: 'not_found' };
      }
      const result = await fillCategoryPath(data, { catBtn, categoryPath, marketplace });
      recordFill({
        field: 'Category',
        status: result.ok ? (result.already ? 'skipped' : (result.filled ? 'filled' : 'skipped')) : 'failed',
        reason: result.error || (result.already ? 'Already set' : ''),
        selector: selectorFor(catBtn, ''),
        value: categoryPath,
      });
      return { status: result.ok ? (result.already ? 'skipped' : (result.filled ? 'filled' : 'skipped')) : 'failed' };
  }

  async function setGeneralCategoryOnly(data) {
      beginFillLog('general');
      log('=== Setting General category only (schema probe) ===');
      try {
          await activateMarketplaceSection('general');
          await sleep(CONFIG.SLEEP_LONG);
          if (!data?.category_path) {
              recordFill({
                  field: 'Category',
                  status: 'skipped',
                  reason: 'No value in listing',
                  selector: VENDOO_SELECTORS.category,
              });
              return { ok: false, error: 'No category_path in listing', fill_log: finishFillLog({ skipUnmapped: true }) };
          }
          const catResult = await fillCategoryPath(data);
          recordFill({
              field: 'Category',
              status: catResult.ok ? (catResult.filled ? 'filled' : 'skipped') : 'failed',
              reason: catResult.error || (catResult.already ? 'Already set' : ''),
              selector: VENDOO_SELECTORS.category,
              value: data.category_path,
          });
          if (!catResult.ok) {
              return {
                  ok: false,
                  error: catResult.error || 'Category selection failed',
                  fill_log: finishFillLog({ skipUnmapped: true }),
              };
          }
          await sleep(CONFIG.SLEEP_LONG);
          return { ok: true, fill_log: finishFillLog({ skipUnmapped: true }) };
      } catch (err) {
          recordFill({ field: 'form', status: 'failed', reason: err.message });
          return { ok: false, error: err.message, fill_log: finishFillLog({ skipUnmapped: true }) };
      }
  }

  // ============================================
  // MAIN VENDOO FORM FILLER - OPTIMIZED
  // ============================================

  async function fillMainForm(data) {
      beginFillLog('general');
      log('=== Filling Main Vendoo Form ===');

      try {
      await activateMarketplaceSection('general');
      await sleep(CONFIG.SLEEP_LONG);
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
            reason: catResult.already ? 'Already set' : '',
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
          const sizeEl = await waitForGeneralSizeControl();
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
      const generalTags = listingTagValues(data);
      if (generalTags.length) {
          await fillDropdownField(VENDOO_SELECTORS.tags, generalTags, 'Tags', false, true);
      } else {
          recordFill({ field: 'Tags', status: 'skipped', reason: 'No value in listing', selector: VENDOO_SELECTORS.tags });
      }
      
      if (data.labels) {
          const labelsEl = document.querySelector(VENDOO_SELECTORS.labels);
          if (labelsEl) {
              const labels = Array.isArray(data.labels) ? data.labels : data.labels.split(',').map(l => l.trim()).filter(Boolean);
              if (chipsMatchValues(labelsEl, labels)) {
                  recordAlreadySet('Labels', labelsEl, VENDOO_SELECTORS.labels, labels);
              } else {
                  for (const label of labels) await fillCombobox(labelsEl, label, false, true);
                  recordFill({ field: 'Labels', status: 'filled', selector: VENDOO_SELECTORS.labels, value: labels });
              }
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
      const packageDims = data.package_dimensions_in || '';
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
      const showNeedles = ['show optional fields', 'show optional', 'show more', 'more options'];
      const hideNeedles = ['hide optional fields', 'hide optional', 'show less'];
      const buttons = Array.from(document.querySelectorAll('button, span[role="button"], a, div[role="button"]'));
      let expanded = false;

      for (const btn of buttons) {
          if (!isVisibleElement(btn)) continue;
          const rawText = (btn.innerText || btn.textContent || '').trim();
          const btnText = normalizeText(rawText);
          if (!btnText) continue;
          if (hideNeedles.some((needle) => btnText.includes(needle)) || btn.getAttribute?.('aria-expanded') === 'true') {
              log(`Optional fields already expanded: "${rawText}"`);
              expanded = true;
              continue;
          }
          if (!showNeedles.some((needle) => btnText.includes(needle))) continue;

          log(`Expanding optional fields: "${rawText}"`);
          btn.scrollIntoView({ block: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_SHORT);
          btn.click();
          await sleep(CONFIG.SLEEP_LONG);
          expanded = true;
      }
      return expanded;
  }

  const EBAY_OPTIONAL_FIELD_LABELS = [
      'Accents', 'Character', 'Character Family', 'Fabric Type', 'Fabric Weight',
      'Features', 'Garment Care', 'Handmade', 'Country of Origin',
  ];
  const EBAY_CASCADE_SPECIFIC_KEYS = ['sizeType', 'department', 'type', 'size'];

  async function waitForEbayOptionalCategoryFields() {
      log('Expanding optional fields for eBay...');
      let ready = false;
      for (let attempt = 0; attempt < 8; attempt++) {
          await expandOptionalFields();
          const inputs = collectEbayCategoryInputs();
          ready = EBAY_OPTIONAL_FIELD_LABELS.some((label) => findEbaySpecificInput(label, inputs));
          if (ready) break;
          await sleep(CONFIG.SLEEP_LONG);
      }
      if (ready) {
          log('eBay optional category fields are visible');
      } else {
          warn('eBay optional category fields did not appear after expanding');
      }
      return ready;
  }

  // ============================================
  // PLATFORM-SPECIFIC FILLERS - OPTIMIZED
  // ============================================

  function isDoesNotApplyValue(value) {
      return /^(d|n\/?a|n\.a\.?|does not apply|none|unknown|-+)$/i.test(String(value || '').trim());
  }

  function normalizeEbaySpecificValue(key, value) {
      if (value == null || value === '') return value;
      const raw = Array.isArray(value) ? value.join(', ') : String(value).trim();
      if (key === 'yearManufactured') {
          if (isDoesNotApplyValue(raw)) return null;
          if (/pre-?1900s/i.test(raw)) return 'Pre-1900s';
          const years = raw.match(/(?:19|20)\d{2}/g);
          if (years && years.length >= 2) return `${years[0]}-${years[1]}`;
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
      if (key === 'type' && /t[\s-]?shirt|\btees?\b/i.test(raw)) return 'T-Shirt';
      if (key === 'department') {
          if (/^women/i.test(raw)) return 'Women';
          if (/^men/i.test(raw)) return 'Men';
          return raw;
      }
      if (key === 'season') {
          const allowed = ['Fall', 'Spring', 'Summer', 'Winter'];
          const parts = raw.split(/[,;/|]+/).map((part) => part.trim()).filter(Boolean);
          const matched = [];
          for (const part of parts) {
              if (/^all seasons$/i.test(part)) continue;
              const hit = allowed.find((item) => item.toLowerCase() === part.toLowerCase());
              if (hit && !matched.includes(hit)) matched.push(hit);
          }
          if (matched.length === 0) return null;
          return matched.length === 1 ? matched[0] : matched;
      }
      if (key === 'countryOfOrigin' && /^unknown$/i.test(raw)) return null;
      if (isDoesNotApplyValue(raw) && key !== 'yearManufactured') return 'Does Not Apply';
      return value;
  }

  async function fillEbayForm(data) {
      log('Filling eBay form...');
      await fillMarketplaceCategory('ebay', data);
      await sleep(CONFIG.SLEEP_LONG);

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
      
      const specs = { ...(data.ebay_specifics || {}) };
      const nestedSpecifics = specs.category_specifics;
      if (nestedSpecifics && typeof nestedSpecifics === 'object' && !Array.isArray(nestedSpecifics)) {
          for (const [key, value] of Object.entries(nestedSpecifics)) {
              if (specs[key] == null) specs[key] = value;
          }
      }
      const nestedMarket = specs.marketplaceSpecifics || specs.marketplace_specifics;
      if (nestedMarket && typeof nestedMarket === 'object' && !Array.isArray(nestedMarket)) {
          for (const [key, value] of Object.entries(nestedMarket)) {
              if (specs[key] == null) specs[key] = value;
          }
      }
      delete specs.category_specifics;
      delete specs.marketplaceSpecifics;
      delete specs.marketplace_specifics;
      if (!specs.department && (data.department || specs.Department)) {
          specs.department = data.department || specs.Department;
      }
      if (!specs.type && (data.type || specs.Type)) {
          specs.type = data.type || specs.Type;
      }
      if (!specs.sizeType && data.sizeType) specs.sizeType = data.sizeType;
      if (!specs.size && (data.size || data.size_us)) specs.size = data.size || data.size_us;

      if (Object.keys(specs).length) {
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

          // "All Seasons" is a Features chip, not a Season option (Season = Fall/Spring/Summer/Winter only).
          const seasonRaw = specs.season;
          if (/all seasons/i.test(String(seasonRaw || ''))) {
              const features = Array.isArray(specs.features) ? specs.features.slice() : String(specs.features || '').split(',').map((item) => item.trim()).filter(Boolean);
              if (!features.some((item) => /all seasons/i.test(item))) features.push('All Seasons');
              specs.features = features;
              delete specs.season;
          }
          const fillOrder = [
              'sizeType', 'department', 'type', 'size',
              ...Object.keys(specs).filter(key => !['sizeType', 'type', 'department', 'size', 'Department', 'Type', 'category_specifics'].includes(key)),
          ];
          let optionalsReady = false;

          let filledNames = new Set();

          for (const key of fillOrder) {
              const mapped = normalizeEbaySpecificValue(key, specs[key]);
              const fieldName = fieldNameMap[key] || key;
              const fieldKey = normalizeFieldKey(fieldName);
              if (filledNames.has(fieldKey)) continue;
              if (isAccountSettingField(fieldName) || isAccountSettingField(key)) continue;
              const isCascade = EBAY_CASCADE_SPECIFIC_KEYS.includes(key);
              if (mapped && typeof mapped === 'object' && !Array.isArray(mapped)) continue;
              if (specs[key] && (mapped == null || mapped === '')) {
                  recordFill({
                    field: fieldName,
                    status: 'skipped',
                    reason: 'No matching eBay option',
                    value: specs[key],
                  });
                  filledNames.add(fieldKey);
                  continue;
              }
              if (!mapped) continue;
              if ((key === 'brand' || key === 'color') && fillLedger.some((entry) => normalizeFieldKey(entry.field) === key && entry.status === 'filled')) {
                  continue;
              }

              if (!isCascade && !optionalsReady) {
                  await waitForEbayOptionalCategoryFields();
                  optionalsReady = true;
              }

              allInputs = collectEbayCategoryInputs();
              let foundEl = findEbaySpecificInput(fieldName, allInputs);
              if ((key === 'type' || key === 'department') && foundEl && !isEnabledField(foundEl)) {
                  for (let attempt = 0; attempt < 6 && foundEl && !isEnabledField(foundEl); attempt++) {
                      await sleep(CONFIG.SLEEP_RETRY);
                      allInputs = collectEbayCategoryInputs();
                      foundEl = findEbaySpecificInput(fieldName, allInputs);
                  }
              }
              if (!foundEl && !isCascade) {
                  for (let attempt = 0; attempt < 4 && !foundEl; attempt++) {
                      await expandOptionalFields();
                      await sleep(CONFIG.SLEEP_RETRY);
                      allInputs = collectEbayCategoryInputs();
                      foundEl = findEbaySpecificInput(fieldName, allInputs);
                  }
              }

              if (!foundEl) {
                  foundEl = findInputByExactLabel(fieldName, isMarketplaceInput('ebay'));
              }
              if (!foundEl) {
                  warn(`Could not find field for ${key}`);
                  recordFill({
                    field: fieldName,
                    status: 'skipped',
                    reason: 'Not on this category form',
                    value: mapped,
                  });
                  filledNames.add(fieldKey);
                  continue;
              }
              filledNames.add(fieldKey);

              let valuesToFill = isMultiChipField(fieldName, foundEl)
                  ? splitChipValues(mapped)
                  : Array.isArray(mapped) ? mapped :
                  (typeof mapped === 'string' && mapped.includes(',') && !['yearManufactured', 'mpn', 'upc'].includes(key)) ?
                  mapped.split(',').map(v => v.trim()) : [mapped];

              if (key === 'color') {
                  valuesToFill = valuesToFill.map(item => mapColor(item, 'ebay')).filter(Boolean);
              }
              if (key === 'type') {
                  valuesToFill = uniqueStrings([
                      ...(/t[\s-]?shirt|\btees?\b/i.test(String(mapped)) ? ['T-Shirt'] : []),
                      ...valuesToFill,
                  ]);
              }
              if (key === 'department') {
                  const rawDept = String(mapped);
                  valuesToFill = uniqueStrings([
                      rawDept,
                      ...(/^women/i.test(rawDept) ? ['Women', "Women's"] : []),
                      ...(/^men/i.test(rawDept) ? ['Men', "Men's"] : []),
                      ...(/unisex/i.test(rawDept) ? ['Unisex Adults', 'Unisex'] : []),
                  ]);
              }

              const isSizeField = key.toLowerCase() === 'size';
              log(`  Filling eBay ${fieldName}: ${valuesToFill.join(', ')}`);

              if (isMultiChipField(fieldName, foundEl)) {
                  await fillDropdownField(foundEl, valuesToFill, fieldName, isSizeField, true);
              } else if (key === 'type' || key === 'department') {
                  let filled = false;
                  for (const item of valuesToFill) {
                      const result = await fillDropdownField(foundEl, item, fieldName, false, false);
                      if (result && result.status === 'filled') {
                          filled = true;
                          break;
                      }
                  }
                  if (!filled) {
                      warn(`eBay ${fieldName} could not be set from ${valuesToFill.join(', ')}`);
                  }
              } else if (valuesToFill.length > 1) {
                  for (const item of valuesToFill) {
                      await fillDropdownField(foundEl, item, fieldName, isSizeField, true);
                      await sleep(CONFIG.SLEEP_MEDIUM);
                  }
              } else {
                  await fillDropdownField(foundEl, valuesToFill[0], fieldName, isSizeField, false);
              }
              if (key === 'department' || key === 'type') await sleep(CONFIG.SLEEP_LONG * 2);
          }
      }
  }

  async function fillEtsyForm(data) {
      log('Filling Etsy form...');
      await fillMarketplaceCategory('etsy', data);
      await sleep(CONFIG.SLEEP_LONG);

      const specs = data.etsy_specifics || {};
      const ebaySpecifics = data.ebay_specifics || {};
      const approvedWhenMade = specs.when_made || specs.whenMade || '';
      const normalizedWhenMade = approvedWhenMade ? normalizeEtsyWhenMade(approvedWhenMade) : '';

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
          if (normalizedWhenMade) {
              await fillDropdownField('#listings\\.etsy\\.marketplaceSpecifics\\.whenMade', normalizedWhenMade, 'When Made');
          } else {
              recordFill({
                  field: 'When Made',
                  status: 'skipped',
                  reason: 'No approved when-made value; leaving blank rather than inventing a date',
                  selector: '#listings.etsy.marketplaceSpecifics.whenMade',
              });
          }
          const listingType = specs.listing_type || specs.listingType || '';
          if (listingType) {
              await fillDropdownField(
                  '#listings\\.etsy\\.marketplaceSpecifics\\.listingType',
                  listingType,
                  'Listing Type'
              );
          }
          const renewalOption = specs.renewal_option || specs.renewalOption || '';
          if (renewalOption) {
              await fillDropdownField(
                  '#listings\\.etsy\\.marketplaceSpecifics\\.renewalOption',
                  renewalOption,
                  'Renewal Option'
              );
          }
          const processingProfile =
              specs.processing_time ||
              specs.processingTime ||
              specs.processingProfile ||
              specs.processingProfilesAccountSpecific ||
              '';
          if (processingProfile) {
              await fillDropdownField(
                  resolveMarketplaceField('etsy', ['processing', 'ready to ship'], [
                      '#listings\\.etsy\\.marketplaceSpecifics\\.processingProfilesAccountSpecific',
                      '#listings\\.etsy\\.marketplaceSpecifics\\.processingTime',
                  ]),
                  processingProfile,
                  'Processing Time'
              );
          } else if (/digital/i.test(String(listingType))) {
              recordFill({
                  field: 'Processing Time',
                  status: 'skipped',
                  reason: 'Digital Item — no physical processing/shipping profile required',
              });
          }
          const shippingProfile =
              specs.shipping_template ||
              specs.shippingTemplate ||
              specs.shippingProfile ||
              specs.shippingProfilesAccountSpecific ||
              '';
          if (shippingProfile) {
              await fillDropdownField(
                  resolveMarketplaceField('etsy', ['shipping profile', 'shipping'], [
                      '#listings\\.etsy\\.marketplaceSpecifics\\.shippingProfilesAccountSpecific',
                      '#listings\\.etsy\\.marketplaceSpecifics\\.shippingTemplate',
                  ]),
                  shippingProfile,
                  'Shipping Profile'
              );
          } else if (/digital/i.test(String(listingType))) {
              recordFill({
                  field: 'Shipping Profile',
                  status: 'skipped',
                  reason: 'Digital Item — no physical shipping profile required',
              });
          }
          const listingStateEl = document.querySelector('#listings\\.etsy\\.marketplaceSpecifics\\.listingState');
          if (listingStateEl) {
              await fillDropdownField(listingStateEl, 'Draft Listing', 'Listing State');
          }
          
          const etsyTags = uniqueStrings([
              ...listingTagValues({ tags: specs.tags }),
              ...listingTagValues(data),
          ]);
          if (etsyTags.length) {
              await fillDropdownField(
                  resolveMarketplaceField('etsy', ['tags'], [
                      '#listings\\.etsy\\.marketplaceSpecifics\\.tags',
                      '#listings\\.etsy\\.overrides\\.tags',
                  ]),
                  etsyTags,
                  'Tags',
                  false,
                  true
              );
          }

          const marketplaceMaterialsEl = document.querySelector('#listings\\.etsy\\.marketplaceSpecifics\\.materials');
          if (marketplaceMaterialsEl && specs.materials) {
              await fillDropdownField(marketplaceMaterialsEl, specs.materials, 'Materials', false, true);
          }

          const etsyOptionalLabels = ['Graphic', 'Materials', 'Fabric pattern', 'Occasion', 'Holiday', 'Sustainability', 'Size'];
          let optionalCategoryReady = false;
          for (let attempt = 0; attempt < 8; attempt++) {
              optionalCategoryReady = etsyOptionalLabels.some((label) => findInputByExactLabel(label, isEtsyCategorySpecificInput));
              if (optionalCategoryReady) break;
              await expandOptionalFields();
              await sleep(CONFIG.SLEEP_LONG);
          }
          if (optionalCategoryReady) {
              log('Etsy optional category fields are visible');
          } else {
              warn('Etsy optional category fields did not appear after expanding');
          }
          
          log('Filling Etsy category specifics...');
          
          const etsyCategoryFieldMap = {
              'sleeveLength': ['sleeve length'],
              'neckline': ['neckline'],
              'clothingStyle': ['clothing style'],
              'closure': ['closure'],
              'collarStyle': ['collar style'],
              'fabricPattern': ['fabric pattern'],
              'pattern': ['fabric pattern'],
              'occasion': ['occasion'],
              'holiday': ['holiday'],
              'sustainability': ['sustainability'],
              'graphic': ['graphic'],
              'materials': ['materials'],
              'size': ['size']
          };
          const etsyMultiFields = new Set(['materials']);
          const categorySpecifics = { ...(specs.category_specifics || {}) };
          const rootLevelEtsyCategoryFields = [
              'sleeveLength', 'neckline', 'clothingStyle', 'closure', 'collarStyle',
              'pattern', 'fabricPattern', 'occasion', 'holiday', 'sustainability',
              'graphic', 'size', 'materials'
          ];

          for (const fieldName of rootLevelEtsyCategoryFields) {
              if (specs[fieldName] && categorySpecifics[fieldName] == null) {
                  categorySpecifics[fieldName] = specs[fieldName];
              }
          }

          if (categorySpecifics.pattern && categorySpecifics.fabricPattern == null) {
              categorySpecifics.fabricPattern = categorySpecifics.pattern;
          }
          delete categorySpecifics.pattern;

          if (categorySpecifics.fabric && categorySpecifics.materials == null) {
              categorySpecifics.materials = categorySpecifics.fabric;
          }
          delete categorySpecifics.fabric;

          if (specs.materials && categorySpecifics.materials == null) {
              categorySpecifics.materials = specs.materials;
          }

          const etsyFallbackCategoryFields = {
              closure: ebaySpecifics.closure,
              collarStyle: ebaySpecifics.collarStyle || ebaySpecifics.collar_style,
              sleeveLength: ebaySpecifics.sleeveLength,
              neckline: ebaySpecifics.neckline,
              fabricPattern: ebaySpecifics.pattern,
              size: data.size || ebaySpecifics.size,
              graphic: ebaySpecifics.theme || ebaySpecifics.characterFamily || ebaySpecifics.character,
              materials: ebaySpecifics.material,
          };

          for (const [fieldName, fallbackValue] of Object.entries(etsyFallbackCategoryFields)) {
              if (fallbackValue && categorySpecifics[fieldName] == null) {
                  categorySpecifics[fieldName] = fallbackValue;
              }
          }

          const fillOrder = [
              'clothingStyle', 'sleeveLength', 'neckline', 'materials', 'graphic',
              'occasion', 'holiday', 'sustainability', 'size', 'fabricPattern',
              ...Object.keys(categorySpecifics).filter((key) => ![
                  'clothingStyle', 'sleeveLength', 'neckline', 'materials', 'graphic',
                  'occasion', 'holiday', 'sustainability', 'size', 'fabricPattern'
              ].includes(key)),
          ];
          
          for (const jsonField of fillOrder) {
              const rawValue = categorySpecifics[jsonField];
              if (!rawValue) continue;

              const labelPatterns = etsyCategoryFieldMap[jsonField] || [normalizeText(jsonField)];
              const parts = Array.isArray(rawValue)
                  ? rawValue
                  : (typeof rawValue === 'string' && rawValue.includes(','))
                      ? rawValue.split(',').map((value) => value.trim()).filter(Boolean)
                      : [rawValue];
              let valuesToFill = parts
                  .map((value) => normalizeEtsyCategorySpecificValue(jsonField, value))
                  .filter(Boolean);
              if (!etsyMultiFields.has(jsonField) && valuesToFill.length > 1) {
                  valuesToFill = valuesToFill.slice(0, 1);
              }

              if (valuesToFill.length === 0) {
                  recordFill({
                    field: jsonField,
                    status: 'skipped',
                    reason: 'No matching Etsy option',
                    value: rawValue,
                  });
                  continue;
              }

              const etsyCategoryInputs = collectEtsyCategoryInputs();
              const foundEl = findEtsyCategoryInput(jsonField, labelPatterns, etsyCategoryInputs);
              
              if (foundEl) {
                  const isMulti = etsyMultiFields.has(jsonField);
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
      }
      
  }

  function listingSizeValue(data) {
      const value = data?.size || data?.size_us || data?.ebay_specifics?.size;
      return value == null ? '' : String(value).trim();
  }

  function listingTagValues(data, extra) {
      const raw = extra != null ? extra : data?.tags;
      if (!raw) return [];
      return uniqueStrings((Array.isArray(raw) ? raw : String(raw).split(','))
          .map((tag) => String(tag).trim())
          .filter(Boolean));
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
      const controls = document.querySelectorAll('input, textarea, select, [role="combobox"], [role="checkbox"], [role="switch"]');
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

  async function fillMarketplaceTagField(marketplace, data, fieldName, labelPatterns, selectors = [], extraTags) {
      const tags = listingTagValues(data, extraTags);
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
      await fillDropdownField(el, tags, fieldName, false, true);
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
          ],
          data?.poshmark_specifics?.styleTags || data?.poshmark_specifics?.tags
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
          const shown = displayedFieldValue(el);
          if (result.status === 'filled' && optionMatchesValue(shown, candidate, true) && !/^select\b/i.test(shown || '')) {
              log(`  ✓ Mercari Brand: "${shown || candidate}"`);
              await setMercariNoBrandChecked(false);
              return;
          }
      }

      if (fieldLooksFilled(el)) await clearInput(el);
      await setMercariNoBrandChecked(true, 'Brand not in Mercari list');
  }

  async function fillMercariForm(data) {
      log('Filling Mercari form...');
      await fillMarketplaceCategory('mercari', data);
      await sleep(CONFIG.SLEEP_LONG);

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
      await fillMarketplaceCategory('depop', data);
      await sleep(CONFIG.SLEEP_LONG);

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
          await fillDropdownField(
              findDepopField(['parcel size', 'parcel'], '#listings\\.depop\\.marketplaceSpecifics\\.parcelSize'),
              specs.parcelSize || specs.parcel_size,
              'Parcel Size',
              true
          );
          
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

  function base64ToUint8Array(data) {
      const binary = atob(data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
      }
      return bytes;
  }

  async function uploadStudioPhotos(files) {
      if (!files || files.length === 0) {
          return { ok: true, count: 0 };
      }

      const ready = await waitForListingFormReady();
      if (!ready.ok) {
          return { ok: false, error: ready.error || 'Vendoo listing form did not finish loading' };
      }

      log(`Uploading ${files.length} photos from Studio...`);

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
      for (const file of files) {
          try {
              const bytes = base64ToUint8Array(file.data);
              const name = file.name || 'photo.jpg';
              fileObjects.push(new File([bytes], name, { type: file.type || 'image/jpeg' }));
          } catch (e) {
              warn(`Photo decode error: ${e.message}`);
          }
      }

      if (fileObjects.length === 0) {
          return { ok: false, error: 'No photos could be decoded' };
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

  function listingFormMarkersPresent() {
      return Boolean(
          document.querySelector('[data-testid="save-item-button"]')
          || document.querySelector('#generalDetails\\.title, [id="generalDetails.title"]')
          || document.querySelector('#categoryV2, [role="category-input"]')
      );
  }

  async function waitForListingFormReady(timeoutMs = 30000) {
      log('Waiting for Vendoo listing form...');
      const started = Date.now();
      while (Date.now() - started < timeoutMs) {
          if (listingFormMarkersPresent()) {
              log('Vendoo listing form is ready');
              return { ok: true, hasSaveButton: Boolean(document.querySelector('[data-testid="save-item-button"]')) };
          }
          const bodyText = (document.body?.innerText || '').slice(0, 800).toLowerCase();
          if (bodyText.includes('sign in') && (bodyText.includes('password') || bodyText.includes('log in'))) {
              warn('Vendoo login wall detected while waiting for form');
              return { ok: false, error: 'Vendoo login required before filling fields' };
          }
          await sleep(500);
      }
      warn('Vendoo listing form did not finish loading');
      return { ok: false, error: 'Vendoo listing form did not finish loading' };
  }

  async function waitForSaveButton(timeoutMs = 20000, { requireEnabled = true } = {}) {
      const started = Date.now();
      let lastBtn = null;
      while (Date.now() - started < timeoutMs) {
          const saveBtn = document.querySelector('[data-testid="save-item-button"]');
          if (saveBtn) {
              lastBtn = saveBtn;
              if (!requireEnabled || !saveBtn.disabled) return saveBtn;
          }
          await sleep(250);
      }
      const saveBtn = document.querySelector('[data-testid="save-item-button"]') || lastBtn;
      if (!saveBtn) return null;
      if (requireEnabled && saveBtn.disabled) return null;
      return saveBtn;
  }

  function findSaveButtonByText() {
      const buttons = Array.from(document.querySelectorAll('button, div[role="button"]'));
      const PROHIBITED_TERMS = ['list', 'publish', 'activate', 'sell'];
      return buttons.find((b) => {
          const t = (b.innerText || '').trim().toLowerCase();
          if (!t || t.length > 20) return false;
          if (!t.includes('save')) return false;
          if (PROHIBITED_TERMS.some((pt) => t.includes(pt))) {
              warn(`Skipping prohibited save button: "${b.innerText}"`);
              return false;
          }
          return true;
      }) || null;
  }

  async function saveGeneralForm() {
      log('Saving form...');
      // Always wait for the SPA save control — tab "complete" fires before React mounts it.
      const saveBtn = await waitForSaveButton(20000, { requireEnabled: true });
      if (!saveBtn) {
          const existingSave = document.querySelector('[data-testid="save-item-button"]');
          if (existingSave && existingSave.disabled) {
              warn('Save button stayed disabled');
              return { ok: false, error: 'Save button stayed disabled' };
          }
      }
      if (saveBtn) {
          saveBtn.scrollIntoView({ block: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_MEDIUM);
          if (saveBtn.disabled) {
              warn('Save button stayed disabled');
              return { ok: false, error: 'Save button stayed disabled' };
          }
          saveBtn.click();
          await sleep(CONFIG.SLEEP_LONG * 3);
          log('Save button clicked, waiting for completion');

          let stillSaving = false;
          for (let i = 0; i < 10; i++) {
              await sleep(1000);
              stillSaving = Boolean(document.querySelector('[data-testid="save-item-button"][disabled]'));
              if (!stillSaving) break;
          }
          if (stillSaving) {
              warn('Save did not finish');
              return { ok: false, error: 'Save did not finish' };
          }

          let itemId = extractItemId();
          for (let i = 0; i < 15 && !itemId; i++) {
              await sleep(500);
              itemId = extractItemId();
          }
          if (!itemId) {
              warn('Save finished but the URL is still /item/new');
              return { ok: false, error: 'Save did not produce a durable Vendoo item ID' };
          }
          const vendooUrl = `https://web.vendoo.co/app/item/${itemId}`;

          log(`Save complete. Item ID: ${itemId}`);
          await waitForPostSaveForm(20000);
          return { ok: true, vendoo_item_id: itemId, vendoo_url: vendooUrl };
      }

      const target = findSaveButtonByText();
      if (target) {
          target.scrollIntoView({ block: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_MEDIUM);
          target.click();
          await sleep(CONFIG.SLEEP_LONG * 3);
          let itemId = extractItemId();
          for (let i = 0; i < 15 && !itemId; i++) {
              await sleep(500);
              itemId = extractItemId();
          }
          if (!itemId) {
              return { ok: false, error: 'Save did not produce a durable Vendoo item ID' };
          }
          return { ok: true, vendoo_item_id: itemId, vendoo_url: `https://web.vendoo.co/app/item/${itemId}` };
      }

      warn('Save button not found');
      return { ok: false, error: 'Save button not found' };
  }

  function auditValuesAgree(expected, observed) {
      if (expected == null || expected === '') return true;
      if (Array.isArray(expected)) {
          const want = expected.map((item) => normalizeComparableText(item)).filter(Boolean).sort();
          const got = (Array.isArray(observed) ? observed : String(observed || '').split(/[,|]/))
              .map((item) => normalizeComparableText(item)).filter(Boolean).sort();
          return want.every((item) => got.includes(item));
      }
      return normalizeComparableText(expected) === normalizeComparableText(observed);
  }

  async function auditGeneralForm(data) {
      log('Auditing general form...');
      await activateMarketplaceSection('general');
      if (!(await waitForMarketplaceFormMounted('general'))) {
          return {
              ok: false,
              error: 'General form did not mount for audit',
              fields: {},
              mismatches: ['General form did not mount for audit'],
              photos: 0,
              statuses: {},
          };
      }
      const fields = {};
      const mismatches = [];

      const checks = [
          { key: 'title', selector: '#generalDetails\\.title', label: 'Title' },
          { key: 'description', selector: '#generalDetails\\.description', label: 'Description' },
          { key: 'price', selector: '#generalDetails\\.price', label: 'Price' },
          { key: 'quantity', selector: '#generalDetails\\.quantity', label: 'Quantity' },
          { key: 'brand', selector: VENDOO_SELECTORS.brand, label: 'Brand' },
          { key: 'size', selector: '#generalDetails\\.size\\.option\\.value', label: 'Size' },
      ];

      await expandOptionalFields();
      for (const check of checks) {
          let el = document.querySelector(check.selector);
          if (check.key === 'size') {
              el = await waitForGeneralSizeControl();
          }
          const expected = data?.[check.key];
          const observed = el ? (readPersistedControlValue(el) || displayedFieldValue(el) || null) : null;
          const ok = auditValuesAgree(expected, observed);
          const state = ok ? 'audited_complete' : (el ? 'mismatch' : 'not_found');
          fields[check.key] = { state, expected: expected ?? '', observed: observed ?? '' };
          if (!ok && expected != null && expected !== '') {
              mismatches.push(`${check.label} expected "${expected}" but found "${observed ?? ''}"`);
          }
      }

      const categoryShown = controlValue(VENDOO_SELECTORS.category);
      if (data?.category_path && categoryShown) {
          const ok = normalizeComparableText(categoryShown).includes(normalizeComparableText(String(data.category_path).split('>').pop()));
          fields.category = { state: ok ? 'audited_complete' : 'mismatch', expected: data.category_path, observed: categoryShown };
          if (!ok) mismatches.push(`Category expected "${data.category_path}" but found "${categoryShown}"`);
      }

      const photos = scrapeListingImageUrls();
      const expectedPhotos = Array.isArray(data?._expected_photos) ? data._expected_photos.length : (data?._expected_photo_count || 0);
      fields.photos = { state: expectedPhotos && photos.length !== expectedPhotos ? 'mismatch' : 'audited_complete', expected: expectedPhotos, observed: photos.length };
      if (expectedPhotos && photos.length !== expectedPhotos) {
          mismatches.push(`Photos expected ${expectedPhotos} but found ${photos.length}`);
      }

      const statuses = scrapeMarketplaceStatusesFromDom();
      const listed = publishedMarketplaceStatuses(statuses);
      fields.publication = { state: listed.length ? 'mismatch' : 'audited_complete', expected: 'NOT LISTED', observed: statuses };
      if (listed.length) {
          mismatches.push(`Publication status is not draft: ${listed.map(([id, status]) => `${id}=${status}`).join(', ')}`);
      }

      const allOk = mismatches.length === 0;
      if (!allOk) warn(`General audit failed: ${mismatches.join('; ')}`);
      return { ok: allOk, fields, mismatches, photos: photos.length, statuses };
  }

  async function fillMarketplaceForm(data, platform) {
      beginFillLog(String(platform || 'unknown').toLowerCase());
      log(`Filling ${platform} marketplace...`);

      try {
      const activated = await activateMarketplaceSection(platform);
      if (!activated || !marketplaceSectionLooksActive(platform)) {
          const error = `Could not activate ${platform} marketplace section`;
          recordFill({ field: 'marketplace', status: 'failed', reason: error });
          return { ok: false, error, fill_log: finishFillLog() };
      }

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

  function marketplaceNavBareLabel(text) {
      // Do not use normalizeText() here: it splits camelCase, so "eBay" becomes "e bay".
      return String(text || '')
          .toLowerCase()
          .replace(/[_-]+/g, ' ')
          .replace(/\b(beta|new|alpha)\b/g, ' ')
          .replace(/\b(not listed|incomplete|complete|listed|failed|draft|sold|pending)\b/g, ' ')
          .replace(/[^\w\s]/g, ' ')
          .replace(/\s+/g, ' ')
          .trim();
  }

  function marketplaceNavLabelMatches(text, platform) {
      const wanted = String(platform || '').toLowerCase().trim();
      if (!wanted) return false;
      const bare = marketplaceNavBareLabel(text);
      if (!bare) return false;
      if (wanted === 'general' || wanted === 'vendoo') {
          return bare === 'general' || bare === 'vendoo' || bare.startsWith('general ') || bare.startsWith('vendoo ');
      }
      return bare === wanted || bare.startsWith(`${wanted} `);
  }

  function marketplaceSectionButtonMatches(btn, platform) {
      if (!btn) return false;
      const labelled = (btn.getAttribute && (
          btn.getAttribute('aria-label') || btn.getAttribute('title') || btn.getAttribute('data-marketplace') || ''
      )) || '';
      const chunks = [
          labelled,
          ...(String(btn.innerText || btn.textContent || '').split('\n')),
      ];
      return chunks.some((chunk) => marketplaceNavLabelMatches(chunk, platform));
  }

  function marketplaceFormMounted(marketplace) {
      const mp = String(marketplace || '').toLowerCase();
      if (!mp || mp === 'general') {
          return Boolean(document.querySelector(
              '[id^="generalDetails."], [name^="generalDetails."], #categoryV2, [role="category-input"]'
          ));
      }
      const prefix = `listings.${mp}.`;
      return Boolean(document.querySelector(`[id^="${prefix}"], [name^="${prefix}"]`));
  }

  async function waitForMarketplaceFormMounted(marketplace, attempts = 20) {
      for (let attempt = 0; attempt < attempts; attempt++) {
          if (marketplaceFormMounted(marketplace)) return true;
          await sleep(CONFIG.SLEEP_LONG);
      }
      return marketplaceFormMounted(marketplace);
  }

  function marketplaceSectionLooksActive(platform) {
      const mp = String(platform || '').toLowerCase();
      if (!mp) return false;
      if (mp === 'general' || mp === 'vendoo') {
          const general = document.querySelector(
              '#categoryV2, [role="category-input"], [id^="generalDetails."], [name^="generalDetails."]'
          );
          return Boolean(general && isEffectivelyVisible(general));
      }
      const prefix = `listings.${mp}.`;
      const nodes = document.querySelectorAll(`[id^="${prefix}"], [name^="${prefix}"]`);
      for (const node of nodes) {
          const control = visibleDropdownControl(node) || (isEffectivelyVisible(node) ? node : null);
          if (control && isEffectivelyVisible(control)) return true;
      }
      const catBtn = findMarketplaceCategoryControl(mp);
      return Boolean(catBtn && isEffectivelyVisible(catBtn));
  }

  async function marketplaceSectionReady(platform) {
      // Mounted alone is not enough — sibling marketplace forms stay in the DOM
      // after schema discovery. Require the panel to be effectively visible too.
      if (!(await waitForMarketplaceFormMounted(platform))) return false;
      for (let attempt = 0; attempt < 12; attempt++) {
          if (marketplaceSectionLooksActive(platform)) return true;
          await sleep(CONFIG.SLEEP_RETRY);
      }
      return marketplaceSectionLooksActive(platform);
  }

  function marketplaceStatusIsPublished(status) {
      const s = String(status || '').replace(/\s+/g, ' ').trim().toUpperCase();
      if (!s) return false;
      if (s.includes('NOT LISTED')) return false;
      if (['DRAFT', 'INCOMPLETE', 'COMPLETE'].includes(s)) return false;
      return /\b(LISTED|LIVE|ACTIVE|SOLD|PUBLISHED)\b/.test(s);
  }

  function publishedMarketplaceStatuses(statuses) {
      return Object.entries(statuses || {}).filter(([, status]) => marketplaceStatusIsPublished(status));
  }

  function marketplaceStatusConfirmsDraft(status) {
      const s = String(status || '').replace(/\s+/g, ' ').trim().toUpperCase();
      return ['NOT LISTED', 'DRAFT', 'DRAFT LISTING', 'INCOMPLETE', 'COMPLETE'].includes(s);
  }

  function checkDraftSafety(platforms) {
      const statuses = scrapeMarketplaceStatusesFromDom();
      const listed = publishedMarketplaceStatuses(statuses);
      if (listed.length) {
          return {
              ok: false,
              error: `Refusing to update a published Vendoo item: ${listed.map(([id, status]) => `${id}=${status}`).join(', ')}`,
              statuses,
          };
      }
      const selected = Array.isArray(platforms)
          ? platforms.map((item) => String(item || '').toLowerCase()).filter(Boolean)
          : [];
      const required = selected.length ? selected : ['ebay', 'etsy', 'poshmark', 'mercari', 'depop'];
      const unverified = required.filter((platform) => !marketplaceStatusConfirmsDraft(statuses[platform]));
      if (!Object.keys(statuses).length || unverified.length) {
          return {
              ok: false,
              error: unverified.length
                  ? `Could not verify draft status for: ${unverified.join(', ')}`
                  : 'Could not verify that the existing Vendoo item is a draft',
              statuses,
          };
      }
      return { ok: true, statuses };
  }

  function marketplaceNameToId(name) {
      const bare = marketplaceNavBareLabel(name);
      if (!bare) return null;
      if (bare === 'vendoo' || bare === 'general') return 'general';
      const known = [
          'ebay', 'etsy', 'poshmark', 'mercari', 'depop', 'facebook',
          'shopify', 'vinted', 'whatnot', 'sellwild', 'grailed', 'vestiaire', 'kidizen',
      ];
      for (const id of known) {
          if (bare === id || bare.startsWith(`${id} `) || bare.includes(id)) return id;
      }
      return null;
  }

  function scrapeMarketplaceStatusesFromDom() {
      // Live labels from Vendoo's Step 1/2 nav: COMPLETE / NOT LISTED / LISTED / …
      // Ignore product badges like BETA — those are not listing statuses.
      const statuses = {};
      const statusRe = /^(complete|not listed|listed|live|active|published|failed|draft|sold|pending|incomplete)(?: listing)?$/i;
      const controls = Array.from(document.querySelectorAll(
          '[role="tab"], button, [role="button"], a, span[role="button"], li, [role="listitem"]'
      ));
      for (const el of controls) {
          if (!isVisibleElement(el)) continue;
          const ownLines = String(el.innerText || el.textContent || '')
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean);
          if (!ownLines.length || ownLines[0].length > 24) continue;
          const id = marketplaceNameToId(ownLines[0]);
          if (!id) continue;

          // Status often lives on a sibling dropdown; walk up to the row that
          // contains both the marketplace name and COMPLETE / NOT LISTED / LISTED.
          let statusLine = ownLines.slice(1).find((line) => statusRe.test(line));
          if (!statusLine) {
              let node = el.parentElement;
              for (let depth = 0; depth < 5 && node && !statusLine; depth++) {
                  const lines = String(node.innerText || node.textContent || '')
                      .split('\n')
                      .map((line) => line.trim())
                      .filter(Boolean);
                  // Keep the row tight so we don't absorb the whole sidebar.
                  if (lines.join(' ').length > 160) break;
                  statusLine = lines.find((line) => statusRe.test(line));
                  node = node.parentElement;
              }
          }
          if (!statusLine) continue;
          if (!statuses[id]) {
              statuses[id] = statusLine.replace(/\s+/g, ' ').toUpperCase();
          }
      }
      return statuses;
  }

  async function waitForMarketplaceNavControls(timeoutMs = 20000) {
      const started = Date.now();
      while (Date.now() - started < timeoutMs) {
          const buttons = Array.from(document.querySelectorAll(
              '[role="tab"], button, [role="button"], a, span[role="button"], [role="listitem"]'
          ));
          const named = buttons.filter((btn) => marketplaceNameToId(
              btn.getAttribute?.('aria-label') || btn.innerText || btn.textContent || ''
          ));
          if (named.length >= 3) return true;
          await sleep(400);
      }
      return false;
  }

  async function waitForPostSaveForm(timeoutMs = 25000) {
      await waitForListingFormReady(Math.min(timeoutMs, 20000));
      const started = Date.now();
      while (Date.now() - started < timeoutMs) {
          const saving = Boolean(document.querySelector('[data-testid="save-item-button"][disabled]'));
          const overlay = Array.from(document.querySelectorAll('.MuiBackdrop-root, [class*="MuiBackdrop-root"]'))
              .some((el) => isVisibleElement(el) && Number(window.getComputedStyle(el).opacity || 1) > 0);
          if (!saving && !overlay && listingFormMarkersPresent()) {
              if (await waitForMarketplaceNavControls(1500)) return true;
          }
          await sleep(400);
      }
      await waitForMarketplaceNavControls(5000);
      return listingFormMarkersPresent();
  }

  async function activateMarketplaceSection(platform) {
      log(`Activating ${platform} marketplace section...`);
      // Always click the marketplace nav control. After schema discovery, sibling
      // marketplace forms (eBay included) stay mounted and can look "visible"
      // while Depop is still the active panel — skipping the click makes
      // filling_ebay a no-op and the job races ahead to Etsy.
      // Also force-click when the form never mounts (Refresh path: aria can say
      // eBay is selected while generalDetails is still showing).
      // After save, Vendoo remounts the listing chrome; wait for nav buttons
      // before treating a missing Depop tab as a hard failure.
      await waitForPostSaveForm(20000);
      await closeOpenMenus();

      const clickMatching = async ({ force = false } = {}) => {
          const buttons = Array.from(document.querySelectorAll(
              '[role="tab"], button, [role="button"], a, span[role="button"], [role="listitem"]'
          ));
          const matches = buttons.filter((btn) => marketplaceSectionButtonMatches(btn, platform));
          if (!matches.length) return false;
          matches.sort((a, b) => {
              const av = isVisibleElement(a) ? 0 : 1;
              const bv = isVisibleElement(b) ? 0 : 1;
              if (av !== bv) return av - bv;
              return (a.innerText || '').length - (b.innerText || '').length;
          });
          const match = matches[0].closest('button, [role="tab"], [role="button"], a') || matches[0];
          const label = (match.innerText || match.textContent || match.getAttribute?.('aria-label') || '').trim().split('\n')[0];
          log(`  Clicking "${label}" to activate ${platform}${force ? ' (force)' : ''}`);
          match.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_SHORT);
          match.click();
          await sleep(CONFIG.SLEEP_LONG * 3);
          return true;
      };

      const started = Date.now();
      while (Date.now() - started < 30000) {
          if (await clickMatching()) {
              if (await marketplaceSectionReady(platform)) return true;
              if (await clickMatching({ force: true }) && await marketplaceSectionReady(platform)) return true;
              warn(`${platform} nav activated but form fields did not mount`);
          }
          await expandOptionalFields();
          await sleep(CONFIG.SLEEP_LONG);
          await closeOpenMenus();
          await waitForMarketplaceNavControls(2000);
      }
      warn(`Could not activate ${platform} marketplace section`);
      return false;
  }

  async function auditMarketplaceForm(data, platform) {
      log(`Auditing ${platform} marketplace...`);
      const mp = String(platform || '').toLowerCase();
      await waitForPostSaveForm(25000);
      const activated = await activateMarketplaceSection(mp);
      if (!activated || !marketplaceSectionLooksActive(mp)) {
          const error = `Could not activate ${platform} marketplace section`;
          warn(error);
          return { ok: false, error, fields: { _error: error } };
      }
      await expandOptionalFields();
      const fields = {};
      const mismatches = [];

      const platformSelectors = {
          ebay: [
              ['brand', ['#listings\\.ebay\\.overrides\\.brand'], ['Brand'], data?.brand || data?.ebay_specifics?.brand],
              ['price', [
                  '#listings\\.ebay\\.marketplaceSpecifics\\.pricingFormatDetails\\.fixedPrice\\.buyItNowPrice',
                  '#listings\\.ebay\\.overrides\\.price',
              ], ['Buy It Now Price', 'Listing Price', 'Price'], data?.price],
              ['quantity', ['#listings\\.ebay\\.overrides\\.quantity'], ['Quantity'], data?.quantity],
          ],
          etsy: [
              ['price', ['#listings\\.etsy\\.overrides\\.price'], ['Price'], data?.price],
              ['quantity', ['#listings\\.etsy\\.overrides\\.quantity'], ['Quantity'], data?.quantity],
              ['whoMade', ['#listings\\.etsy\\.marketplaceSpecifics\\.whoMade'], ['Who made it', 'Who made'], data?.etsy_specifics?.who_made || data?.etsy_specifics?.whoMade],
              ['whatIsIt', ['#listings\\.etsy\\.marketplaceSpecifics\\.whatIsIt'], ['What Is It', 'What is it'], data?.etsy_specifics?.what_is || data?.etsy_specifics?.whatIsIt],
              ['whenMade', ['#listings\\.etsy\\.marketplaceSpecifics\\.whenMade'], ['When Was It Made', 'When Made'], data?.etsy_specifics?.when_made || data?.etsy_specifics?.whenMade],
              ['listingType', ['#listings\\.etsy\\.marketplaceSpecifics\\.listingType'], ['Listing Type'], data?.etsy_specifics?.listing_type || data?.etsy_specifics?.listingType],
              ['renewalOption', ['#listings\\.etsy\\.marketplaceSpecifics\\.renewalOption'], ['Renewal options', 'Renewal Option'], data?.etsy_specifics?.renewal_option || data?.etsy_specifics?.renewalOption],
              ['listingState', ['#listings\\.etsy\\.marketplaceSpecifics\\.listingState'], ['Listing State'], 'Draft Listing'],
          ],
          poshmark: [
              ['brand', ['#listings\\.poshmark\\.overrides\\.brand'], ['Brand'], data?.brand],
              ['price', ['#listings\\.poshmark\\.overrides\\.price'], ['Price'], data?.price],
              ['quantity', ['#listings\\.poshmark\\.overrides\\.quantity'], ['Quantity'], data?.quantity],
              ['primaryColor', ['#listings\\.poshmark\\.overrides\\.primaryColor'], ['Primary Color', 'Color'], mapColor(data?.primaryColor || data?.color, 'poshmark')],
          ],
          mercari: [
              ['brand', ['#listings\\.mercari\\.overrides\\.brand'], ['Brand'], data?.brand],
              ['price', ['#listings\\.mercari\\.overrides\\.price'], ['Price'], data?.price],
              ['quantity', ['#listings\\.mercari\\.overrides\\.quantity'], ['Quantity'], data?.quantity],
          ],
          depop: [
              ['price', ['#listings\\.depop\\.overrides\\.price'], ['Price'], data?.price],
              ['quantity', ['#listings\\.depop\\.overrides\\.quantity'], ['Quantity'], data?.quantity],
              ['source', ['#listings\\.depop\\.marketplaceSpecifics\\.source'], ['Source'], data?.depop_specifics?.source],
              ['age', ['#listings\\.depop\\.marketplaceSpecifics\\.age'], ['Age'], data?.depop_specifics?.age],
              ['size', ['#listings\\.depop\\.overrides\\.size'], ['Size'], data?.size || data?.depop_specifics?.size],
              ['parcelSize', ['#listings\\.depop\\.marketplaceSpecifics\\.parcelSize'], ['Parcel Size'], data?.depop_specifics?.parcel_size || data?.depop_specifics?.parcelSize],
          ],
      };

      const selectors = platformSelectors[mp] || [];
      let foundAnyField = false;
      for (const [key, sels, labels, expected] of selectors) {
          let el = null;
          for (const sel of sels) {
              el = queryByRecordedSelector(sel) || document.querySelector(sel);
              if (el) break;
          }
          if (!el) {
              for (const label of labels || []) {
                  el = findInputByExactLabel(label, isMarketplaceInput(mp));
                  if (el) break;
              }
          }
          if (!el && key === 'category') {
              el = findMarketplaceCategoryControl(mp);
          }
          if (!el && key === 'size') {
              el = findMarketplaceSizeControl(mp);
          }
          if (el) el = visibleDropdownControl(el) || el;
          const readObserved = (node) => {
              if (!node) return '';
              const chips = listedChipValues(node);
              if (chips.length) return chips.length === 1 ? chips[0] : chips.join(', ');
              const root = fieldControlRoot(node) || node.parentElement;
              if (root) {
                  const rootChips = listedChipValues(root);
                  if (rootChips.length) return rootChips.length === 1 ? rootChips[0] : rootChips.join(', ');
                  const remove = root.querySelector('[aria-label^="Remove "], [title^="Remove "]');
                  const removeLabel = remove && (remove.getAttribute('aria-label') || remove.getAttribute('title') || '');
                  if (removeLabel) return removeLabel.replace(/^remove\s+/i, '').trim();
              }
              return readPersistedControlValue(node) || displayedFieldValue(node) || '';
          };
          let observed = readObserved(el);
          if (!observed && expected) {
              const want = String(Array.isArray(expected) ? expected[0] : expected).trim();
              if (want) {
                  const buttons = document.querySelectorAll('[aria-label^="Remove "], [title^="Remove "]');
                  for (const btn of buttons) {
                      const lab = String(btn.getAttribute('aria-label') || btn.getAttribute('title') || '')
                          .replace(/^remove\s+/i, '').trim();
                      if (lab && normalizeComparableText(lab) === normalizeComparableText(want)) {
                          observed = lab;
                          break;
                      }
                  }
              }
          }
          if (!observed && expected) {
              const want = String(Array.isArray(expected) ? expected[0] : expected).trim();
              const wantNorm = normalizeComparableText(want);
              if (wantNorm) {
                  const matchExact = (node) => {
                      if (!node) return '';
                      const own = String(node.childNodes && node.childNodes.length
                          ? Array.from(node.childNodes)
                              .filter((part) => part.nodeType === 3)
                              .map((part) => part.textContent || '')
                              .join('')
                          : (node.textContent || ''))
                          .replace(/\u00a0/g, ' ')
                          .trim();
                      if (own && normalizeComparableText(own) === wantNorm) return own;
                      const text = String(node.textContent || '').replace(/\u00a0/g, ' ').trim();
                      if (text && normalizeComparableText(text) === wantNorm) return text;
                      return '';
                  };
                  const scan = (root) => {
                      if (!root) return '';
                      const hit = matchExact(root);
                      if (hit) return hit;
                      const nodes = root.querySelectorAll
                          ? root.querySelectorAll('.MuiChip-label, [class*="Chip-label"], span, div, p, button, label')
                          : [];
                      for (const node of nodes) {
                          const text = matchExact(node);
                          if (text) return text;
                      }
                      return '';
                  };
                  let node = el;
                  for (let depth = 0; depth < 8 && node; depth++) {
                      let sib = node.previousElementSibling;
                      while (sib) {
                          const hit = scan(sib) || matchExact(sib);
                          if (hit) { observed = hit; break; }
                          sib = sib.previousElementSibling;
                      }
                      if (observed) break;
                      const hit = scan(node);
                      if (hit) { observed = hit; break; }
                      node = node.parentElement;
                  }
                  if (!observed) {
                      for (const label of labels || []) {
                          const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,label,legend,span,div,p'))
                              .filter((item) => normalizeComparableText(item.textContent || '') === normalizeComparableText(label));
                          for (const heading of headings) {
                              let sib = heading.nextElementSibling;
                              for (let i = 0; i < 6 && sib; i++) {
                                  const hit = scan(sib) || matchExact(sib);
                                  if (hit) { observed = hit; break; }
                                  sib = sib.nextElementSibling;
                              }
                              if (observed) break;
                              const hit = scan(heading.parentElement);
                              if (hit) { observed = hit; break; }
                          }
                          if (observed) break;
                      }
                  }
              }
          }
          if (!observed) {
              for (const label of labels || []) {
                  const labeled = findInputByExactLabel(label, isMarketplaceInput(mp));
                  const labeledObserved = readObserved(labeled);
                  if (labeledObserved) {
                      el = labeled || el;
                      observed = labeledObserved;
                      break;
                  }
              }
          }
          if (!observed && el) {
              observed = String(el.innerText || el.textContent || '').split('\n').map((line) => line.trim()).filter(Boolean)[0] || '';
          }
          const observedValue = observed || null;
          if (el) foundAnyField = true;
          let ok;
          if (key === 'category' && expected) {
              ok = categoryDisplayMatches(observed, expected);
          } else {
              ok = auditValuesAgree(expected, observed);
          }
          // Unfilled Etsy sections often keep Listing State = "Live Listing" while the
          // marketplace nav remains NOT LISTED. Publication is enforced via nav status.
          if (!ok && key === 'listingState' && mp === 'etsy') {
              const navStatus = scrapeMarketplaceStatusesFromDom()[mp] || '';
              const navConfirmsDraft = /^(not listed|draft|incomplete|complete)(?: listing)?$/i.test(String(navStatus).trim());
              if (navConfirmsDraft) {
                  const liveOrDraft = /^(live|draft)\s+listing$/i.test(String(observed || '').trim());
                  if (liveOrDraft || !String(observed || '').trim()) {
                      ok = true;
                  }
              }
          }
          fields[key] = { found: !!el, expected: expected ?? '', observed: observed ?? '', state: ok ? 'audited_complete' : (el ? 'mismatch' : 'not_found') };
          if (!ok && expected != null && expected !== '') {
              mismatches.push(`${platform} ${key} expected "${expected}" but found "${observed ?? ''}"`);
          }
      }

      if (!foundAnyField) {
          const error = `${platform} marketplace section appears inactive`;
          warn(error);
          return { ok: false, error, fields: { ...fields, _error: error }, mismatches: [error] };
      }

      const statuses = scrapeMarketplaceStatusesFromDom();
      const status = statuses[mp];
      if (status && marketplaceStatusIsPublished(status)) {
          mismatches.push(`${platform} publication status is ${status}`);
      }

      const allOk = mismatches.length === 0;
      if (!allOk) warn(`${platform} audit failed: ${mismatches.join('; ')}`);
      return { ok: allOk, fields, mismatches, statuses };
  }

  function extractItemId() {
      const nonDurable = new Set(['new', 'edit', 'create']);
      const match = window.location.href.match(/\/(?:app\/)?item\/([^/?]+)/);
      if (match) {
          const id = String(match[1] || '').trim();
          if (!id || nonDurable.has(id.toLowerCase())) return null;
          return id;
      }

      const el = document.querySelector('[data-item-id], [data-testid="item-id"]');
      if (el) {
          const id = String(el.getAttribute('data-item-id') || el.textContent || '').trim();
          if (!id || nonDurable.has(id.toLowerCase())) return null;
          return id;
      }

      return null;
  }

  function controlValue(selector) {
      const el = document.querySelector(selector);
      if (!el) return '';
      if ('value' in el && el.value != null && String(el.value).trim()) return String(el.value).trim();
      const text = (el.innerText || el.textContent || '').trim();
      return text;
  }

  function scrapeListingImageUrls() {
      const urls = [];
      const seen = new Set();
      const add = (raw) => {
          if (!raw || typeof raw !== 'string') return;
          let url = raw.trim();
          if (url.startsWith('//')) url = `https:${url}`;
          if (!(url.startsWith('http://') || url.startsWith('https://') || url.startsWith('blob:'))) return;
          if (url.startsWith('data:')) return;
          const lower = url.toLowerCase();
          if (lower.includes('favicon') || lower.includes('/logo') || lower.includes('gravatar')) return;
          const looksImage = url.startsWith('blob:')
              || /\.(jpe?g|png|webp|gif|heic|heif|avif)(\?|$)/i.test(url)
              || /cloudinary|cloudfront|googleusercontent|firebasestorage|imgix|storage\.googleapis\.com/.test(lower)
              || /(cdn|images|img|media|static|storage)[.-].*vendoo|vendoo[^/]*\.(cdn|images)/i.test(lower);
          if (!looksImage || seen.has(url)) return;
          seen.add(url);
          urls.push(url);
      };
      document.querySelectorAll('img').forEach((img) => {
          const w = img.naturalWidth || img.width || 0;
          const h = img.naturalHeight || img.height || 0;
          if (w && h && (w < 64 || h < 64)) return;
          add(img.currentSrc || img.src);
          add(img.getAttribute('data-src'));
          const srcset = img.getAttribute('srcset') || '';
          srcset.split(',').forEach((part) => add(part.trim().split(/\s+/)[0]));
      });
      return urls.slice(0, 20);
  }

  function normalizeScrapedFieldKey(raw) {
      // listings.ebay.categorySpecifics.15687_Unit_Quantity -> "Unit Quantity"
      return String(raw || '')
          .replace(/^[0-9a-f]{8,}_/i, '')
          .replace(/^\d+_/, '')
          .replace(/_/g, ' ')
          .replace(/\s+/g, ' ')
          .trim();
  }

  // eBay puts the name in the input id (15687_Unit_Quantity), Etsy keys its
  // category inputs by bare taxonomy id (148789511893), so the id alone leaves
  // Studio nothing to show but digits. Those keys need the on-page label.
  function scrapedFieldKeyNeedsLabel(fieldKey) {
      return Boolean(fieldKey) && !/[A-Za-z]/.test(fieldKey);
  }

  function scrapedFieldLabel(el) {
      const controlId = el.id || (el.getAttribute && el.getAttribute('name')) || '';
      // Vendoo renders a sibling <label id="<controlId>-label"> for these. Prefer
      // it: on a filled multi-select the parent walk in fieldLabelForControl
      // matches a selected value chip, so Materials comes back as "Polyester".
      const sibling = controlId ? document.getElementById(`${controlId}-label`) : null;
      for (const raw of [sibling && sibling.textContent, fieldLabelForControl(el)]) {
          const label = String(raw || '')
              .replace(/\s+/g, ' ')
              .replace(/\s*\*$/, '')
              .replace(/\s*\((optional|required)\)$/i, '')
              .trim();
          // fieldLabelForControl falls back to the id tail; that is digits again.
          if (label && /[A-Za-z]/.test(label) && label.length <= 60) return label;
      }
      return '';
  }

  function deepMergeListings(base, overlay) {
      const out = base && typeof base === 'object' ? { ...base } : {};
      for (const [marketplace, section] of Object.entries(overlay || {})) {
          if (!section || typeof section !== 'object') continue;
          const current = out[marketplace] && typeof out[marketplace] === 'object' ? { ...out[marketplace] } : {};
          for (const [bucket, fields] of Object.entries(section)) {
              if (!fields || typeof fields !== 'object') continue;
              const bucketOut = current[bucket] && typeof current[bucket] === 'object' ? { ...current[bucket] } : {};
              for (const [key, value] of Object.entries(fields)) {
                  if (!(key in bucketOut) || (value != null && String(value).trim() !== '')) {
                      bucketOut[key] = value;
                  }
              }
              current[bucket] = bucketOut;
          }
          out[marketplace] = current;
      }
      return out;
  }

  function scrapeMarketplaceListingsFromDom() {
      const listings = {};
      const controls = document.querySelectorAll(
          'input[id^="listings."], textarea[id^="listings."], select[id^="listings."], [id^="listings."][role="combobox"], [name^="listings."]'
      );
      for (const el of controls) {
          const id = el.id || el.getAttribute('name') || '';
          const parts = id.split('.');
          if (parts.length < 4 || parts[0] !== 'listings') continue;
          const marketplace = parts[1];
          const bucket = parts[2];
          if (!['overrides', 'marketplaceSpecifics', 'categorySpecifics'].includes(bucket)) continue;
          const fieldKey = normalizeScrapedFieldKey(parts.slice(3).join('.'));
          if (!fieldKey || /image/i.test(fieldKey)) continue;
          if (!listings[marketplace]) listings[marketplace] = {};
          if (!listings[marketplace][bucket]) listings[marketplace][bucket] = {};
          let value = readPersistedControlValue(el);
          if (value && typeof value !== 'boolean' && !Array.isArray(value) && !fieldLooksFilled(el)) value = '';
          // Keep empty strings so Studio Fields can show unfilled optional keys.
          if (!(fieldKey in listings[marketplace][bucket]) || value === true || value === false || (Array.isArray(value) ? value.length : value)) {
              listings[marketplace][bucket][fieldKey] = value;
          }
          if (scrapedFieldKeyNeedsLabel(fieldKey)) {
              if (!listings[marketplace].fieldLabels) listings[marketplace].fieldLabels = {};
              const labelKey = `${bucket}.${fieldKey}`;
              // Several nodes share one key (input, hidden input, value chips).
              // First usable label wins so a later chip cannot overwrite it.
              if (!listings[marketplace].fieldLabels[labelKey]) {
                  const label = scrapedFieldLabel(el);
                  if (label) listings[marketplace].fieldLabels[labelKey] = label;
              }
          }
      }
      return listings;
  }

  function scrapeGeneralDetailsFromDom() {
      const details = {
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
      };
      const controls = document.querySelectorAll(
          'input[id^="generalDetails."], textarea[id^="generalDetails."], select[id^="generalDetails."], [id^="generalDetails."][role="combobox"]'
      );
      for (const el of controls) {
          const id = el.id || '';
          const path = id.slice('generalDetails.'.length);
          if (!path || /image/i.test(path)) continue;
          let value = '';
          if ('value' in el && el.value != null) value = String(el.value).trim();
          if (!value) value = (el.innerText || el.textContent || '').trim();
          if (value && !fieldLooksFilled(el)) value = '';
          const parts = path.split('.');
          let cursor = details;
          for (let i = 0; i < parts.length - 1; i += 1) {
              const part = parts[i];
              if (!cursor[part] || typeof cursor[part] !== 'object') cursor[part] = {};
              cursor = cursor[part];
          }
          const leaf = parts[parts.length - 1];
          if (!(leaf in cursor) || value) cursor[leaf] = value;
      }
      return details;
  }

  async function discoverAllMarketplaceListings(platforms = null) {
      // Read-only: never call fillMarketplaceCategory here. Refresh/GET_VENDOO_ITEM
      // must scrape what's already on the draft — re-selecting category remounts
      // optionals as empty and makes Fields think fills never stuck.
      const list = Array.isArray(platforms) && platforms.length
          ? platforms.map((platform) => String(platform || '').toLowerCase()).filter(Boolean)
          : ['ebay', 'etsy', 'poshmark', 'mercari', 'depop'];
      let listings = {};
      for (const platform of list) {
          try {
              log(`Reading ${platform} form fields (including empty optionals)...`);
              await activateMarketplaceSection(platform);
              await sleep(CONFIG.SLEEP_LONG);
              if (!marketplaceFormMounted(platform)) {
                  warn(`  ${platform}: form did not mount after activate; skipping scrape`);
                  continue;
              }
              if (platform === 'ebay') {
                  // Only wait for optionals when a category is already on the draft.
                  // Re-selecting category is forbidden on refresh (remounts empties).
                  const categoryShown = marketplaceCategoryDisplay('ebay');
                  if (categoryShown) {
                      await waitForEbayOptionalCategoryFields();
                  } else {
                      await expandOptionalFields();
                      await sleep(CONFIG.SLEEP_LONG);
                  }
              } else {
                  await expandOptionalFields();
                  await sleep(CONFIG.SLEEP_LONG);
              }
              listings = deepMergeListings(listings, scrapeMarketplaceListingsFromDom());
              const count = Object.values(listings[platform] || {}).reduce(
                  (sum, bucket) => sum + (bucket && typeof bucket === 'object' ? Object.keys(bucket).length : 0),
                  0
              );
              log(`  ${platform}: ${count} fields`);
          } catch (err) {
              warn(`Discover ${platform} failed: ${err.message}`);
          }
      }
      return listings;
  }

  function marketplaceCategoryDisplay(marketplace) {
      const catBtn = findMarketplaceCategoryControl(marketplace);
      if (!catBtn) return '';
      return readCategoryDisplay(catBtn);
  }

  // Each capture costs ~0.5-1.1s (open, settle, read, Escape). Keep the per-platform
  // budget in step with the DISCOVER_SCHEMA timeout in background.js.
  const MAX_OPTION_CAPTURES_PER_PLATFORM = 12;

  async function collectMarketplaceSchemaFields(marketplace) {
      const fields = [];
      const elements = [];
      const seen = new Set();
      const controls = document.querySelectorAll('input, textarea, select, [role="combobox"]');
      for (const el of controls) {
          if (el.closest && el.closest('#vendoo-debug-box')) continue;
          const type = String(el.type || '').toLowerCase();
          if (['hidden', 'submit', 'button', 'reset', 'file', 'image'].includes(type)) continue;
          if (!isVisibleElement(el)) continue;
          if (!isEnabledField(el)) continue;
          if (!marketplaceFieldNode(el, marketplace) && !isCurrentMarketplaceControl(el)) continue;

          const label = scrapedFieldLabel(el) || fieldLabelForControl(el);
          const key = normalizeFieldKey(label);
          if (!key || seen.has(key)) continue;
          if (isAccountSettingField(key) || isAccountSettingField(label)) continue;
          seen.add(key);
          const nativeSelect = el.tagName === 'SELECT';
          let value = nativeSelect
              ? (el.multiple ? Array.from(el.selectedOptions).map((option) => option.textContent.trim())
                  : (el.value ? el.selectedOptions[0]?.textContent.trim() || '' : ''))
              : readPersistedControlValue(el);
          if (!nativeSelect && typeof value === 'string' && value && !fieldLooksFilled(el)) value = '';
          const described = String(el.getAttribute?.('aria-errormessage') || el.getAttribute?.('aria-describedby') || '')
              .split(/\s+/).map((id) => document.getElementById(id)?.textContent || '').join(' ').trim();
          fields.push({
              label,
              key: el.id || el.name || key,
              type: nativeSelect ? 'select' : (el.getAttribute?.('role') || type || el.tagName.toLowerCase()),
              multiple: Boolean(el.multiple || el.getAttribute?.('aria-multiselectable') === 'true' || isMultiChipField(label, el)),
              options: nativeSelect ? Array.from(el.options).filter((option) => !option.disabled && option.value !== '')
                  .map((option) => ({ label: option.textContent.trim(), value: option.value })) : [],
              options_complete: nativeSelect,
              min: el.getAttribute?.('min'),
              max: el.getAttribute?.('max'),
              max_length: el.getAttribute?.('maxlength'),
              pattern: el.getAttribute?.('pattern'),
              error: el.getAttribute?.('aria-invalid') === 'true'
                  ? (described || 'Form rejected this value') : (el.validationMessage || ''),
              selector: selectorFor(el, ''),
              filled: value !== '' && value != null && (!Array.isArray(value) || value.length > 0),
              value,
              is_dropdown: isDropdownLike(el),
              options_source: nativeSelect ? 'native-select' : 'not-collected',
              required: Boolean(
                  el.required
                  || el.getAttribute?.('aria-required') === 'true'
                  || /\*/.test(label)
                  || /\(required\)/i.test(label)
              ),
          });
          elements.push(el);
      }

      // Second pass: opening a menu mutates the DOM, so only do it once the
      // field list is settled.
      let captured = 0;
      for (let i = 0; i < fields.length; i += 1) {
          const field = fields[i];
          if (!field.is_dropdown || field.options_complete) continue;
          if (captured >= MAX_OPTION_CAPTURES_PER_PLATFORM) {
              field.options_source = 'capture-limit';
              continue;
          }
          const el = elements[i];
          const before = (displayedFieldValue(el) || '').trim();
          const result = await readLiveFieldOptions(el, field.label);
          field.options = result.options;
          field.options_source = result.source;
          if (result.options.length) captured += 1;

          // Opening a menu should never commit a value. If one stuck, the probe
          // is about to save it, so make that loud instead of silent.
          const after = (displayedFieldValue(el) || '').trim();
          if (after !== before) {
              field.value_changed_during_capture = true;
              warn(`${marketplace} ${field.label}: value changed during option capture ("${before}" → "${after}")`);
          }
      }
      await closeOpenMenus();
      if (captured) log(`  ${marketplace}: captured options for ${captured} dropdown(s)`);

      return fields;
  }

  function compareSchemaValues(schema, listing) {
      for (const [marketplace, section] of Object.entries(schema)) {
          const specifics = listing[`${marketplace}_specifics`] || {};
          const source = { ...listing, ...(specifics.category_specifics || {}), ...specifics };
          for (const field of section.fields || []) {
              const key = normalizeFieldKey(field.label);
              const entry = Object.entries(source).find(([name, value]) =>
                  normalizeFieldKey(name) === key && value != null && value !== '' &&
                  (typeof value !== 'object' || Array.isArray(value))
              );
              if (!entry) continue;
              const input = entry[1];
              const expected = mapPatchValue(marketplace, field.label, input);
              field.expected_input = Array.isArray(input) ? input.join(', ') : String(input);
              field.expected = Array.isArray(expected) ? expected.join(', ') : String(expected);
              if (Array.isArray(field.value) || Array.isArray(expected)) {
                  const values = (value) => (Array.isArray(value) ? value : String(value).split(','))
                      .map((item) => String(item).trim().toLowerCase()).sort();
                  field.matches_expected = JSON.stringify(values(field.value)) === JSON.stringify(values(expected));
              } else if (typeof field.value === 'boolean') {
                  field.matches_expected = String(field.value).toLowerCase() === String(expected).toLowerCase();
              } else {
                  field.matches_expected = fieldValuesEqual(field.value, expected);
              }
          }
      }
  }

  async function discoverMarketplaceSchema(data, platforms) {
      const list = Array.isArray(platforms) && platforms.length
          ? platforms.map((platform) => String(platform || '').toLowerCase()).filter(Boolean)
          : ['ebay', 'etsy', 'poshmark', 'mercari', 'depop'];
      const listing = data && typeof data === 'object' ? data : {};
      const allEntries = [];
      const categories = {};
      const schema = {};

      await activateMarketplaceSection('general');
      beginFillLog('general');
      await expandOptionalFields();
      schema.general = {
          category: { path: readCategoryDisplay(findGeneralCategoryControl()), status: 'observed' },
          fields: await collectMarketplaceSchemaFields('general'),
      };

      log(`=== Discovering marketplace schemas after category (${list.join(', ')}) ===`);

      for (const platform of list) {
          beginFillLog(platform);
          try {
              await activateMarketplaceSection(platform);
              await sleep(CONFIG.SLEEP_LONG);

              const catResult = await fillMarketplaceCategory(platform, listing);
              await sleep(CONFIG.SLEEP_LONG);
              const shown = marketplaceCategoryDisplay(platform);
              categories[platform] = {
                  status: catResult?.status || 'skipped',
                  path: shown || '',
              };
              log(`  ${platform} category: ${shown || catResult?.status || 'none'}`);

              if (platform === 'ebay') {
                  await waitForEbayOptionalCategoryFields();
              } else {
                  await expandOptionalFields();
                  await sleep(CONFIG.SLEEP_LONG);
              }

              const fields = await collectMarketplaceSchemaFields(platform);
              for (const field of fields) {
                  if (normalizeFieldKey(field.label) === 'category') continue;
                  recordFill({
                      field: field.label,
                      status: field.filled ? 'filled' : 'new',
                      reason: field.filled
                          ? 'Already has a value'
                          : (field.required
                              ? 'Required field discovered after category select'
                              : 'Discovered on form after category select'),
                      selector: field.selector,
                      value: field.value,
                  });
              }
              schema[platform] = {
                  category: categories[platform],
                  fields,
                  error: !shown || ['failed', 'invalid', 'not_found'].includes(catResult?.status)
                      ? 'Marketplace category selection was not verified' : null,
              };
              log(`  ${platform}: ${fields.length} schema fields`);
          } catch (err) {
              warn(`Discover schema ${platform} failed: ${err.message}`);
              recordFill({ field: 'form', status: 'failed', reason: err.message });
              categories[platform] = categories[platform] || { status: 'failed', path: '', error: err.message };
              schema[platform] = {
                  category: categories[platform],
                  fields: [],
                  error: err.message,
              };
          }
          const logResult = finishFillLog({ skipUnmapped: true });
          allEntries.push(...logResult.entries);
      }

      // Persist category alignments and dismiss overlays so filling_ebay (etc.)
      // can leave the last discovered marketplace (often Depop).
      await closeOpenMenus();
      try {
          const saved = await saveGeneralForm();
          if (!saved?.ok) {
              warn(`Schema discovery save: ${saved?.error || 'failed'}`);
          }
      } catch (err) {
          warn(`Schema discovery save failed: ${err.message}`);
      }

      const failures = Object.entries(schema).filter(([, section]) => section.error || !section.fields.length)
          .map(([platform, section]) => `${platform}: ${section.error || 'No form fields were found'}`);
      return {
          ok: failures.length === 0,
          error: failures.length ? `Category field discovery failed: ${failures.join('; ')}` : null,
          schema,
          categories,
          fill_log: {
              marketplace: allEntries[0]?.marketplace || 'ebay',
              summary: summarizeFillLog(allEntries),
              entries: allEntries,
          },
      };
  }

  async function verifySavedDraft(data, platforms, expectedPhotoCount) {
      const itemId = extractItemId();
      if (!itemId) {
          return {
              ok: false,
              verified: false,
              error: 'No durable Vendoo item ID after save',
              url: window.location.href,
          };
      }
      const ready = await waitForListingFormReady();
      if (!ready.ok) {
          return { ok: false, verified: false, error: ready.error, item_id: itemId, url: window.location.href };
      }
      const listing = { ...(data || {}), _expected_photo_count: expectedPhotoCount || 0 };
      const general = await auditGeneralForm(listing);
      beginFillLog('general');
      await activateMarketplaceSection('general');
      await expandOptionalFields();
      const schema = { general: {
          category: { path: normalizeCategoryDisplay(controlValue(VENDOO_SELECTORS.category)) },
          fields: await collectMarketplaceSchemaFields('general'),
      } };
      const marketplaceResults = {};
      const mismatches = [...(general.mismatches || [])];
      const selected = Array.isArray(platforms) ? platforms.map((item) => String(item || '').toLowerCase()).filter(Boolean) : [];
      for (const platform of selected) {
          const result = await auditMarketplaceForm(listing, platform);
          marketplaceResults[platform] = result;
          beginFillLog(platform);
          await expandOptionalFields();
          await sleep(CONFIG.SLEEP_LONG);
          schema[platform] = {
              category: { path: marketplaceCategoryDisplay(platform) },
              fields: marketplaceFormMounted(platform) ? await collectMarketplaceSchemaFields(platform) : [],
              error: marketplaceFormMounted(platform) ? null : 'Marketplace form did not mount',
          };
          if (!result.ok) mismatches.push(...(result.mismatches || [result.error || `${platform} audit failed`]));
      }
      const photos = scrapeListingImageUrls();
      const statuses = scrapeMarketplaceStatusesFromDom();
      const listed = publishedMarketplaceStatuses(statuses);
      if (listed.length) {
          mismatches.push(`Publication status is not draft: ${listed.map(([id, status]) => `${id}=${status}`).join(', ')}`);
      }
      const verified = mismatches.length === 0;
      compareSchemaValues(schema, listing);
      return {
          ok: verified,
          readback: true,
          schema,
          verified,
          error: verified ? null : mismatches.join('; '),
          mismatches,
          item_id: itemId,
          url: window.location.href,
          photos: photos.length,
          photo_urls: photos,
          statuses,
          general,
          marketplaces: marketplaceResults,
      };
  }

  async function scrapeVendooItem() {
      const itemId = extractItemId();
      if (!itemId) {
          return { ok: false, error: 'This is a new item, not a saved draft', url: window.location.href, item_id: null };
      }
      // Capture live nav statuses before marketplace discovery changes selection.
      const statuses = scrapeMarketplaceStatusesFromDom();
      // General form first, then every marketplace with optionals expanded so
      // Studio gets the live field schema (empty keys included), not only API values.
      await activateMarketplaceSection('general');
      await expandOptionalFields();
      await sleep(CONFIG.SLEEP_LONG);
      const generalDetails = scrapeGeneralDetailsFromDom();
      const listings = await discoverAllMarketplaceListings();
      const form = {
          itemID: itemId,
          generalDetails,
          listings,
          images: scrapeListingImageUrls().map((url) => ({ url })),
          statuses,
      };
      const filled = Object.values(form.generalDetails).some((value) => {
          if (value && typeof value === 'object') return Object.values(value).some(Boolean);
          return Boolean(value);
      });
      const hasListings = Object.keys(form.listings || {}).length > 0;
      return {
          ok: filled || hasListings || Boolean(itemId),
          source: 'form',
          item_id: itemId,
          url: window.location.href,
          form,
          statuses,
      };
  }

  async function clearChipContainer(el) {
      let container = chipFieldRoot(el);
      for (let depth = 0; depth < 4 && container; depth++) {
          let removed = false;
          for (let i = 0; i < 40; i++) {
              const chipDelete = container.querySelector('.MuiChip-deleteIcon, [data-testid*="Cancel"], [aria-label="Remove"], [aria-label="delete"]');
              if (!chipDelete) break;
              chipDelete.dispatchEvent(new MouseEvent('click', { bubbles: true }));
              await sleep(CONFIG.SLEEP_SHORT);
              removed = true;
          }
          if (removed || listedChipValues(el).length === 0) return;
          container = container.parentElement;
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
      await activateMarketplaceSection('general');
      await sleep(CONFIG.SLEEP_LONG);
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
      const raw = queryByRecordedSelector(item.selector);
      const bySelector = visibleDropdownControl(raw) || (raw && isVisibleElement(raw) ? raw : null);
      if (bySelector && isEnabledField(bySelector)) return bySelector;
      const want = normalizeFieldKey(item.field);
      if (!want) return bySelector;
      const marketplace = String(currentFillMarketplace || 'general').toLowerCase();
      const inMarketplace = marketplace && marketplace !== 'general' && marketplace !== 'unknown'
          ? isMarketplaceInput(marketplace)
          : (el) => isCurrentMarketplaceControl(el);
      const controls = document.querySelectorAll('input, textarea, select, [role="combobox"], [role="button"][aria-haspopup]');
      for (const el of controls) {
          if (!inMarketplace(el)) continue;
          const control = visibleDropdownControl(el) || el;
          if (!isEnabledField(control)) continue;
          if (want === 'size' && isSizeScaleControl(control)) continue;
          if (normalizeFieldKey(fieldLabelForControl(control)) === want) return control;
          const token = normalizeFieldKey(controlFieldToken(control) || specificFieldToken(control.id) || specificFieldToken(control.name));
          if (token === want) return control;
      }
      if (marketplace && marketplace !== 'general' && marketplace !== 'unknown') {
          return findInputByExactLabel(item.field, isMarketplaceInput(marketplace)) || bySelector;
      }
      return bySelector;
  }

  async function waitForPatchControl(item) {
      let seen = false;
      for (let attempt = 0; attempt < 8; attempt++) {
          if (attempt === 1 || attempt === 3 || attempt === 5) await expandOptionalFields();
          const el = findControlForPatch(item);
          if (el) {
              seen = true;
              if (isEnabledField(el) && (isVisibleElement(el) || isAttachedElement(el))) return el;
          } else if (!seen && attempt >= 3) {
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
      if (fieldValuesEqual(displayedFieldValue(el), value)) {
          return recordAlreadySet(fieldName, el, selectorText, value);
      }
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
      await clearInput(el);
      setReactValue(el, value);
      await sleep(CONFIG.SLEEP_SHORT);
      log(`  ✓ ${fieldName}: "${value}"`);
      recordFill({ field: fieldName, status: 'filled', selector: selectorText, value });
      return { status: 'filled' };
  }

  async function fillBooleanField(el, value, fieldName) {
      const text = String(value).trim().toLowerCase();
      if (!['true', 'false', 'yes', 'no', '1', '0'].includes(text)) {
          recordFill({ field: fieldName, status: 'invalid', reason: 'A yes/no answer is required', value });
          return;
      }
      const expected = ['true', 'yes', '1'].includes(text);
      if (readPersistedControlValue(el) !== expected) {
          el.click();
          await sleep(CONFIG.SLEEP_SHORT);
      }
      recordFill({ field: fieldName, selector: selectorFor(el, ''), value: expected,
          status: readPersistedControlValue(el) === expected ? 'filled' : 'failed' });
  }

  function reverifyPatchedFields(items) {
      for (const item of items) {
          const fieldName = item.field || 'Field';
          const intended = String(item.value ?? '').trim();
          const entry = [...fillLedger].reverse().find((row) =>
              (item.id && row.id === item.id) ||
              normalizeFieldKey(row.field) === normalizeFieldKey(fieldName)
          );
          if (!entry || entry.status === 'skipped' || entry.status === 'not_found') continue;
          if (/already set/i.test(String(entry.reason || ''))) continue;
          const marketplace = String(item.marketplace || '').toLowerCase();
          let el = findControlForPatch(item);
          if (!el && normalizeFieldKey(fieldName) === 'category' && marketplace && marketplace !== 'general') {
              el = findMarketplaceCategoryControl(marketplace);
          }
          if (!el) {
              entry.status = 'failed';
              entry.reason = 'Field disappeared after fill';
              continue;
          }
          const booleanControl = el.type === 'checkbox' || ['checkbox', 'switch'].includes(el.getAttribute?.('role'));
          if (booleanControl) {
              const expected = ['true', 'yes', '1'].includes(intended.toLowerCase());
              entry.status = readPersistedControlValue(el) === expected ? 'filled' : 'failed';
              continue;
          }
          const shown = normalizeFieldKey(fieldName) === 'category'
              ? readCategoryDisplay(el)
              : (displayedFieldValue(el) || el.innerText || el.textContent || '');
          const matches = normalizeFieldKey(fieldName) === 'category'
              ? categoryDisplayMatches(shown, intended)
              : Boolean(intended && optionMatchesValue(shown, intended, false));
          // Category breadcrumbs can lag one paint behind the control; accept nearby leaf text.
          if (!matches && normalizeFieldKey(fieldName) === 'category' && intended) {
              const leaf = String(intended).split('>').pop().trim();
              if (leaf && categoryDisplayMatches(shown, leaf)) {
                  entry.status = 'filled';
                  continue;
              }
          }
          if (entry.status === 'filled') {
              if (!matches) {
                  entry.status = 'failed';
                  entry.reason = shouldFillAsDropdown(el, fieldName)
                      ? `Dropdown option was not selected (shown: "${String(shown || '').slice(0, 80)}")`
                      : 'Value did not stick';
              }
              continue;
          }
          if (shouldFillAsDropdown(el, fieldName) && !matches) {
              entry.status = 'failed';
              entry.reason = `Dropdown option was not selected (shown: "${String(shown || '').slice(0, 80)}")`;
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
          const formReady = await waitForListingFormReady();
          if (!formReady.ok) {
              return {
                  ok: false,
                  error: formReady.error || 'Vendoo listing form did not finish loading',
                  fill_log: {
                      marketplace: items[0]?.marketplace || 'general',
                      summary: { filled: 0, failed: 0, skipped: 0, not_found: 0 },
                      entries: [],
                  },
              };
          }
          for (const [marketplace, group] of grouped) {
              beginFillLog(marketplace);
              if (marketplace && marketplace !== 'general' && marketplace !== 'unknown') {
                  await activateMarketplaceSection(marketplace);
              } else {
                  await activateMarketplaceSection('general');
              }
              await expandOptionalFields();
              await sleep(CONFIG.SLEEP_LONG * 2);
              let ebayOptionalsReady = marketplace !== 'ebay';
              const pending = group.filter((item) => !isAccountSettingField(item.field));
              pending.sort((left, right) => {
                  const fillPriority = (key) => {
                      if (key === 'category') return 0;
                      if (key === 'size type') return 1;
                      if (key === 'department') return 2;
                      if (key === 'type') return 3;
                      if (key === 'size') return 4;
                      return 10;
                  };
                  return fillPriority(normalizeFieldKey(left.field)) - fillPriority(normalizeFieldKey(right.field));
              });
              for (const item of pending) {
                  currentPatchEntryId = item.id || '';
                  const fieldName = item.field || 'Field';
                  const value = mapPatchValue(marketplace, fieldName, item.value);
                  item.value = value;
                  const fieldKey = normalizeFieldKey(fieldName);
                  if (['publish', 'published', 'publication status', 'listing status', 'listing state'].includes(fieldKey)
                      && !['draft', 'draft listing'].includes(String(value).trim().toLowerCase())) {
                      recordFill({ field: fieldName, status: 'invalid', reason: 'Automation only permits draft status', value });
                      continue;
                  }
                  const isEbayCascade = marketplace === 'ebay' && ['category', 'size type', 'department', 'type', 'size'].includes(fieldKey);
                  if (marketplace === 'ebay' && !isEbayCascade && !ebayOptionalsReady) {
                      await waitForEbayOptionalCategoryFields();
                      ebayOptionalsReady = true;
                  }
                  if (fieldKey === 'category') {
                      if (marketplace === 'general' || marketplace === 'unknown') {
                          const result = await fillCategoryPath({ category_path: value });
                          recordFill({
                              field: fieldName,
                              status: result.ok ? (result.filled ? 'filled' : 'skipped') : 'failed',
                              reason: result.error || (result.already ? 'Already set' : ''),
                              selector: item.selector || VENDOO_SELECTORS.category,
                              value,
                          });
                      } else {
                          await fillMarketplaceCategory(marketplace, { category_path: value });
                      }
                      if (marketplace === 'ebay') {
                          await sleep(CONFIG.SLEEP_LONG * 2);
                          ebayOptionalsReady = false;
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
                  if (el.type === 'checkbox' || ['checkbox', 'switch'].includes(el.getAttribute?.('role'))) {
                      await fillBooleanField(el, value, fieldName);
                  } else if (shouldFillAsDropdown(el, fieldName) || isMultiChipField(fieldName, el)) {
                      await fillDropdownField(el, value, fieldName, false, isMultiChipField(fieldName, el));
                  } else {
                      await fillTextFieldByElement(el, value, fieldName);
                  }
                  if (marketplace === 'ebay' && ['size type', 'department', 'type'].includes(fieldKey)) {
                      await sleep(CONFIG.SLEEP_LONG * 2);
                      ebayOptionalsReady = false;
                  }
              }
              currentPatchEntryId = '';
              reverifyPatchedFields(pending);
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
              uploadStudioPhotos(msg.files || [])
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'FILL_GENERAL') {
              currentRegistrySelectors = msg.registry_selectors || {};
              currentRegistryOptions = msg.registry_options || {};
              fillMainForm(msg.data)
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'SET_GENERAL_CATEGORY') {
              setGeneralCategoryOnly(msg.data)
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

          if (msg.type === 'CHECK_DRAFT_SAFETY') {
              Promise.resolve(checkDraftSafety(msg.platforms || []))
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'FILL_MARKETPLACE') {
              currentRegistrySelectors = msg.registry_selectors || {};
              currentRegistryOptions = msg.registry_options || {};
              fillMarketplaceForm(msg.data, msg.platform)
                  .then(result => sendResponse(result))
                  .catch(err => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'DISCOVER_SCHEMA') {
              discoverMarketplaceSchema(msg.data, msg.platforms)
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
              scrapeVendooItem()
                  .then((result) => sendResponse(result))
                  .catch((err) => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'VERIFY_SAVED_DRAFT') {
              verifySavedDraft(msg.data || {}, msg.platforms || [], msg.expected_photo_count)
                  .then((result) => sendResponse(result))
                  .catch((err) => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'SEARCH_CATEGORIES') {
              searchCategoryPicker(msg.query || '')
                  .then((result) => sendResponse(result))
                  .catch((err) => sendResponse({ ok: false, error: err.message }));
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

          if (msg.type === 'WAIT_FOR_FORM') {
              waitForListingFormReady(msg.timeoutMs || 30000)
                  .then((result) => sendResponse(result))
                  .catch((err) => sendResponse({ ok: false, error: err.message }));
              return true;
          }

          if (msg.type === 'GET_PAGE_STATE') {
              sendResponse({
                  ok: true,
                  url: window.location.href,
                  hasSaveButton: !!document.querySelector('[data-testid="save-item-button"]'),
                  formReady: listingFormMarkersPresent(),
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
