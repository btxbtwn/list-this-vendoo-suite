// Vendoo content script - Speed Optimized Version
// Reduced delays, parallel operations, efficient event dispatch

(function() {
  'use strict';

  const PLATFORM = 'VENDOO';
  const CONTENT_SCRIPT_VERSION = '0.3.0';
  const DEBUG = true;
  let statusBox;

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

  function normalizeEtsyCategorySpecificValue(fieldName, rawValue) {
      if (!rawValue) return rawValue;

      const mappings = ETSY_CATEGORY_VALUE_MAPS[fieldName];
      if (!mappings) {
          return rawValue;
      }

      return mapByIncludes(rawValue, mappings);
  }

  function isVisibleElement(el) {
      return Boolean(el) && (el.offsetParent !== null || el.getClientRects().length > 0);
  }

  function isEtsyCategorySpecificInput(input) {
      return Boolean(input?.id) && input.id.startsWith('listings.etsy.categorySpecifics.');
  }

  function isDepopSpecificInput(input) {
      if (!input) return false;
      const id = String(input.id || '');
      const name = String(input.name || '');
      return id.startsWith('listings.depop.') || name.startsWith('listings.depop.');
  }

  function findInputNearLabel(labelEl, filterFn = () => true) {
      if (!labelEl) return null;

      const forId = labelEl.getAttribute?.('for');
      if (forId) {
          const directInput = document.getElementById(forId);
          if (isVisibleElement(directInput) && filterFn(directInput)) {
              return directInput;
          }
      }

      let container = labelEl;
      for (let depth = 0; depth < 6 && container; depth++) {
          const candidates = Array.from(
              container.querySelectorAll('input:not([type="hidden"]), textarea, select, [role="combobox"]')
          ).filter(candidate => isVisibleElement(candidate) && filterFn(candidate));

          if (candidates.length > 0) {
              return candidates[0];
          }

          container = container.parentElement;
      }

      return null;
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

      if (el !== finalTarget && typeof el.focus === 'function') {
          el.focus();
      }
  }

  // ============================================
  // OPTIMIZED DROPDOWN FILLING
  // ============================================

  async function fillCombobox(el, value, isStrict = false, isMulti = false) {
      if (!value || !el) return;
      
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
      await sleep(CONFIG.SLEEP_MEDIUM);
      
      // Handle native <select> elements
      if (el instanceof HTMLSelectElement) {
          const searchValue = value.toLowerCase().trim();
          const targetOption = Array.from(el.options).find(opt => {
              const optText = opt.textContent.trim().toLowerCase();
              return optText === searchValue || optText.includes(searchValue);
          });
          
          if (targetOption) {
              el.value = targetOption.value;
              el.dispatchEvent(new Event('change', { bubbles: true }));
              await sleep(CONFIG.SLEEP_SHORT);
          } else {
              // Type as fallback
              await clearInput(el);
              setReactValue(el, value);
              await sleep(CONFIG.SLEEP_LONG);
          }
          return;
      }
      
      // Click to open dropdown
      await clickRightEdge(el);
      await sleep(CONFIG.SLEEP_LONG);

      let targetOption = null;
      let attempts = 0;
      const supportsSearch = el instanceof HTMLInputElement ||
          el.getAttribute('role') === 'combobox' ||
          el.classList.contains('react-select__input');
      
      while (!targetOption && attempts < CONFIG.MAX_RETRIES) {
          attempts++;
          const portals = document.querySelectorAll(
              '[role="presentation"], .MuiAutocomplete-popper, [role="listbox"], .react-select__menu, .react-select__menu-list, [class*="menu"], [class*="popover"]'
          );
          
          for (const portal of portals) {
              if (portal.offsetParent === null) continue;
              
              let options = Array.from(portal.querySelectorAll('[role="option"], li, .MuiAutocomplete-option'));
              options = options.filter(o => {
                  const text = (o.innerText || '').toLowerCase();
                  return !text.includes('create your description') && !text.includes('description with ai');
              });
              
              // Try exact match first
              targetOption = options.find(o => o.innerText.trim().toLowerCase() === value.toLowerCase());
              
              // Try includes match
              if (!targetOption && !isStrict) {
                  targetOption = options.find(o => 
                      o.innerText.trim().toLowerCase().includes(value.toLowerCase())
                  );
              }
              
              if (targetOption) break;
          }

          if (!targetOption && supportsSearch) {
              el.focus();
              await clearInput(el);
              setReactValue(el, value);
              await sleep(CONFIG.SLEEP_MEDIUM);
          }
          
          if (!targetOption && attempts < CONFIG.MAX_RETRIES) {
              await sleep(CONFIG.SLEEP_RETRY);
          }
      }

      if (targetOption) {
          const mouseEventOptions = { bubbles: true, cancelable: true, view: window };
          targetOption.dispatchEvent(new MouseEvent('mousedown', mouseEventOptions));
          targetOption.dispatchEvent(new MouseEvent('mouseup', mouseEventOptions));
          targetOption.click();
          await sleep(CONFIG.SLEEP_MEDIUM);
      } else {
          // Fallback: type the value
          await clearInput(el);
          setReactValue(el, value);
          await sleep(CONFIG.SLEEP_LONG);
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          await sleep(CONFIG.SLEEP_MEDIUM);
      }
      
      if (isMulti) {
          await sleep(CONFIG.SLEEP_MEDIUM);
          if (el.value) await clearInput(el);
      }
  }

  // ============================================
  // FIELD FILLING FUNCTIONS
  // ============================================

  async function fillTextField(selector, value, fieldName) {
      if (value === null || value === undefined) return;
      if (typeof value === 'string' && value.trim() === '') return;
      
      const el = resolveWithRegistry(selector, fieldName);
      if (!el) {
          warn(`${fieldName}: Element not found`);
          return;
      }
      
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
      await clearInput(el);
      setReactValue(el, value);
      await sleep(CONFIG.SLEEP_SHORT);
      log(`  ✓ ${fieldName}: "${value}"`);
  }

  async function fillDropdownField(selectorOrEl, value, fieldName, isStrict = false, isMulti = false) {
      if (value === null || value === undefined) return;
      if (typeof value === 'string' && value.trim() === '') return;
      
      let el;
      if (typeof selectorOrEl === 'string') {
          el = resolveWithRegistry(selectorOrEl, fieldName);
          if (!el) {
              warn(`${fieldName}: Element not found`);
              return;
          }
      } else if (selectorOrEl instanceof Element) {
          el = selectorOrEl;
      } else {
          return;
      }
      
      log(`Filling ${fieldName}...`);
      await fillCombobox(el, value, isStrict, isMulti);
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

  async function fillCategoryPath(data) {
      const categoryPath = data.category_path || '';
      if (!categoryPath) return { ok: true, filled: false };

      log(`Setting category: ${categoryPath}`);

      const segments = categoryPath.split('>').map(s => s.trim()).filter(Boolean);
      const department = normalizeText(data.department || data.ebay_specifics?.department);
      const lastSegment = normalizeText(segments[segments.length - 1]);
      if (department === 'women' && lastSegment === 'shirts & blouses') {
          log('Normalizing General category "Shirts & Blouses" to Vendoo category "Tops"');
          segments[segments.length - 1] = 'Tops';
      }
      if (segments.length === 0) return { ok: true, filled: false };

      const catBtn = document.querySelector('#categoryV2, [role="category-input"]');
      if (!catBtn) {
          warn('Category button #categoryV2 not found');
          return { ok: false, filled: false, error: 'Category button not found' };
      }

      log('Opening category selector...');
      catBtn.scrollIntoView({ block: 'center', behavior: 'instant' });
      await sleep(CONFIG.SLEEP_MEDIUM);
      catBtn.click();
      await sleep(CONFIG.SLEEP_LONG * 2);

      for (let i = 0; i < segments.length; i++) {
          const segment = segments[i];
          log(`  Drilling into: "${segment}" (${i + 1}/${segments.length})`);

          let targetOption = null;
          const lowerSegment = segment.toLowerCase();

          for (let attempt = 0; attempt < 10 && !targetOption; attempt++) {
              await sleep(CONFIG.SLEEP_LONG);
              const allOptions = document.querySelectorAll('[role="option"]');
              for (const opt of allOptions) {
                  if (opt.offsetParent === null) continue;
                  const text = (opt.innerText || opt.textContent || '').trim();
                  if (text.toLowerCase() === lowerSegment) {
                      targetOption = opt;
                      break;
                  }
              }
          }

          if (!targetOption) {
              warn(`Category option "${segment}" not found`);
              return { ok: false, filled: false, error: `Category option "${segment}" not found` };
          }

          log(`  Clicking: "${targetOption.innerText.trim()}"`);
          targetOption.scrollIntoView({ block: 'center', behavior: 'instant' });
          await sleep(CONFIG.SLEEP_SHORT);
          targetOption.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
          targetOption.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
          targetOption.click();
          await sleep(CONFIG.SLEEP_LONG * 2);
      }

      await sleep(CONFIG.SLEEP_LONG * 2);

      const searchInput = document.querySelector('input[role="category-search-field"]');
      if (searchInput && document.contains(searchInput)) {
          log('Category modal still open, searching for terminal child...');

          const children = [];
          const allOptions = document.querySelectorAll('[role="option"]');
          for (const opt of allOptions) {
              if (opt.offsetParent === null) continue;
              const text = (opt.innerText || opt.textContent || '').trim();
              if (text) children.push(text);
          }

          log(`  Visible children: ${JSON.stringify(children)}`);

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

              let targetText = null;
              if (targetType) {
                  for (const child of children) {
                      if (child.toLowerCase() === targetType) {
                          targetText = child;
                          break;
                      }
                  }
              }

              if (!targetText) {
                  for (const child of children) {
                      if (typeLower && child.toLowerCase().includes(typeLower)) {
                          targetText = child;
                          break;
                      }
                  }
              }

              if (!targetText) {
                  for (const child of children) {
                      if (child.toLowerCase().includes('t-shirt') || child.toLowerCase().includes('shirt')) {
                          targetText = child;
                          break;
                      }
                  }
              }

              if (targetText) {
                  log(`  Selecting terminal child: "${targetText}"`);
                  const childOption = [...allOptions].find(o =>
                      (o.innerText || o.textContent || '').trim() === targetText && o.offsetParent !== null
                  );
                  if (childOption) {
                      childOption.scrollIntoView({ block: 'center', behavior: 'instant' });
                      await sleep(CONFIG.SLEEP_SHORT);
                      childOption.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                      childOption.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                      childOption.click();
                      await sleep(CONFIG.SLEEP_LONG * 2);
                  }
              } else {
                  warn(`No terminal child match. Children: ${JSON.stringify(children)}`);
              }
          }
      }

      await sleep(CONFIG.SLEEP_LONG);

      const searchInputAfter = document.querySelector('input[role="category-search-field"]');
      if (searchInputAfter && document.contains(searchInputAfter)) {
          warn('Category modal still open after selecting all segments');
          return { ok: false, filled: false, error: 'Category modal did not close after selection' };
      }

      const catBtnText = (catBtn.innerText || catBtn.textContent || '').trim();
      log(`Category selected. Button text: "${catBtnText}"`);

      if (!catBtnText || catBtnText.toLowerCase().includes('click to select')) {
          return { ok: false, filled: false, error: 'Category button not updated after selection' };
      }

      return { ok: true, filled: true, result: catBtnText };
  }

  // ============================================
  // MAIN VENDOO FORM FILLER - OPTIMIZED
  // ============================================

  async function fillMainForm(data) {
      log('=== Filling Main Vendoo Form ===');

      // Category must be set FIRST (before size/sizeType which depend on it)
      if (data.category_path) {
          const catResult = await fillCategoryPath(data);
          if (!catResult.ok) {
              return { ok: false, error: catResult.error || 'Category selection failed' };
          }
          await sleep(CONFIG.SLEEP_LONG);
      }
      
      // Text fields (parallel)
      const textFields = [
          {fn: fillTextField, args: [VENDOO_SELECTORS.title, data.title, 'Title']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.description, data.description, 'Description']},
          {fn: fillTextField, args: [VENDOO_SELECTORS.zipCode, data.zipCode || '70125', 'Zip Code']},
      ];
      await batchFillFields(textFields);
      
      // Condition mapping
      if (data.condition) {
          let condVal = data.condition;
          if (condVal.toLowerCase().includes('used') || condVal.toLowerCase() === 'good') condVal = 'Pre-Owned - Good';
          if (condVal.toLowerCase().includes('excellent')) condVal = 'Pre-Owned - Excellent';
          if (condVal.toLowerCase().includes('fair')) condVal = 'Pre-Owned - Fair';
          if (condVal.toLowerCase().includes('new') && !condVal.toLowerCase().includes('imperfections')) condVal = 'New Without Tags/Box';
          await fillDropdownField(VENDOO_SELECTORS.condition, condVal, 'Condition', true);
      }
      
      // Dropdown fields (sequential for stability)
      await fillDropdownField(VENDOO_SELECTORS.brand, data.brand, 'Brand');
      await fillDropdownField(VENDOO_SELECTORS.primaryColor, data.primaryColor || data.color, 'Primary Color');
      await fillDropdownField(VENDOO_SELECTORS.secondaryColor, data.secondaryColor, 'Secondary Color');
      // Size fields (sizeType BEFORE size - size options depend on sizeType)
      if (data.sizeType) {
          await fillDropdownField(VENDOO_SELECTORS.sizeType, data.sizeType, 'Size Type', true);
          await sleep(CONFIG.SLEEP_LONG);
      }
      if (data.size) {
          const sizeEl = document.querySelector(VENDOO_SELECTORS.size);
          if (sizeEl) {
              await fillDropdownField(sizeEl, data.size, 'Size', true);
          } else {
              warn('Size input not found after category');
          }
      }
      
      // Multi-value fields
      if (data.tags) {
          const tagsEl = document.querySelector(VENDOO_SELECTORS.tags);
          if (tagsEl) {
              const tags = Array.isArray(data.tags) ? data.tags : data.tags.split(',').map(t => t.trim());
              for (const tag of tags) await fillCombobox(tagsEl, tag, false, true);
          }
      }
      
      if (data.labels) {
          const labelsEl = document.querySelector(VENDOO_SELECTORS.labels);
          if (labelsEl) {
              const labels = Array.isArray(data.labels) ? data.labels : data.labels.split(',').map(l => l.trim());
              for (const label of labels) await fillCombobox(labelsEl, label, false, true);
          }
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
      return { ok: true };
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

  async function fillEbayForm(data) {
      log('Filling eBay form...');

      // Parallel fill for independent fields
      await Promise.all([
          fillDropdownField('#listings\\.ebay\\.overrides\\.brand', data.brand, 'eBay Brand'),
          fillDropdownField('#listings\\.ebay\\.overrides\\.primaryColor', data.primaryColor || data.color, 'eBay Color'),
          fillTextField('#listings\\.ebay\\.overrides\\.quantity', data.quantity, 'eBay Quantity'),
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
              'vintage': 'Vintage', 'handmade': 'Handmade', 'personalize': 'Personalize',
              'garmentCare': 'Garment Care', 'unitQuantity': 'Unit Quantity',
              'unitType': 'Unit Type', 'mpn': 'MPN', 'upc': 'UPC',
              'character': 'Character', 'characterFamily': 'Character Family',
              'performanceActivity': 'Performance Activity', 'yearManufactured': 'Year Manufactured',
              'collarStyle': 'Collar Style', 'rise': 'Rise', 'inseam': 'Inseam',
              'waist': 'Waist'
          };
          
          // Label-based patterns for fallback when ID matching fails
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
          
          // Find category fields
          let allInputs = Array.from(document.querySelectorAll('input[id^="listings\\.ebay\\.categorySpecifics\\."], select[id^="listings\\.ebay\\.categorySpecifics\\."]'));
          log(`Found ${allInputs.length} category specific fields`);
          
          for (const [key, value] of Object.entries(data.ebay_specifics)) {
              if (!value) continue;
              
              const fieldName = fieldNameMap[key] || key;
              let foundEl = null;
              
              for (const input of allInputs) {
                  const idLower = input.id.toLowerCase();
                  const fieldNameLower = fieldName.toLowerCase();
                  const afterLastDot = input.id.split('.').pop().toLowerCase();
                  
                  // Pattern 1: Exact match on afterLastDot (e.g., "color" → "color")
                  if (afterLastDot === fieldNameLower) {
                      foundEl = input;
                      break;
                  }
                  
                  // Pattern 2: categoryId_FieldName with underscore separator
                  // e.g., "15687_features" matches "Features", "15687_unit quantity" matches "Unit Quantity"
                  // The afterLastDot is "15687_unit quantity" — check if it ends with "_fieldName"
                  // Also handle IDs that use underscores instead of spaces (15687_Unit_Quantity)
                  if (afterLastDot.includes('_') && (
                      afterLastDot.endsWith('_' + fieldNameLower) ||
                      afterLastDot.endsWith('_' + fieldNameLower.replace(/\s+/g, '_'))
                  )) {
                      foundEl = input;
                      break;
                  }
                  
                  // Pattern 3: Full ID ends with _fieldName or .fieldName
                  if (idLower.endsWith('_' + fieldNameLower) || 
                      idLower.endsWith('.' + fieldNameLower) ||
                      new RegExp(`[._]${fieldNameLower.replace(/\s+/g, '\\s*')}$`, 'i').test(input.id)) {
                      foundEl = input;
                      break;
                  }
              }
              
              if (foundEl) {
                  let valuesToFill = Array.isArray(value) ? value : 
                      (typeof value === 'string' && value.includes(',')) ? 
                      value.split(',').map(v => v.trim()) : [value];
                  
                  // Use strict matching for size fields to avoid "S" matching "3XS"
                  const isSizeField = key.toLowerCase().includes('size');
                  const shouldBeStrict = isSizeField;
                  
                  if (valuesToFill.length > 1) {
                      for (const item of valuesToFill) {
                          await fillDropdownField(foundEl, item, key, shouldBeStrict, true);
                          await sleep(CONFIG.SLEEP_MEDIUM);
                      }
                  } else {
                      await fillDropdownField(foundEl, valuesToFill[0], key, shouldBeStrict, false);
                  }
              } else {
                  // Fallback: try label-based matching for eBay category specifics
                  const patterns = fieldLabelPatterns[key] || [normalizeText(fieldName)];
                  const ebayCategoryInputs = allInputs.filter(i => 
                      i.id && i.id.includes('categorySpecifics')
                  );
                  const labelEl = findInputByLabelPatterns(patterns) || 
                      findInputByContext(ebayCategoryInputs, patterns);
                  
                  if (labelEl) {
                      let valuesToFill = Array.isArray(value) ? value : 
                          (typeof value === 'string' && value.includes(',')) ? 
                          value.split(',').map(v => v.trim()) : [value];
                      
                      const isSizeField = key.toLowerCase().includes('size');
                      const shouldBeStrict = isSizeField;
                      
                      log(`  Found ${key} via label fallback`);
                      if (valuesToFill.length > 1) {
                          for (const item of valuesToFill) {
                              await fillDropdownField(labelEl, item, key, shouldBeStrict, true);
                              await sleep(CONFIG.SLEEP_MEDIUM);
                          }
                      } else {
                          await fillDropdownField(labelEl, valuesToFill[0], key, shouldBeStrict, false);
                      }
                  } else {
                      warn(`Could not find field for ${key}`);
                  }
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
      
      // Parallel independent fields
      await Promise.all([
          fillDropdownField('#listings\\.etsy\\.overrides\\.primaryColor', data.primaryColor || data.color, 'Etsy Color'),
          fillTextField('#listings\\.etsy\\.overrides\\.quantity', data.quantity, 'Etsy Quantity'),
          fillTextField('#listings\\.etsy\\.overrides\\.price', data.price, 'Etsy Price'),
      ]);
      
      if (data.etsy_specifics) {
          await expandOptionalFields();
          await sleep(CONFIG.SLEEP_LONG);
          
          // Marketplace specifics (parallel)
          await Promise.all([
              fillDropdownField('#listings\\.etsy\\.marketplaceSpecifics\\.whoMade', specs.who_made || specs.whoMade, 'Who Made'),
              fillDropdownField('#listings\\.etsy\\.marketplaceSpecifics\\.whatIsIt', specs.what_is || specs.whatIsIt, 'What Is It'),
              fillDropdownField('#listings\\.etsy\\.marketplaceSpecifics\\.whenMade', normalizedWhenMade, 'When Made'),
          ]);
          
          // Tags and materials
          if (specs.tags || specs.materials) {
              const tagsEl = document.querySelector('#listings\\.etsy\\.marketplaceSpecifics\\.tags');
              const materialsEl = document.querySelector('#listings\\.etsy\\.marketplaceSpecifics\\.materials');
              
              if (tagsEl && specs.tags) {
                  const tags = Array.isArray(specs.tags) ? specs.tags : specs.tags.split(',').map(t => t.trim());
                  for (const tag of tags) await fillCombobox(tagsEl, tag, false, true);
              }
              
              if (materialsEl && specs.materials) {
                  const materials = Array.isArray(specs.materials) ? specs.materials : specs.materials.split(',').map(m => m.trim());
                  for (const material of materials) await fillCombobox(materialsEl, material, false, true);
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
              'materials': ['materials', 'material']
          };
          
          // Get all category specific inputs
          const etsyCategoryInputs = Array.from(document.querySelectorAll(
              '[id^="listings\.etsy\.categorySpecifics\."], [name^="listings.etsy.categorySpecifics."]'
          )).filter(isVisibleElement);
          const categorySpecifics = { ...(specs.category_specifics || {}) };
          const rootLevelEtsyCategoryFields = [
              'sleeveLength', 'neckline', 'clothingStyle', 'closure', 'collarStyle',
              'pattern', 'occasion', 'holiday', 'sustainability', 'fabric', 'graphic'
          ];

          for (const fieldName of rootLevelEtsyCategoryFields) {
              if (specs[fieldName] && categorySpecifics[fieldName] == null) {
                  categorySpecifics[fieldName] = specs[fieldName];
              }
          }

          const etsyFallbackCategoryFields = {
              closure: ebaySpecifics.closure,
              collarStyle: ebaySpecifics.collarStyle || ebaySpecifics.collar_style || ebaySpecifics.neckline,
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
              const valuesToFill = Array.isArray(rawValue)
                  ? rawValue.map(value => normalizeEtsyCategorySpecificValue(jsonField, value))
                  : (typeof rawValue === 'string' && rawValue.includes(','))
                      ? rawValue.split(',').map(value => normalizeEtsyCategorySpecificValue(jsonField, value.trim())).filter(Boolean)
                      : [normalizeEtsyCategorySpecificValue(jsonField, rawValue)];

              const foundEl = findInputByLabelPatterns(labelPatterns, isEtsyCategorySpecificInput) ||
                  findInputByContext(etsyCategoryInputs, labelPatterns);
              
              if (foundEl) {
                  const isMulti = jsonField === 'materials' || valuesToFill.length > 1;
                  log(`  Filling Etsy ${jsonField}: ${valuesToFill.join(', ')}`);
                  for (const value of valuesToFill) {
                      await fillDropdownField(foundEl, value, jsonField, false, isMulti);
                      if (isMulti) await sleep(CONFIG.SLEEP_MEDIUM);
                  }
              } else {
                  warn(`  Could not find Etsy category field for ${jsonField}`);
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
              }
          }
      }
      
  }

  async function fillPoshmarkForm(data) {
      log('Filling Poshmark form...');
      
      await Promise.all([
          fillDropdownField('#listings\\.poshmark\\.overrides\\.condition', data.condition, 'Poshmark Condition'),
          fillDropdownField('#listings\\.poshmark\\.overrides\\.brand', data.brand, 'Poshmark Brand'),
          fillDropdownField('#listings\\.poshmark\\.overrides\\.primaryColor', data.primaryColor || data.color, 'Poshmark Color'),
          fillTextField('#listings\\.poshmark\\.overrides\\.quantity', data.quantity, 'Poshmark Quantity'),
          fillTextField('#listings\\.poshmark\\.overrides\\.price', data.price, 'Poshmark Price'),
      ]);
      
      if (data.poshmark_specifics) {
          await fillTextField('#listings\\.poshmark\\.marketplaceSpecifics\\.originalPrice', data.poshmark_specifics.originalPrice, 'Original Price');
      }
      
  }

  async function fillMercariForm(data) {
      log('Filling Mercari form...');
      
      await Promise.all([
          fillDropdownField('#listings\\.mercari\\.overrides\\.condition', data.condition, 'Mercari Condition'),
          fillDropdownField('#listings\\.mercari\\.overrides\\.brand', data.brand, 'Mercari Brand'),
          fillTextField('#listings\\.mercari\\.overrides\\.quantity', data.quantity, 'Mercari Quantity'),
          fillTextField('#listings\\.mercari\\.overrides\\.price', data.price, 'Mercari Price'),
      ]);
      
      const shippingEl = document.querySelector('#listings\\.mercari\\.marketplaceSpecifics\\.shipping\\.carrierId');
      if (shippingEl) {
          const currentVal = (shippingEl.value || '').trim().toLowerCase();
          if (!currentVal.includes('usps ground advantage')) {
              log('Setting Mercari shipping to USPS Ground Advantage');
              await fillDropdownField(shippingEl, 'USPS Ground Advantage', 'Shipping Label', false);
          } else {
              log('Mercari shipping already USPS Ground Advantage');
          }
      } else {
          warn('Mercari shipping carrier field not found');
      }
      
  }

  async function fillDepopForm(data) {
      log('Filling Depop form...');
      
      await Promise.all([
          fillDropdownField('#listings\\.depop\\.overrides\\.condition', data.condition, 'Depop Condition'),
          fillDropdownField('#listings\\.depop\\.overrides\\.primaryColor', data.primaryColor || data.color, 'Depop Color'),
          fillTextField('#listings\\.depop\\.overrides\\.quantity', data.quantity, 'Depop Quantity'),
          fillTextField('#listings\\.depop\\.overrides\\.price', data.price, 'Depop Price'),
      ]);

      const depopBrandEl = document.querySelector('#listings\\.depop\\.overrides\\.brand');
      if (depopBrandEl && !depopBrandEl.value?.trim()) {
          log('Depop Brand is blank, selecting Other');
          await fillDropdownField(depopBrandEl, 'Other', 'Depop Brand', true);
      }
      
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
          
          // Marketplace specifics (parallel)
          await Promise.all([
              fillDropdownField(findDepopField(['source'], '#listings\\.depop\\.marketplaceSpecifics\\.source'), specs.source, 'Source'),
              fillDropdownField(findDepopField(['age'], '#listings\\.depop\\.marketplaceSpecifics\\.age'), specs.age, 'Age'),
          ]);
          
          // Style (multi-value)
          if (specs.style) {
              const styles = Array.isArray(specs.style) ? specs.style : specs.style.split(',').map(s => s.trim());
              const styleEl = findDepopField(['style'], '#listings\\.depop\\.marketplaceSpecifics\\.style');
              if (styleEl) {
                  log(`Filling ${styles.length} style tags...`);
                  for (const style of styles) await fillCombobox(styleEl, style, false, true);
              } else {
                  warn('Style field not found for Depop');
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
              } else {
                  warn('Occasion field not found for Depop');
              }
          }

          const materialData = specs.material || data.ebay_specifics?.material || data.ebay_specifics?.fabricType;

          if (specs.size_grouping || materialData) {
              log('Filling Depop category specifics...');
          }

          if (specs.size_grouping) {
              const sizeGroupingEl = findDepopField(
                  ['size grouping', 'size group', 'body fit'],
                  '#listings\\.depop\\.categorySpecifics\\.sizeGrouping'
              );
              if (sizeGroupingEl) {
                  await fillDropdownField(sizeGroupingEl, specs.size_grouping, 'Size Grouping');
              } else {
                  warn('Size Grouping field not found for Depop');
              }
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
              } else {
                  warn('Material field not found for Depop');
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
      log(`Filling ${platform} marketplace...`);

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
      }

      return { ok: true };
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

  // ============================================
  // INIT
  // ============================================

  function init() {
      log(`✓ Content script loaded on ${window.location.hostname}`);
      
      chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
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
                  .then(() => sendResponse({ ok: true }))
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
      });
  }

  if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
  } else {
      init();
  }

})();
