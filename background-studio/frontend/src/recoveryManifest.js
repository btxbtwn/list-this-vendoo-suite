export const RECOVERY_MANIFEST_KEY = 'background-studio.recovery-manifest.v1'
export const RECOVERY_MANIFEST_VERSION = 1
export const MAX_RECOVERY_ENTRIES = 10

const JOB_ID = /^[0-9a-f]{32}$/i
const LOCAL_ID = /^[A-Za-z0-9._:-]{1,80}$/
const RECOVERY_STATUSES = new Set(['queued', 'processing', 'ready', 'failed', 'cleanup_pending', 'restoring'])
const EDITOR_KEYS = new Set(['threshold', 'feather', 'background', 'color', 'compare', 'mode', 'brushSize', 'softness', 'strokeCount', 'revision'])
const MAX_FILE_NAME = 255
const MAX_FILE_TYPE = 128
const MAX_EDITOR_BYTES = 4096

const resolveStorage = (storage) => {
  if (storage) return storage
  try {
    if (typeof window !== 'undefined') {
      const local = window.localStorage
      if (local) return local
      const session = window.sessionStorage
      if (session) return session
      return null
    }
    return globalThis.localStorage
  } catch {
    try { return typeof window !== 'undefined' ? window.sessionStorage : null } catch { return null }
  }
}

const finiteNonNegative = (value) => Number.isFinite(value) && value >= 0

function normalizeEditor(value) {
  if (value == null) return {}
  if (typeof value !== 'object' || Array.isArray(value)) throw new TypeError('Invalid editor metadata')
  const editor = {}
  for (const key of Object.keys(value)) {
    if (!EDITOR_KEYS.has(key)) continue
    const next = value[key]
    if (typeof next === 'number' && Number.isFinite(next)) editor[key] = next
    else if (typeof next === 'string' && next.length <= 64) editor[key] = next
    else if (typeof next === 'boolean') editor[key] = next
    else throw new TypeError('Invalid editor metadata')
  }
  if (JSON.stringify(editor).length > MAX_EDITOR_BYTES) throw new TypeError('Editor metadata is too large')
  return editor
}

export function normalizeRecoveryEntry(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('Invalid recovery entry')
  if (!JOB_ID.test(value.clientJobId || '') || !LOCAL_ID.test(value.localId || '')) throw new TypeError('Invalid recovery identifier')
  if (!RECOVERY_STATUSES.has(value.status) || value.uploadable !== false) throw new TypeError('Invalid recovery status')
  const file = value.file && typeof value.file === 'object' ? value.file : null
  if (!file || typeof file.name !== 'string' || !file.name.trim() || file.name.length > MAX_FILE_NAME) throw new TypeError('Invalid recovery filename')
  if (typeof file.type !== 'string' || file.type.length > MAX_FILE_TYPE) throw new TypeError('Invalid recovery file type')
  if (!Number.isSafeInteger(file.size) || file.size < 0) throw new TypeError('Invalid recovery file size')
  if (!Number.isSafeInteger(file.lastModified) || file.lastModified < 0) throw new TypeError('Invalid recovery file timestamp')
  const dimensions = (width, height) => {
    if (width == null && height == null) return { width: null, height: null }
    if (!Number.isSafeInteger(width) || width <= 0 || !Number.isSafeInteger(height) || height <= 0) throw new TypeError('Invalid recovery dimensions')
    return { width, height }
  }
  const { width, height } = dimensions(value.backendWidth, value.backendHeight)
  if (!Number.isSafeInteger(value.updatedAt) || !finiteNonNegative(value.updatedAt)) throw new TypeError('Invalid recovery timestamp')
  const createdAt = value.createdAt == null ? value.updatedAt : value.createdAt
  if (!Number.isSafeInteger(createdAt) || !finiteNonNegative(createdAt)) throw new TypeError('Invalid recovery timestamp')
  return {
    clientJobId: value.clientJobId.toLowerCase(),
    localId: value.localId,
    file: { name: file.name, type: file.type, size: file.size, lastModified: file.lastModified },
    status: value.status,
    uploadable: false,
    backendWidth: width,
    backendHeight: height,
    editor: normalizeEditor(value.editor),
    createdAt,
    updatedAt: value.updatedAt,
  }
}

const readRaw = (storage, key) => {
  const raw = storage.getItem(key)
  if (raw == null) return { entries: [], corrupt: false }
  const value = JSON.parse(raw)
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== RECOVERY_MANIFEST_VERSION || !Array.isArray(value.entries) || value.entries.length > MAX_RECOVERY_ENTRIES) throw new TypeError('Invalid recovery manifest')
  const entries = value.entries.map(normalizeRecoveryEntry)
  if (new Set(entries.map((entry) => entry.clientJobId)).size !== entries.length || new Set(entries.map((entry) => entry.localId)).size !== entries.length) throw new TypeError('Duplicate recovery identifier')
  return { entries, corrupt: false }
}

export function readRecoveryManifest(storage, key = RECOVERY_MANIFEST_KEY) {
  const resolved = resolveStorage(storage)
  if (!resolved) return { entries: [], corrupt: false, available: false }
  try { return { ...readRaw(resolved, key), available: true } } catch { return { entries: [], corrupt: true, available: true } }
}

function writeEntries(entries, storage, key) {
  const resolved = resolveStorage(storage)
  if (!resolved) return { ok: false, entries: [], available: false }
  try {
    const normalized = entries.map(normalizeRecoveryEntry)
    if (normalized.length > MAX_RECOVERY_ENTRIES) return { ok: false, entries: normalized, available: true, error: new RangeError('Recovery manifest is full') }
    if (new Set(normalized.map((entry) => entry.clientJobId)).size !== normalized.length || new Set(normalized.map((entry) => entry.localId)).size !== normalized.length) return { ok: false, entries: normalized, available: true, error: new TypeError('Duplicate recovery identifier') }
    resolved.setItem(key, JSON.stringify({ version: RECOVERY_MANIFEST_VERSION, entries: normalized }))
    return { ok: true, entries: normalized, available: true }
  } catch (error) { return { ok: false, entries, available: true, error } }
}

export function replaceRecoveryManifest(entries, storage, key = RECOVERY_MANIFEST_KEY) {
  const resolved = resolveStorage(storage)
  if (!resolved) return { ok: false, entries: [], available: false }
  const current = readRecoveryManifest(resolved, key)
  if (current.corrupt) return { ok: false, entries: [], available: true, corrupt: true }
  return writeEntries(entries, resolved, key)
}

export function upsertRecoveryEntry(entry, storage, key = RECOVERY_MANIFEST_KEY) {
  const resolved = resolveStorage(storage)
  if (!resolved) return { ok: false, entries: [], available: false }
  const current = readRecoveryManifest(resolved, key)
  if (current.corrupt) return { ok: false, entries: [], available: true, corrupt: true }
  let normalized
  try { normalized = normalizeRecoveryEntry(entry) } catch (error) { return { ok: false, entries: current.entries, available: true, error } }
  const remaining = current.entries.filter((candidate) => candidate.clientJobId !== normalized.clientJobId && candidate.localId !== normalized.localId)
  return writeEntries([...remaining, normalized], resolved, key)
}

export function removeRecoveryEntry(clientJobId, storage, key = RECOVERY_MANIFEST_KEY) {
  const resolved = resolveStorage(storage)
  if (!resolved) return { ok: false, entries: [], available: false }
  const current = readRecoveryManifest(resolved, key)
  if (current.corrupt) return { ok: false, entries: [], available: true, corrupt: true }
  if (!JOB_ID.test(clientJobId || '')) return { ok: false, entries: current.entries, available: true, error: new TypeError('Invalid recovery identifier') }
  return writeEntries(current.entries.filter((entry) => entry.clientJobId !== clientJobId.toLowerCase()), resolved, key)
}

export function recoveryEntryFromItem(item, status = item.status) {
  const file = item.fileMetadata || {
    name: item.file?.name || 'Recovered image',
    type: item.file?.type || 'application/octet-stream',
    size: Number.isSafeInteger(item.file?.size) ? item.file.size : 0,
    lastModified: Number.isSafeInteger(item.file?.lastModified) ? item.file.lastModified : 0,
  }
  return {
    clientJobId: item.clientJobId,
    localId: item.localId,
    file,
    status,
    uploadable: false,
    backendWidth: item.backendWidth,
    backendHeight: item.backendHeight,
    editor: item.editor || {},
    createdAt: item.recoveryCreatedAt || Date.now(),
    updatedAt: Date.now(),
  }
}
