// Leftover field fills and per-command timeouts.

async function runFillFields(jobId, payload) {
  if (activePatch) {
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { step: 'filling_fields', error: 'Another leftover field fill is already running' },
    });
    return;
  }
  // Leftover fills use activePatch, not activeJob. A restored/stale activeJob from a
  // finished Send must not block refill after reload.
  if (activeJob && activeJob.job_id !== jobId) {
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { step: 'filling_fields', error: 'Another automation job is already running' },
    });
    return;
  }
  if (activeJob) {
    warn(
      `Clearing stale activeJob ${activeJob.job_id} (${activeJob.current_step || 'unknown'}) before leftover fill`
    );
    await persistActiveJob(null);
    await stopJobPreview();
  }

  const opened = await openListingForPatch(
    { ...payload, job_id: jobId },
    { reload: payload.reload !== false, preview: true },
  );
  if (!opened.ok) {
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { step: 'filling_fields', error: opened.error },
    });
    return;
  }

  const job = { job_id: jobId, tabId: opened.tabId };
  activePatch = job;
  send({
    version: 1,
    type: 'job.progress',
    job_id: jobId,
    message_id: Date.now().toString(36),
    sent_at: new Date().toISOString(),
    payload: { step: 'filling_fields' },
  });

  const ready = await waitForContentScript(job);
  if (!ready.ok) {
    activePatch = null;
    await stopJobPreview();
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: { step: 'filling_fields', error: ready.error },
    });
    return;
  }

  const formReady = await sendToVendoo(job, { type: 'WAIT_FOR_FORM', timeoutMs: 30000 });
  if (!formReady?.ok) {
    activePatch = null;
    await stopJobPreview();
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: {
        step: 'filling_fields',
        error: formReady?.error || 'Vendoo listing form did not finish loading',
      },
    });
    return;
  }

  const patchPlatforms = [...new Set((payload.fields || [])
    .map((field) => String(field.marketplace || '').toLowerCase())
    .filter((marketplace) => marketplace && marketplace !== 'general'))];
  const safety = await sendToVendoo(job, {
    type: 'CHECK_DRAFT_SAFETY',
    platforms: patchPlatforms,
  });
  if (!safety?.ok) {
    activePatch = null;
    await stopJobPreview();
    send({
      version: 1,
      type: 'job.step_failed',
      job_id: jobId,
      message_id: Date.now().toString(36),
      sent_at: new Date().toISOString(),
      payload: {
        step: 'filling_fields',
        error: safety?.error || 'Could not verify that the existing Vendoo item is a draft',
      },
    });
    return;
  }

  const fillStartedAt = Date.now();
  const shouldVerify = payload.verify !== false;
  const marketplaceGroups = payload.fields?.length ? groupFillFieldMarketplaces(payload.fields) : [];
  const totalBatches = marketplaceGroups.reduce((sum, group) => sum + group.batches.length, 0);
  const batchResults = [];
  let lastSaved = null;
  // Prefer marketplaces from the patch list so post-fill verify does not re-tour every form.
  const hasFieldPatches = Array.isArray(payload.fields) && payload.fields.length > 0;
  const verifyPlatforms = patchPlatforms.length
    ? patchPlatforms
    : (hasFieldPatches ? [] : (payload.platforms || []));
  const verifyIncludesGeneral = !hasFieldPatches || (payload.fields || []).some((field) => {
    const mp = String(field.marketplace || 'general').toLowerCase();
    return !mp || mp === 'general' || mp === 'unknown';
  });
  log(`Filling leftover fields in ${totalBatches} batch(es) across ${marketplaceGroups.length} marketplace(s)`);

  let batchIndex = 0;
  let fillFailed = false;
  for (const { marketplace, batches } of marketplaceGroups) {
    for (const fields of batches) {
      if (activePatch !== job) return;
      batchIndex += 1;
      send({
        version: 1,
        type: 'job.progress',
        job_id: jobId,
        message_id: Date.now().toString(36),
        sent_at: new Date().toISOString(),
        payload: {
          step: 'filling_fields',
          marketplace,
          batch: batchIndex,
          batch_count: totalBatches,
          field_count: fields.length,
        },
      });
      const result = await sendToVendoo(job, {
        type: 'FILL_FIELDS',
        fields,
        skip_reverify: !shouldVerify,
      });
      if (activePatch !== job) return;
      batchResults.push(result);
      if (!result.ok) {
        fillFailed = true;
        log(`Leftover fill needs repair: ${result.error || 'Fill failed'}`);
        break;
      }
    }
    if (fillFailed) break;

    if (shouldVerify) {
      log(`Saving leftover ${marketplace} form`);
      const saved = await sendToVendoo(job, saveCommandForMarketplace(marketplace));
      lastSaved = saved;
      if (!saved.ok) {
        fillFailed = true;
        log(`Leftover fill needs repair: ${saved.error || 'Save failed'}`);
        break;
      }
    }
  }

  if (!shouldVerify && !fillFailed && batchResults.length) {
    log('Saving Vendoo draft after apply');
    const saved = await sendToVendoo(job, { type: 'SAVE_GENERAL' });
    lastSaved = saved;
    if (!saved.ok) {
      fillFailed = true;
      log(`Leftover fill needs repair: ${saved.error || 'Save failed'}`);
    }
  }

  const fillLog = mergeFillLogs(batchResults);
  if (activePatch !== job) return;
  let verification = null;
  if (shouldVerify) {
    const platformsForVerify = [
      ...(verifyIncludesGeneral ? ['general'] : []),
      ...verifyPlatforms,
    ];
    verification = await verifySavedDraft({
      ...job,
      vendoo_item_id: lastSaved?.vendoo_item_id || payload.vendoo_item_id,
      vendoo_url: lastSaved?.vendoo_url || payload.vendoo_url,
      listing: payload.listing || {},
      options: { platforms: platformsForVerify },
      photos: Array(payload.expected_photo_count || 0).fill(null),
    });
    const schema = verification?.schema || {};
    const incomplete = !verification?.readback || platformsForVerify.some((mp) => {
      const section = schema[mp] || {};
      return !section.fields?.length || section.error;
    });
    // Only retry when the first pass failed to read — do not re-tour matching forms.
    if (incomplete) {
      log(`Fill verification incomplete (${verification?.error || 'empty marketplace schema'}); retrying once`);
      await sleep(2000);
      verification = await verifySavedDraft({
        ...job,
        vendoo_item_id: lastSaved?.vendoo_item_id || payload.vendoo_item_id,
        vendoo_url: lastSaved?.vendoo_url || payload.vendoo_url,
        listing: payload.listing || {},
        options: { platforms: platformsForVerify },
        photos: Array(payload.expected_photo_count || 0).fill(null),
      });
    }
  }
  if (activePatch !== job) return;
  // Read the saved item over the API while the tab is open so Studio's draft cache
  // reflects this apply (Send uses it to skip marketplaces that already match).
  let savedItem = null;
  const savedItemId = durableItemId(lastSaved?.vendoo_item_id || payload.vendoo_item_id);
  if (payload.read_item && !fillFailed && savedItemId) {
    const read = await Promise.race([
      readItemFromPage(job.tabId, savedItemId),
      sleep(8000).then(() => ({ ok: false })),
    ]);
    if (read?.ok && read.item) savedItem = compactVendooValue(read.item, 0);
  }
  if (activePatch !== job) return;
  activePatch = null;
  await stopJobPreview();
  await sleep(1500);
  await closeListingTab(job.tabId);

  const completedPayload = {
    step: 'filling_fields',
    duration_ms: Date.now() - fillStartedAt,
    vendoo_item_id: savedItemId || null,
    vendoo_url: lastSaved?.vendoo_url || payload.vendoo_url || null,
    fill_log: fillLog,
  };
  if (savedItem) {
    completedPayload.item = savedItem;
  }
  if (verification) {
    completedPayload.verification = verification;
  }
  send({
    version: 1,
    type: 'job.step_completed',
    job_id: jobId,
    message_id: Date.now().toString(36),
    sent_at: new Date().toISOString(),
    payload: completedPayload,
  });
}

function groupFillFieldBatches(fields) {
  return groupFillFieldMarketplaces(fields).flatMap((group) => group.batches);
}

function groupFillFieldMarketplaces(fields) {
  const grouped = new Map();
  for (const item of Array.isArray(fields) ? fields : []) {
    const marketplace = String(item?.marketplace || 'general').toLowerCase();
    if (!grouped.has(marketplace)) grouped.set(marketplace, []);
    grouped.get(marketplace).push(item);
  }
  const chunkSize = 25;
  const result = [];
  for (const [marketplace, group] of grouped) {
    const batches = [];
    for (let i = 0; i < group.length; i += chunkSize) {
      batches.push(group.slice(i, i + chunkSize));
    }
    result.push({ marketplace, batches: batches.length ? batches : [[]] });
  }
  return result;
}

function mergeFillLogs(results) {
  const entries = [];
  for (const result of results) {
    const log = result && result.fill_log;
    if (log && Array.isArray(log.entries)) entries.push(...log.entries);
  }
  if (!entries.length) return null;
  return {
    marketplace: entries[0].marketplace || 'general',
    entries,
  };
}

function saveCommandForMarketplace(marketplace) {
  const platform = String(marketplace || 'general').toLowerCase();
  if (platform && platform !== 'general' && platform !== 'unknown') {
    return { type: 'SAVE_MARKETPLACE', platform };
  }
  return { type: 'SAVE_GENERAL' };
}

function commandTimeoutMs(command) {
  if (command.type === 'FILL_FIELDS') {
    const count = Array.isArray(command.fields) ? command.fields.length : 0;
    return Math.min(300000, Math.max(90000, 30000 + count * 5000));
  }
  if (command.type === 'WAIT_FOR_FORM') {
    return Math.max(35000, Number(command.timeoutMs) || 30000) + 5000;
  }
  // Full marketplace fills (esp. Etsy category specifics) routinely exceed 90s.
  // Leftover FILL_FIELDS already scales up to 300s; keep the bulk fill in the same range.
  if (command.type === 'FILL_GENERAL' || command.type === 'FILL_MARKETPLACE') {
    return 180000;
  }
  if (command.type === 'CLEAR_GENERAL' || command.type === 'CLEAR_MARKETPLACE') {
    return 90000;
  }
  if (command.type === 'SAVE_GENERAL' || command.type === 'SAVE_MARKETPLACE') {
    return 60000;
  }
  if (command.type === 'DISCOVER_SCHEMA' || command.type === 'VERIFY_SAVED_DRAFT') {
    const count = Array.isArray(command.platforms) ? command.platforms.length : 5;
    // Discovery walks each panel, then opens up to MAX_OPTION_CAPTURES_PER_PLATFORM
    // dropdowns (12) to read their live options at ~1.1s worst case each. Keep both
    // halves budgeted or the probe times out and learns nothing.
    const perPlatformMs = 25000 + 15000;
    return Math.min(300000, Math.max(120000, 60000 + count * perPlatformMs));
  }
  if (command.type === 'SET_GENERAL_CATEGORY') {
    return 90000;
  }
  if (command.type === 'GET_VENDOO_ITEM') {
    return 120000;
  }
  if (command.type === 'SEARCH_CATEGORIES') {
    return 45000;
  }
  if (command.type === 'UPLOAD_PHOTOS') {
    const count = Array.isArray(command.files) ? command.files.length : 0;
    return Math.min(180000, Math.max(60000, 20000 + count * 10000));
  }
  return 45000;
}
