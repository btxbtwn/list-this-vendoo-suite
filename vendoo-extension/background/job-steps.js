// Send pipeline steps: open, upload photos, fill, save, and audit.

async function openVendooListing(job) {
  try {
    // Field discovery during generate should be visible so mobile/Browser preview
    // and the Mac user can see Chrome working. Background Send fills stay unfocused.
    const foreground = job.options?.mode === 'schema_probe';
    const reuseId = durableItemId(job.vendoo_item_id || job.options?.vendoo_item_id);
    const reuseUrl = job.vendoo_url || job.options?.vendoo_url || (reuseId
      ? `https://web.vendoo.co/app/item/${reuseId}`
      : null);
    if (reuseId || reuseUrl) {
      const resumeMarketplace = marketplaceFromStep(job.options?.resumeFrom);
      const opened = await openListingForPatch({
        job_id: job.job_id,
        vendoo_item_id: reuseId,
        vendoo_url: reuseUrl,
      }, { reload: true, preview: true, marketplace: resumeMarketplace, foreground });
      if (!opened.ok) return opened;
      const tab = await chrome.tabs.get(opened.tabId);
      activeJob.windowId = tab.windowId;
      activeJob.tabId = opened.tabId;
      activeJob.vendoo_item_id = reuseId || extractItemIdFromUrl(tab.url || reuseUrl || '');
      activeJob.vendoo_url = reuseUrl || tab.url;
      await persistActiveJob(activeJob);
      return {
        ok: true,
        vendoo_item_id: activeJob.vendoo_item_id,
        vendoo_url: activeJob.vendoo_url,
      };
    }

    const existingTab = await findNewItemTab();
    if (existingTab) {
      log(`Reloading new-item tab ${existingTab.id} -> ${NEW_ITEM_URL}`);
      const tab = await openEverydayListingTab(NEW_ITEM_URL, existingTab, { foreground });
      activeJob.windowId = tab.windowId;
      activeJob.tabId = tab.id;
      await persistActiveJob(activeJob);
      await waitForTabComplete(tab.id);
      await startJobPreview(tab.id, job.job_id);
      return { ok: true };
    }

    const tab = await openEverydayListingTab(NEW_ITEM_URL, null, { foreground });
    log(`Opened Vendoo tab ${tab.id} in Studio engine window ${tab.windowId}`);

    activeJob.windowId = tab.windowId;
    activeJob.tabId = tab.id;
    await persistActiveJob(activeJob);

    const loaded = await waitForTabComplete(tab.id);
    await startJobPreview(tab.id, job.job_id);
    if (!isTabReady(loaded)) {
      return { ok: false, error: `Vendoo tab did not finish loading (${loaded?.url || 'unknown url'})` };
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, error: `Failed to open Vendoo: ${err.message}` };
  }
}

async function waitForContentScript(job) {
  const tabId = job.tabId || (activeJob && activeJob.tabId);
  if (!tabId) return { ok: false, error: 'No job tab stored' };

  const tab = await waitForTabComplete(tabId);
  if (!isTabReady(tab)) {
    return { ok: false, error: `Vendoo tab not ready (${tab?.url || 'unknown url'})` };
  }
  const expectedId = durableItemId(
    job.vendoo_item_id || job.options?.vendoo_item_id || activeJob?.vendoo_item_id,
  );
  if (expectedId && extractItemIdFromUrl(tab.url || '') !== expectedId) {
    return { ok: false, error: `Vendoo tab is not the saved draft (${tab?.url || 'unknown url'})` };
  }

  let injected = false;
  let reloaded = false;
  let lastUrl = tab.url;
  for (let i = 0; i < 20; i++) {
    const resp = await pingContentScript(tabId);
    if (resp && resp.ok) {
      if (resp.contentScriptVersion === CONTENT_SCRIPT_VERSION) {
        log(`Content script ready on tab ${tabId} v${resp.contentScriptVersion}`);
        return { ok: true };
      }
      log(`Content script version mismatch: got ${resp.contentScriptVersion}, expected ${CONTENT_SCRIPT_VERSION}`);
      if (!reloaded) {
        log(`Reloading Vendoo tab ${tabId} to pick up the current content script`);
        const reloadedTab = await reloadTabAndWait(tabId);
        reloaded = true;
        injected = false;
        if (!isTabReady(reloadedTab)) {
          return { ok: false, error: `Vendoo tab did not finish reloading (${reloadedTab?.url || 'unknown url'})` };
        }
        lastUrl = reloadedTab.url;
        continue;
      }
      log(`Content script still at v${resp.contentScriptVersion} after reload; continuing`);
      return { ok: true };
    }

    try {
      const current = await chrome.tabs.get(tabId);
      if (current.url && current.url !== lastUrl) {
        log(`Vendoo tab navigated ${lastUrl} -> ${current.url}`);
        lastUrl = current.url;
        injected = false;
      }
    } catch (err) {
      return { ok: false, error: `Vendoo tab closed: ${err.message}` };
    }

    if (!injected) {
      try {
        await injectVendooContentScript(tabId);
        injected = true;
        log(`Injected content script into tab ${tabId}`);
      } catch (err) {
        log(`Content script inject failed on tab ${tabId}: ${err.message}`);
      }
    }

    await sleep(1000);
  }
  return { ok: false, error: 'Content script not ready after timeout' };
}

async function sendToVendoo(job, command) {
  const tabId = job.tabId || (activeJob && activeJob.tabId);
  if (!tabId) {
    return { ok: false, error: 'No job tab stored' };
  }
  const timeoutMs = commandTimeoutMs(command);
  try {
    const resp = await Promise.race([
      chrome.tabs.sendMessage(tabId, { ...command }),
      sleep(timeoutMs).then(() => ({
        ok: false,
        error: `${command.type} timed out after ${timeoutMs / 1000}s`,
      })),
    ]);
    return resp || { ok: false, error: 'No response' };
  } catch (err) {
    return { ok: false, error: `sendMessage failed: ${err.message}` };
  }
}

async function clearGeneral(job) {
  return sendToVendoo(job, { type: 'CLEAR_GENERAL' });
}

async function clearMarketplace(job, platform) {
  return sendToVendoo(job, { type: 'CLEAR_MARKETPLACE', platform });
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunks = [];
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    chunks.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize)));
  }
  return btoa(chunks.join(''));
}

function photoFetchTimeoutSignal() {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(30000);
  }
  return undefined;
}

async function fetchStudioPhotoFiles(jobId, photos) {
  const files = [];
  const errors = [];
  for (const photo of photos) {
    const photoId = photo.id || photo.stored_filename || photo.name;
    if (!photoId) {
      errors.push('Photo is missing an id');
      continue;
    }
    const url = `${STUDIO_URL}/api/jobs/${jobId}/photos/${encodeURIComponent(photoId)}`;
    try {
      const response = await fetch(url, { signal: photoFetchTimeoutSignal() });
      if (!response.ok) {
        errors.push(`${photoId}: HTTP ${response.status}`);
        continue;
      }
      const buffer = await response.arrayBuffer();
      files.push({
        name: photo.name || photo.original_filename || 'photo.jpg',
        type: response.headers.get('content-type') || photo.mime_type || 'image/jpeg',
        data: arrayBufferToBase64(buffer),
      });
    } catch (err) {
      errors.push(`${photoId}: ${err.message}`);
    }
  }
  return { files, errors };
}

async function uploadPhotos(job) {
  if (job.options?.skipPhotos) {
    return { ok: true };
  }
  const photos = job.photos || [];
  if (photos.length === 0) {
    return { ok: true };
  }

  const { files, errors } = await fetchStudioPhotoFiles(job.job_id, photos);
  if (errors.length) {
    log(`Studio photo fetch failed: ${errors.join('; ')}`);
  }
  if (files.length === 0) {
    const detail = errors.length ? `: ${errors.join('; ')}` : '';
    return { ok: false, error: `No photos could be fetched${detail}` };
  }

  return sendToVendoo(job, {
    type: 'UPLOAD_PHOTOS',
    files,
  });
}

async function fillGeneral(job) {
  return sendToVendoo(job, {
    type: 'FILL_GENERAL',
    data: job.listing,
    registry_selectors: job.registry_selectors || {},
    registry_options: job.registry_options || {},
  });
}

async function selectGeneralCategoryOnly(job) {
  return sendToVendoo(job, {
    type: 'SET_GENERAL_CATEGORY',
    data: job.listing,
  });
}

async function discoverSchema(job) {
  const platforms = job.options?.platforms || [];
  const result = await sendToVendoo(job, {
    type: 'DISCOVER_SCHEMA',
    data: job.listing,
    platforms,
  });
  if (result?.ok && result.schema) {
    job.discovered_schema = result.schema;
    await persistActiveJob(job);
  }
  return result;
}

async function saveGeneral(job) {
  return sendToVendoo(job, {
    type: 'SAVE_GENERAL',
  });
}

async function checkDraftSafety(job) {
  return sendToVendoo(job, {
    type: 'CHECK_DRAFT_SAFETY',
    platforms: job.options?.platforms || [],
  });
}

async function verifySavedDraft(job) {
  const itemId = durableItemId(job.vendoo_item_id) || extractItemIdFromUrl(job.vendoo_url || '');
  if (!itemId) {
    return { ok: false, error: 'No durable Vendoo item ID after save' };
  }
  const url = extractItemIdFromUrl(job.vendoo_url || '') === itemId
    ? job.vendoo_url
    : `https://web.vendoo.co/app/item/${itemId}`;
  const tabId = job.tabId;
  if (tabId) {
    try {
      await chrome.tabs.update(tabId, { url });
      const loaded = await reloadTabAndWait(tabId, 20000);
      if (!isTabReady(loaded)) return { ok: false, error: 'Saved draft reload did not finish' };
      const ready = await waitForContentScript({ tabId, job_id: job.job_id });
      if (!ready.ok) return ready;
    } catch (err) {
      return { ok: false, error: `Could not reopen saved draft: ${err.message}` };
    }
  }
  const expectedPhotos = Array.isArray(job.photos) ? job.photos.length : 0;
  return sendToVendoo(job, {
    type: 'VERIFY_SAVED_DRAFT',
    data: job.listing,
    platforms: job.options?.platforms || [],
    expected_photo_count: expectedPhotos,
  });
}

async function auditGeneral(job) {
  return sendToVendoo(job, {
    type: 'AUDIT_GENERAL',
    data: job.listing,
  });
}

async function fillMarketplace(job, platform) {
  return sendToVendoo(job, {
    type: 'FILL_MARKETPLACE',
    platform,
    data: job.listing,
    skipCategory: Boolean(job.categoriesAligned),
    registry_selectors: job.registry_selectors || {},
    registry_options: job.registry_options || {},
  });
}

async function saveMarketplace(job, platform) {
  return sendToVendoo(job, {
    type: 'SAVE_MARKETPLACE',
    platform,
  });
}

async function auditMarketplace(job, platform) {
  return sendToVendoo(job, {
    type: 'AUDIT_MARKETPLACE',
    platform,
    data: job.listing,
  });
}

async function auditAllMarketplaces(job) {
  const platforms = job.options?.platforms || [];
  const results = [];
  for (const platform of platforms) {
    const result = await auditMarketplace(job, platform);
    results.push(result);
    if (!result?.ok) {
      return {
        ok: false,
        error: result?.error || `${platform} audit failed`,
        fields: result?.fields || {},
        fill_log: mergeFillLogs(results),
      };
    }
  }
  return { ok: true, fill_log: mergeFillLogs(results) };
}
