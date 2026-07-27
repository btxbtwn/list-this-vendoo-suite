export const CLEANUP_LEDGER_KEY = "background-studio.cleanup-ledger.v1";
export const MAX_CLEANUP_IDS = 256;
const VALID = /^[0-9a-f]{32}$/i;
const resolve = storage => storage || globalThis.sessionStorage;
export function readCleanupLedger(storage, key = CLEANUP_LEDGER_KEY) {
  try { const raw = resolve(storage).getItem(key); if (raw == null) return { ids: [], corrupt: false }; const value = JSON.parse(raw); if (!value || Object.keys(value).length !== 1 || !Array.isArray(value.ids) || value.ids.length > MAX_CLEANUP_IDS) throw new Error(); const ids = value.ids.map(x => { if (!VALID.test(x)) throw new Error(); return x.toLowerCase(); }); if (new Set(ids).size !== ids.length) throw new Error(); return { ids, corrupt: false }; } catch { return { ids: [], corrupt: true }; }
}
function change(id, storage, key, remove) { const current = readCleanupLedger(storage, key); if (current.corrupt) return { ok: false, ...current, error: new Error("Cleanup ledger is corrupt") }; if (!VALID.test(id || "")) return { ok: false, ...current, error: new TypeError("Invalid cleanup ID") }; const normalized = id.toLowerCase(); let ids = remove ? current.ids.filter(x => x !== normalized) : current.ids.includes(normalized) ? current.ids : [...current.ids, normalized]; if (ids.length > MAX_CLEANUP_IDS) return { ok: false, ...current, error: new RangeError("Cleanup ledger is full") }; if (ids.length === current.ids.length && ids.every((x, i) => x === current.ids[i])) return { ok: true, ids, corrupt: false, changed: false }; try { resolve(storage).setItem(key, JSON.stringify({ ids })); return { ok: true, ids, corrupt: false, changed: true }; } catch (error) { return { ok: false, ...current, error }; } }
export const addCleanupId = (id, storage, key = CLEANUP_LEDGER_KEY) => change(id, storage, key, false);
export const removeCleanupId = (id, storage, key = CLEANUP_LEDGER_KEY) => change(id, storage, key, true);
