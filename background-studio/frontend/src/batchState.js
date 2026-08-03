export const MAX_BATCH_ITEMS = 10;
export const BATCH_STATUS = Object.freeze({ QUEUED: "queued", PROCESSING: "processing", RESTORING: "restoring", READY: "ready", FAILED: "failed", CLEANUP_PENDING: "cleanup_pending" });
const JOB_ID = /^[0-9a-f]{32}$/i;
const fileMetadata = file => ({ name: file?.name || "Recovered image", type: file?.type || "application/octet-stream", size: Number.isSafeInteger(file?.size) ? file.size : 0, lastModified: Number.isSafeInteger(file?.lastModified) ? file.lastModified : 0 });
const displayFile = metadata => {
  try { return new File([], metadata.name, { type: metadata.type, lastModified: metadata.lastModified }); } catch { return { ...metadata }; }
};
export const createInitialBatchState = (items = []) => { const safeItems = Array.isArray(items) ? items : []; return { items: safeItems, selectedLocalId: safeItems.find(item => item.status === BATCH_STATUS.READY)?.localId || null }; };
function hex32() { const bytes = new Uint8Array(16); crypto.getRandomValues(bytes); return [...bytes].map(v => v.toString(16).padStart(2, "0")).join(""); }
export function createBatchItems(files, factories = {}) {
  const localIdFactory = factories.localIdFactory || (() => `local-${hex32()}`);
  const jobIdFactory = factories.jobIdFactory || hex32;
  return [...(files || [])].map((file, index) => {
    const localId = localIdFactory(file, index); const clientJobId = jobIdFactory(file, index);
    if (!localId || !JOB_ID.test(clientJobId)) throw new TypeError("Invalid batch item identifier");
    return { file, localId, clientJobId: clientJobId.toLowerCase(), uploadable: true, fileMetadata: fileMetadata(file) };
  });
}
export function createRestoredBatchItems(entries = []) {
  return (Array.isArray(entries) ? entries : []).slice(0, MAX_BATCH_ITEMS).filter(entry => entry && JOB_ID.test(entry.clientJobId || "") && entry.localId && entry.file).map(entry => ({
    file: displayFile(entry.file), fileMetadata: { ...entry.file }, localId: entry.localId, clientJobId: entry.clientJobId.toLowerCase(), uploadable: false,
    recoveryStatus: entry.status, recoveryCreatedAt: entry.createdAt, status: entry.status === BATCH_STATUS.CLEANUP_PENDING ? BATCH_STATUS.CLEANUP_PENDING : entry.status === BATCH_STATUS.FAILED ? BATCH_STATUS.FAILED : BATCH_STATUS.RESTORING,
    backendWidth: entry.backendWidth, backendHeight: entry.backendHeight, editor: entry.editor || {},
  })).map(initialItem);
}
const initialItem = x => ({ ...x, status: x.status || BATCH_STATUS.QUEUED, uploadable: x.uploadable !== false, fileMetadata: x.fileMetadata || fileMetadata(x.file), thumbnailUrl: x.thumbnailUrl ?? null, thumbnailWidth: x.thumbnailWidth ?? null, thumbnailHeight: x.thumbnailHeight ?? null, thumbnailRevoke: x.thumbnailRevoke || null, thumbnailError: x.thumbnailError || null, backendWidth: x.backendWidth ?? null, backendHeight: x.backendHeight ?? null, error: x.error || null, editor: x.editor || {}, cleanup: x.cleanup || null });
const update = (items, id, fn) => items.map(item => item.localId === id ? fn(item) : item);
const selectedReady = state => state.items.find(x => x.localId === state.selectedLocalId)?.status === BATCH_STATUS.READY;
const repairSelection = (items, selected) => items.find(x => x.localId === selected)?.status === BATCH_STATUS.READY ? selected : items.find(x => x.status === BATCH_STATUS.READY)?.localId || null;
const appendItems = (state, candidates, restored = false) => {
  const known = new Set(state.items.flatMap(x => [x.localId, x.clientJobId])); const added = [];
  for (const candidate of candidates || []) {
    if (state.items.length + added.length >= MAX_BATCH_ITEMS) break;
    const x = { ...candidate, uploadable: restored ? false : true };
    if (!x?.file || !x.localId || !JOB_ID.test(x.clientJobId || "") || known.has(x.localId) || known.has(x.clientJobId.toLowerCase())) continue;
    known.add(x.localId); known.add(x.clientJobId.toLowerCase()); added.push(initialItem({ ...x, clientJobId: x.clientJobId.toLowerCase() }));
  }
  return added.length ? { ...state, items: [...state.items, ...added] } : state;
};
export const batchActions = {
  admit: items => ({ type: "admit", items }), adopt: items => ({ type: "adopt", items }), thumbnailReady: (localId, thumbnail) => ({ type: "thumbnailReady", localId, ...thumbnail }), thumbnailFailed: (localId, error) => ({ type: "thumbnailFailed", localId, error }), processing: localId => ({ type: "processing", localId }), ready: (localId, payload) => ({ type: "ready", localId, ...payload }), restoreReady: (localId, payload) => ({ type: "restoreReady", localId, ...payload }), restorePending: (localId, error = null) => ({ type: "restorePending", localId, error }), failed: (localId, error) => ({ type: "failed", localId, error }), retry: (localId, clientJobId) => ({ type: "retry", localId, clientJobId }), select: localId => ({ type: "select", localId }), remove: localId => ({ type: "remove", localId }), editorPatch: (localId, patch) => ({ type: "editorPatch", localId, patch }), cleanupStatus: (localId, phase, error = null) => ({ type: "cleanupStatus", localId, phase, error }), reset: () => ({ type: "reset" }),
};
export function batchReducer(state = createInitialBatchState(), action) {
  let items;
  switch (action?.type) {
    case "admit": return appendItems(state, action.items, false);
    case "adopt": return appendItems(state, action.items, true);
    case "thumbnailReady": items = update(state.items, action.localId, x => ({ ...x, thumbnailUrl: action.url, thumbnailWidth: action.width, thumbnailHeight: action.height, thumbnailRevoke: action.revoke || null, thumbnailError: null })); return { ...state, items };
    case "thumbnailFailed": items = update(state.items, action.localId, x => ({ ...x, thumbnailError: action.error || "Thumbnail failed" })); return { ...state, items };
    case "processing": items = update(state.items, action.localId, x => x.uploadable !== false && x.status === BATCH_STATUS.QUEUED ? ({ ...x, status: BATCH_STATUS.PROCESSING, error: null, cleanup: null }) : x); return { ...state, items };
    case "ready": items = update(state.items, action.localId, x => x.status === BATCH_STATUS.PROCESSING ? ({ ...x, status: BATCH_STATUS.READY, backendWidth: action.width, backendHeight: action.height, error: null, cleanup: null }) : x); return { items, selectedLocalId: selectedReady(state) ? state.selectedLocalId : action.localId };
    case "restoreReady": items = update(state.items, action.localId, x => x.uploadable === false && [BATCH_STATUS.RESTORING, BATCH_STATUS.CLEANUP_PENDING, BATCH_STATUS.READY].includes(x.status) ? ({ ...x, status: BATCH_STATUS.READY, backendWidth: action.width, backendHeight: action.height, error: null, cleanup: null }) : x); return { items, selectedLocalId: selectedReady(state) ? state.selectedLocalId : action.localId };
    case "restorePending": items = update(state.items, action.localId, x => x.uploadable === false ? ({ ...x, status: BATCH_STATUS.RESTORING, error: action.error || null }) : x); return { ...state, items };
    case "failed": items = update(state.items, action.localId, x => x.status === BATCH_STATUS.CLEANUP_PENDING ? x : ({ ...x, status: BATCH_STATUS.FAILED, backendWidth: null, backendHeight: null, error: action.error || "Processing failed", cleanup: null })); return { items, selectedLocalId: repairSelection(items, state.selectedLocalId) };
    case "retry": if (!JOB_ID.test(action.clientJobId || "")) return state; items = update(state.items, action.localId, x => x.uploadable !== false && x.status === BATCH_STATUS.FAILED ? ({ ...x, clientJobId: action.clientJobId.toLowerCase(), status: BATCH_STATUS.QUEUED, backendWidth: null, backendHeight: null, error: null, editor: {}, cleanup: null }) : x); return { items, selectedLocalId: repairSelection(items, state.selectedLocalId) };
    case "select": return action.localId == null || state.items.some(x => x.localId === action.localId && x.status === BATCH_STATUS.READY) ? { ...state, selectedLocalId: action.localId } : state;
    case "editorPatch": items = update(state.items, action.localId, x => x.status === BATCH_STATUS.READY ? ({ ...x, editor: { ...x.editor, ...(action.patch || {}) } }) : x); return { ...state, items };
    case "cleanupStatus": if (action.phase === "complete") return batchReducer(state, batchActions.remove(action.localId)); items = update(state.items, action.localId, x => ({ ...x, status: BATCH_STATUS.CLEANUP_PENDING, cleanup: { phase: action.phase, error: action.error } })); return { items, selectedLocalId: repairSelection(items, state.selectedLocalId) };
    case "remove": items = state.items.filter(x => x.localId !== action.localId); return { items, selectedLocalId: repairSelection(items, state.selectedLocalId) };
    case "reset": return createInitialBatchState();
    default: return state;
  }
}
export function selectNextQueuedItem(state) { return state.items.some(x => x.status === BATCH_STATUS.PROCESSING) ? null : state.items.find(x => x.status === BATCH_STATUS.QUEUED) || null; }
