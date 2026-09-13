// Popup script - handles JSON input and triggers fill flow

const SAMPLE_JSON = {
  "title": "Vintage 90s Graphic T-Shirt Single Stitch Made in USA Cotton XL",
  "description": "Awesome vintage 90s graphic tee. Single stitch sleeves and hem. Made in USA. Great fade and wear.\n\nCondition: Good vintage condition. Soft and worn in.\n\nSize: XL\nMeasurements:\n- Pit to pit: 23\"\n- Length: 27\"\n\nShips fast!",
  "price": 45.00,
  "cost": 5.00,
  "quantity": 1,
  
  "brand": "Hanes",
  "condition": "Good",
  "primaryColor": "Black",
  "secondaryColor": "Red",
  
  "department": "Men",
  "sizeType": "Regular",
  "size": "XL",
  "size_us": "XL",
  
  "tags": ["vintage", "90s", "single stitch", "graphic tee", "streetwear"],
  "labels": ["To List"],
  "weight_lb": 0,
  "weight_oz": 8,
  
  "ebay_specifics": {
    "type": "T-Shirt",
    "department": "Men",
    "sizeType": "Regular",
    "size": "XL",
    "brand": "Hanes",
    "color": "Black",
    "material": "Cotton",
    "sleeveLength": "Short Sleeve",
    "neckline": "Crew Neck",
    "fit": "Regular",
    "pattern": "Solid",
    "theme": "90s, Vintage, USA",
    "features": "Single Stitch, Graphic Print, Preshrunk",
    "character": "N/A",
    "characterFamily": "N/A",
    "occasion": "Casual",
    "season": "Summer",
    "vintage": "Yes",
    "countryOfOrigin": "United States",
    "garmentCare": "Machine Washable",
    "handmade": "No",
    "personalize": "No",
    "unitQuantity": "1",
    "unitType": "Unit",
    "yearManufactured": "1990-1999"
  },
  "depop_specifics": {
    "source": "Preloved",
    "age": "90s",
    "style": "Streetwear",
    "material": "Cotton",
    "occasion": "Casual"
  },
  "etsy_specifics": {
    "who_made": "Another company or person",
    "what_is": "A finished product",
    "when_made": "1990s",
    "section": "T-Shirts",
    "materials": ["Cotton"],
    "tags": ["vintage", "90s", "graphic tee"],
    "category_specifics": {
      "clothingStyle": "Streetwear",
      "sleeveLength": "Short Sleeve",
      "neckline": "Crew Neck",
      "graphic": "Sports & fitness",
      "fabricPattern": "Solid",
      "size": "L"
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  // ALL element references at the TOP
  const jsonInput = document.getElementById('jsonInput');
  const startBtn = document.getElementById('startBtn');
  const startEbayBtn = document.getElementById('startEbayBtn');
  const startEtsyBtn = document.getElementById('startEtsyBtn');
  const startPoshmarkBtn = document.getElementById('startPoshmarkBtn');
  const startMercariBtn = document.getElementById('startMercariBtn');
  const startDepopBtn = document.getElementById('startDepopBtn');
  const loadSampleBtn = document.getElementById('loadSampleBtn');
  const diagnoseBtn = document.getElementById('diagnoseBtn');
  const status = document.getElementById('status');
  const debugLog = document.getElementById('debugLog');
  const debugDetails = document.querySelector('.minimal-section');
  const vendooLabelsInput = document.getElementById('vendooLabelsInput');
  const cogInput = document.getElementById('cogInput');
  const packageDimsInput = document.getElementById('packageDimsInput');
  const studioStatusText = document.getElementById('studioStatusText');
  const studioJobInfo = document.getElementById('studioJobInfo');
  const studioJobStep = document.getElementById('studioJobStep');
  const openStudioBtn = document.getElementById('openStudioBtn');
  const importStudioBtn = document.getElementById('importStudioBtn');

  function currentVendooItemId(url) {
    const match = String(url || '').match(/\/item\/([^/?]+)/);
    if (!match || match[1] === 'new') return '';
    return match[1];
  }

  function updateImportButton(connected) {
    if (!importStudioBtn) return;
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const itemId = currentVendooItemId(tabs[0]?.url);
      const canImport = Boolean(connected && itemId);
      importStudioBtn.style.display = canImport ? 'block' : 'none';
      importStudioBtn.disabled = !canImport;
    });
  }

  function pollStudioStatus() {
    chrome.runtime.sendMessage({ type: 'GET_STUDIO_STATUS' }, (resp) => {
      if (chrome.runtime.lastError) return;
      if (!resp) return;
      if (resp.connected) {
        studioStatusText.textContent = 'Studio: Connected';
        studioStatusText.style.color = '#4caf50';
      } else {
        studioStatusText.textContent = 'Studio: Disconnected';
        studioStatusText.style.color = '#999';
      }
      if (resp.active_job_id) {
        studioJobInfo.style.display = 'block';
        studioJobStep.textContent = resp.active_job_step || 'processing';
      } else {
        studioJobInfo.style.display = 'none';
      }
      updateImportButton(Boolean(resp.connected));
    });
  }

  pollStudioStatus();
  setInterval(pollStudioStatus, 5000);

  if (openStudioBtn) {
    openStudioBtn.addEventListener('click', () => {
      chrome.runtime.sendMessage({ type: 'OPEN_STUDIO' });
    });
  }

  if (importStudioBtn) {
    importStudioBtn.addEventListener('click', () => {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        const tabId = tabs[0]?.id;
        if (!tabId) {
          showStatus('error', 'No active tab found');
          return;
        }
        importStudioBtn.disabled = true;
        showStatus('info', 'Importing listing into Studio...');
        chrome.runtime.sendMessage({ type: 'IMPORT_VENDOO_LISTING', tabId }, (resp) => {
          importStudioBtn.disabled = false;
          if (chrome.runtime.lastError) {
            showStatus('error', chrome.runtime.lastError.message);
            return;
          }
          if (!resp?.ok) {
            showStatus('error', resp?.error || 'Import failed');
            return;
          }
          const photoNote = resp.photo_count ? ` • ${resp.photo_count} photos` : '';
          showStatus('success', `${resp.reused ? 'Updated' : 'Imported'} ${resp.listing_title || 'listing'} in Studio${photoNote}`);
          if (Array.isArray(resp.photo_warnings) && resp.photo_warnings.length) {
            log(resp.photo_warnings.join('\n'));
          }
        });
      });
    });
  }

  function log(msg) {
    const time = new Date().toLocaleTimeString();
    debugLog.textContent += `\n[${time}] ${msg}`;
    debugLog.scrollTop = debugLog.scrollHeight;
  }

  function showStatus(type, message) {
    status.className = 'status ' + type;
    status.textContent = message;
    status.style.display = 'block';
  }

  function setDiagnoseState(running) {
    if (!diagnoseBtn) return;
    diagnoseBtn.disabled = running;
    diagnoseBtn.textContent = running ? 'Diagnosing...' : 'Diagnose Page';
  }

  function stripCodeFences(text) {
    const trimmed = String(text || '').trim();
    if (!trimmed.startsWith('```')) {
      return trimmed;
    }

    return trimmed
      .replace(/^```(?:json)?\s*/i, '')
      .replace(/\s*```$/, '')
      .trim();
  }

  function escapeLiteralNewlinesInStrings(text) {
    const normalized = String(text || '').replace(/\r\n?/g, '\n');
    let output = '';
    let inString = false;
    let escaping = false;

    for (const char of normalized) {
      if (!inString) {
        if (char === '"') {
          inString = true;
        }
        output += char;
        continue;
      }

      if (escaping) {
        output += char;
        escaping = false;
        continue;
      }

      if (char === '\\') {
        output += char;
        escaping = true;
        continue;
      }

      if (char === '"') {
        output += char;
        inString = false;
        continue;
      }

      if (char === '\n') {
        output += '\\n';
        continue;
      }

      output += char;
    }

    return output;
  }

  function parseListingJson(text) {
    const originalText = String(text || '').trim();
    const cleanedText = stripCodeFences(originalText)
      .replace(/[\u201C\u201D]/g, '"')
      .replace(/[\u2018\u2019]/g, "'")
      .replace(/\u00A0/g, ' ');

    if (!cleanedText) {
      throw new Error('Paste JSON first');
    }

    try {
      return { data: JSON.parse(cleanedText), wasNormalized: cleanedText !== originalText };
    } catch (initialError) {
      const escapedText = escapeLiteralNewlinesInStrings(cleanedText);
      if (escapedText === cleanedText) {
        throw initialError;
      }

      return {
        data: JSON.parse(escapedText),
        wasNormalized: true
      };
    }
  }

  function getListingData({ reformatInput = false } = {}) {
    const parsed = parseListingJson(jsonInput.value);
    if (reformatInput && parsed.wasNormalized) {
      jsonInput.value = JSON.stringify(parsed.data, null, 2);
      saveState();
    }
    return parsed.data;
  }

  function enableAllButtons() {
    const ids = ['startBtn', 'startEbayBtn', 'startEtsyBtn', 'startPoshmarkBtn', 'startMercariBtn', 'startDepopBtn'];
    ids.forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = false;
    });
  }

  // Helper: Apply UI overrides
  function applyOverrides(listingData) {
    const packageDims = packageDimsInput.value.trim();
    if (packageDims) {
      listingData.package_dimensions_in = packageDims;
    }
    return listingData;
  }

  // Save state
  function saveState() {
    const jsonText = jsonInput.value.trim();
    let dataToSave = null;
    if (jsonText) {
      try { dataToSave = parseListingJson(jsonText).data; } catch (e) {}
    }
    
    chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
      const currentTabId = tabs[0]?.id;
      if (currentTabId) {
        const storageKey = `tab_${currentTabId}`;
        if (dataToSave) {
          chrome.storage.local.set({ [storageKey]: { listingJson: dataToSave, timestamp: Date.now() } });
        } else {
          chrome.storage.local.remove(storageKey);
        }
      }
    });
  }

  // Load saved state
  chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
    const currentTabId = tabs[0]?.id;
    if (!currentTabId) return;

    const storageKey = `tab_${currentTabId}`;
    chrome.storage.local.get([storageKey, 'vendooLabels', 'defaultCog'], (result) => {
      const tabData = result[storageKey] || {};
      if (tabData.listingJson) {
        jsonInput.value = JSON.stringify(tabData.listingJson, null, 2);
      }
      if (result.vendooLabels) vendooLabelsInput.value = result.vendooLabels;
      if (result.defaultCog) cogInput.value = result.defaultCog;
      jsonInput.focus();
    });
  });

  // Input listeners
  jsonInput.addEventListener('input', saveState);
  if (vendooLabelsInput) {
    vendooLabelsInput.addEventListener('input', () => {
      chrome.storage.local.set({ 'vendooLabels': vendooLabelsInput.value });
    });
  }
  if (cogInput) {
    cogInput.addEventListener('input', () => {
      chrome.storage.local.set({ 'defaultCog': cogInput.value });
    });
  }

  // Check connection
  chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
    if (tabs[0]) {
      chrome.tabs.sendMessage(tabs[0].id, {type: 'PING'}, (response) => {
        if (chrome.runtime.lastError) {
          showStatus('error', 'Please REFRESH the Vendoo page');
          if (startBtn) startBtn.disabled = true;
        } else {
          showStatus('info', `Ready - ${response.platform}`);
        }
      });
    }
  });

  // Listen for completion
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'FILL_COMPLETE') {
      showStatus('success', `✅ ${msg.platform} complete`);
      enableAllButtons();
    }
    if (msg.type === 'FILL_ERROR') {
      showStatus('error', `❌ ${msg.platform} error: ${msg.error}`);
      enableAllButtons();
    }
    if (msg.type === 'LOG') {
      log(msg.message);
    }
  });

  // Load sample
  if (loadSampleBtn) {
    loadSampleBtn.addEventListener('click', () => {
      jsonInput.value = JSON.stringify(SAMPLE_JSON, null, 2);
      saveState();
      showStatus('info', 'Sample loaded');
    });
  }

  // Diagnose
  if (diagnoseBtn) {
    diagnoseBtn.addEventListener('click', () => {
      if (debugDetails) debugDetails.open = true;
      setDiagnoseState(true);
      showStatus('info', 'Inspecting page and downloading diagnostic...');
      log('Starting background diagnostics with live dropdown scraping...');

      chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
        const tab = tabs[0];
        const tabId = tab?.id;
        if (!tabId) {
          showStatus('error', 'No active tab found');
          log('❌ No active tab found');
          setDiagnoseState(false);
          return;
        }

        chrome.runtime.sendMessage({ type: 'RUN_DIAGNOSTIC', tabId }, (response) => {
          setDiagnoseState(false);
          if (chrome.runtime.lastError) {
            showStatus('error', `Diagnostic failed: ${chrome.runtime.lastError.message}`);
            log(`❌ Diagnostic failed: ${chrome.runtime.lastError.message}`);
            return;
          }

          if (!response?.ok) {
            showStatus('error', `Diagnostic failed: ${response?.error || 'Unknown error'}`);
            log(`❌ Diagnostic failed: ${response?.error || 'Unknown error'}`);
            return;
          }

          showStatus(
            'success',
            `Found ${response.fieldCount} fields • Captured ${response.dropdownsWithOptions}/${response.dropdownCount} dropdowns • Downloaded ${response.filename}`
          );
          log(`✓ URL: ${response.url}`);
          if (response.expandedSections?.length) {
            log(`✓ Expanded: ${response.expandedSections.join(' | ')}`);
          }
          log(
            `✓ Fields: ${response.fieldCount}, Dropdowns: ${response.dropdownCount}, Captured options: ${response.dropdownsWithOptions}, Live captures: ${response.liveDropdownsWithOptions}, Total option values: ${response.totalDropdownOptions}`
          );
        });
      });
    });
  }

  // ============================================
  // ALL PLATFORM BUTTON HANDLERS (at the END)
  // ============================================

  // Vendoo (Main)
  if (startBtn) {
    startBtn.addEventListener('click', () => {
      const jsonText = jsonInput.value.trim();
      if (!jsonText) { showStatus('error', 'Paste JSON first'); return; }
      
      let data;
      try { data = getListingData({ reformatInput: true }); } catch(e) { showStatus('error', 'Invalid JSON'); return; }
      
      const labels = vendooLabelsInput.value.split(',').map(s => s.trim()).filter(s => s);
      if (labels.length > 0) data.labels = labels;
      
      const cog = parseFloat(cogInput.value);
      if (!isNaN(cog)) data.cost = cog;
      
      data = applyOverrides(data);
      
      showStatus('info', 'Filling Vendoo...');
      startBtn.disabled = true;
      
      chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
        chrome.runtime.sendMessage({ type: 'START_VENDOO', data: data, tabId: tabs[0].id });
      });
    });
  }

  // eBay
  if (startEbayBtn) {
    startEbayBtn.addEventListener('click', () => {
      try {
        const data = getListingData({ reformatInput: true });
        const processedData = applyOverrides(data);
        showStatus('info', 'Filling eBay...');
        startEbayBtn.disabled = true;
        chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
          chrome.runtime.sendMessage({ type: 'START_EBAY', data: processedData, tabId: tabs[0].id });
        });
      } catch(e) { showStatus('error', 'Invalid JSON'); }
    });
  }

  // Etsy
  if (startEtsyBtn) {
    startEtsyBtn.addEventListener('click', () => {
      try {
        const data = getListingData({ reformatInput: true });
        const processedData = applyOverrides(data);
        showStatus('info', 'Filling Etsy...');
        startEtsyBtn.disabled = true;
        chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
          chrome.runtime.sendMessage({ type: 'START_ETSY', data: processedData, tabId: tabs[0].id });
        });
      } catch(e) { showStatus('error', 'Invalid JSON'); }
    });
  }

  // Poshmark
  if (startPoshmarkBtn) {
    startPoshmarkBtn.addEventListener('click', () => {
      try {
        const data = getListingData({ reformatInput: true });
        const processedData = applyOverrides(data);
        showStatus('info', 'Filling Poshmark...');
        startPoshmarkBtn.disabled = true;
        chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
          chrome.runtime.sendMessage({ type: 'START_POSHMARK', data: processedData, tabId: tabs[0].id });
        });
      } catch(e) { showStatus('error', 'Invalid JSON'); }
    });
  }

  // Mercari
  if (startMercariBtn) {
    startMercariBtn.addEventListener('click', () => {
      try {
        const data = getListingData({ reformatInput: true });
        const processedData = applyOverrides(data);
        showStatus('info', 'Filling Mercari...');
        startMercariBtn.disabled = true;
        chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
          chrome.runtime.sendMessage({ type: 'START_MERCARI', data: processedData, tabId: tabs[0].id });
        });
      } catch(e) { showStatus('error', 'Invalid JSON'); }
    });
  }

  // Depop
  if (startDepopBtn) {
    startDepopBtn.addEventListener('click', () => {
      try {
        const data = getListingData({ reformatInput: true });
        const processedData = applyOverrides(data);
        showStatus('info', 'Filling Depop...');
        startDepopBtn.disabled = true;
        chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
          chrome.runtime.sendMessage({ type: 'START_DEPOP', data: processedData, tabId: tabs[0].id });
        });
      } catch(e) { showStatus('error', 'Invalid JSON'); }
    });
  }
});
