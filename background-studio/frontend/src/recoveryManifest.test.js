import { describe, expect, it } from 'vitest'
import { RECOVERY_MANIFEST_KEY, readRecoveryManifest, removeRecoveryEntry, upsertRecoveryEntry } from './recoveryManifest.js'

const jobId = 'a'.repeat(32)
const memory = () => {
  const values = new Map()
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
}
const entry = (overrides = {}) => ({
  clientJobId: jobId,
  localId: 'local-1',
  file: { name: 'photo.png', type: 'image/png', size: 12, lastModified: 100 },
  status: 'ready',
  uploadable: false,
  backendWidth: 200,
  backendHeight: 100,
  editor: { threshold: 4, background: 'transparent', revision: 2 },
  createdAt: 100,
  updatedAt: 100,
  ...overrides,
})

describe('recovery manifest', () => {
  it('round-trips bounded metadata and removes one job', () => {
    const storage = memory()
    expect(upsertRecoveryEntry(entry(), storage)).toMatchObject({ ok: true })
    expect(readRecoveryManifest(storage).entries[0]).toMatchObject({ clientJobId: jobId, file: { name: 'photo.png' }, uploadable: false })
    expect(removeRecoveryEntry(jobId, storage)).toMatchObject({ ok: true })
    expect(readRecoveryManifest(storage).entries).toEqual([])
  })

  it('fails closed without overwriting malformed metadata', () => {
    const storage = memory()
    storage.setItem(RECOVERY_MANIFEST_KEY, '{not-json')
    expect(readRecoveryManifest(storage)).toMatchObject({ corrupt: true, entries: [] })
    expect(upsertRecoveryEntry(entry(), storage)).toMatchObject({ ok: false, corrupt: true })
    expect(storage.getItem(RECOVERY_MANIFEST_KEY)).toBe('{not-json')
  })

  it('rejects uploadable or invalid entries', () => {
    const storage = memory()
    expect(upsertRecoveryEntry(entry({ uploadable: true }), storage).ok).toBe(false)
    expect(upsertRecoveryEntry(entry({ backendWidth: 0 }), storage).ok).toBe(false)
    expect(readRecoveryManifest(storage).entries).toEqual([])
  })
})
