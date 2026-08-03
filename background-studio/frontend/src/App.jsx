import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { BATCH_STATUS, batchActions, batchReducer, createBatchItems, createInitialBatchState, selectNextQueuedItem } from './batchState.js'
import { addCleanupId, readCleanupLedger, removeCleanupId } from './cleanupLedger.js'
import { createThumbnail } from './thumbnails.js'

const presets = [['White', '#ffffff'], ['Black', '#000000'], ['Marketplace', '#f5f5f5']]
const MAX_POINTS = 2048
const REBALANCE_POINTS = 1024
const BATCH_UPLOAD_TIMEOUT_MS = 3 * 60 * 1000

async function fetchWithTimeout(url, options, timeoutMs, timeoutMessage) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } catch (caught) {
    if (caught?.name === 'AbortError') {
      const timeout = new Error(timeoutMessage)
      timeout.code = 'timeout'
      throw timeout
    }
    throw caught
  } finally {
    window.clearTimeout(timer)
  }
}

function apiError(response, fallback) {
  return response.json().then((body) => body.detail || fallback).catch(() => fallback)
}

function fittedRect(element, width, height) {
  const box = element.getBoundingClientRect()
  const scale = Math.min(box.width / width, box.height / height)
  const w = width * scale
  const h = height * scale
  return { left: (box.width - w) / 2, top: (box.height - h) / 2, width: w, height: h }
}

function normalizedPoint(event, viewport, clamp = false) {
  const { stageRect, imageRect } = viewport
  const x = (event.clientX - stageRect.left - imageRect.left) / imageRect.width
  const y = (event.clientY - stageRect.top - imageRect.top) / imageRect.height
  if (!clamp && (x < 0 || x > 1 || y < 0 || y > 1)) return null
  return [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))]
}

function compactPoints(points, limit = MAX_POINTS, pixelScale = { width: 1, height: 1 }) {
  if (points.length <= limit) return points
  const keep = new Set([0, points.length - 1])
  const segments = [[0, points.length - 1]]
  while (keep.size < limit && segments.length) {
    let bestSegment = -1; let bestIndex = -1; let bestDistance = -1
    for (let segmentIndex = 0; segmentIndex < segments.length; segmentIndex += 1) {
      const [start, end] = segments[segmentIndex]
      const [ax, ay] = points[start]; const [bx, by] = points[end]
      const dx = (bx - ax) * pixelScale.width; const dy = (by - ay) * pixelScale.height; const length2 = dx * dx + dy * dy
      for (let index = start + 1; index < end; index += 1) {
        const [px, py] = points[index]
        const apx = (px - ax) * pixelScale.width; const apy = (py - ay) * pixelScale.height
        const t = length2 ? Math.max(0, Math.min(1, (apx * dx + apy * dy) / length2)) : 0
        const ex = apx - t * dx; const ey = apy - t * dy
        const distance = ex * ex + ey * ey
        if (distance > bestDistance) { bestDistance = distance; bestIndex = index; bestSegment = segmentIndex }
      }
    }
    if (bestIndex < 0) break
    const [start, end] = segments.splice(bestSegment, 1)[0]
    keep.add(bestIndex); segments.push([start, bestIndex], [bestIndex, end])
  }
  return [...keep].sort((a, b) => a - b).map((index) => points[index])
}

function createPointStream(point, pixelScale) {
  return { active: [point], pixelScale }
}

function appendStreamPoint(stream, point) {
  const active = [...stream.active, point]
  if (active.length < MAX_POINTS) return { ...stream, active }
  // Once the terminal budget is approached, rebalance the complete ordered
  // geometry instead of freezing early chunks and starving all later motion.
  return { ...stream, active: compactPoints(active, REBALANCE_POINTS, stream.pixelScale) }
}

function streamPoints(stream) {
  return compactPoints(stream.active, MAX_POINTS, stream.pixelScale)
}

export default function App() {
  const [batch, batchDispatch] = useReducer(batchReducer, undefined, createInitialBatchState)
  const [announcement, setAnnouncement] = useState('')
  const [queuePaused, setQueuePaused] = useState(false)
  const [queueProcessing, setQueueProcessing] = useState(false)
  const [job, setJob] = useState(null)
  const [processing, setProcessing] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [mutating, setMutating] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [threshold, setThreshold] = useState(0)
  const [feather, setFeather] = useState(0)
  const [background, setBackground] = useState('transparent')
  const [color, setColor] = useState('#ffffff')
  const [compare, setCompare] = useState(50)
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewNonce, setPreviewNonce] = useState(0)
  const [mode, setMode] = useState('remove')
  const [brushSize, setBrushSize] = useState(36)
  const [softness, setSoftness] = useState(0.35)
  const [strokeCount, setStrokeCount] = useState(0)
  const [drawing, setDrawing] = useState(false)
  const [livePoints, setLivePoints] = useState([])
  const [cursor, setCursor] = useState(null)
  const [imageRect, setImageRect] = useState(null)
  const [previewReady, setPreviewReady] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [previewIdentity, setPreviewIdentity] = useState(null)
  const [uncertainty, setUncertainty] = useState({ causes: {} })

  const ingestionRef = useRef(null)
  const mutationRef = useRef(null)
  const exportRef = useRef(null)
  const deletionRef = useRef(null)
  const uncertaintyRef = useRef({ causes: {} })
  const errorOwnerRef = useRef(null)
  const jobRef = useRef(null)
  const previewUrlRef = useRef('')
  const previewRequestRef = useRef(0)
  const previewIdentityRef = useRef(null)
  const previewReadyRef = useRef(false)
  const serverRevisionRef = useRef(0)
  const inputRef = useRef(null)
  const stageRef = useRef(null)
  const activePointerRef = useRef(null)
  const normalizedPointsRef = useRef(null)
  const activeBrushRef = useRef(null)
  const keyboardPointRef = useRef([0.5, 0.5])
  const batchRef = useRef(batch)
  const queueOperationRef = useRef(null)
  const batchGenerationRef = useRef(0)
  const selectedLocalIdRef = useRef(null)
  const localItemSequenceRef = useRef(0)
  const queuePausedItemRef = useRef(null)
  const liveItemIdsRef = useRef(new Set())

  useEffect(() => { jobRef.current = job }, [job])
  useEffect(() => { batchRef.current = batch }, [batch])
  const replacePreviewUrl = useCallback((next, identity = null) => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    previewUrlRef.current = next
    previewIdentityRef.current = next ? identity : null
    setPreviewIdentity(next ? identity : null)
    previewReadyRef.current = false
    setPreviewReady(false)
    setPreviewUrl(next)
  }, [])

  const invalidatePreview = () => {
    previewRequestRef.current += 1
    previewReadyRef.current = false
    setPreviewReady(false)
  }

  const previewIsCurrent = () => {
    const identity = previewIdentityRef.current
    return previewReadyRef.current && identity && identity.jobId === jobRef.current?.id && identity.requestId === previewRequestRef.current
  }

  const stateBlocked = () => Object.keys(uncertaintyRef.current.causes).length > 0
  const replaceUncertainty = (causes) => {
    const next = { causes }
    uncertaintyRef.current = next
    setUncertainty(next)
  }
  const addUncertainty = (key, cause, jobIds, cleanupIds = jobIds) => {
    replaceUncertainty({ ...uncertaintyRef.current.causes, [key]: { cause, jobIds: [...new Set(jobIds.filter(Boolean))], cleanupIds: [...new Set(cleanupIds.filter(Boolean))] } })
  }
  const clearUncertainty = (key) => {
    const causes = { ...uncertaintyRef.current.causes }
    delete causes[key]
    replaceUncertainty(causes)
  }
  const affectedJobIds = () => [...new Set(Object.values(uncertaintyRef.current.causes).flatMap((entry) => entry.jobIds))]
  const cleanupJobIds = () => [...new Set(Object.values(uncertaintyRef.current.causes).flatMap((entry) => entry.cleanupIds || entry.jobIds))]
  const setOwnedError = (message, owner) => {
    errorOwnerRef.current = owner
    setError(message)
  }
  const clearOwnedError = (owner) => {
    if (errorOwnerRef.current === owner) {
      errorOwnerRef.current = null
      setError('')
    }
  }

  const changePreviewSetting = (setter, value) => {
    invalidatePreview()
    setter(value)
  }

  const clearBrushState = () => {
    activePointerRef.current = null
    normalizedPointsRef.current = null
    activeBrushRef.current = null
    setDrawing(false)
    setLivePoints([])
    setCursor(null)
    setStrokeCount(0)
    setMode('remove')
    setBrushSize(36)
    setSoftness(0.35)
    keyboardPointRef.current = [0.5, 0.5]
    setImageRect(null)
  }

  const expireCurrentJob = (jobId, message = 'This image expired. Choose a new image.') => {
    if (jobRef.current?.id !== jobId) return
    invalidatePreview()
    jobRef.current = null
    setJob(null)
    selectedLocalIdRef.current = null
    const expired = batchRef.current.items.find((item) => item.clientJobId === jobId)
    if (expired) batchDispatch(batchActions.failed(expired.localId, message))
    clearBrushState()
    replacePreviewUrl('')
    setOwnedError(message, `expired:${jobId}`)
  }

  const deleteJob = async (jobId, fallback = 'Delete failed.') => {
    let lastTransportError
    for (let attempt = 0; attempt < 3; attempt += 1) {
      let response
      try {
        response = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' })
      } catch (error) {
        lastTransportError = error
        continue
      }
      if (response.status === 204 || response.status === 410) return
      if (response.status === 404) {
        const reconciled = await reconcileJob(jobId)
        if (reconciled.state === 'deleted') return
        lastTransportError = new Error('Deletion returned an unknown result.')
        continue
      }
      if (!response.ok) throw new Error(await apiError(response, fallback))
      return
    }
    const failure = lastTransportError || new Error(fallback)
    failure.deleteTransportFailure = true
    throw failure
  }

  const postJob = async (form) => {
    let lastError
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        return await fetch('/api/jobs', { method: 'POST', body: form })
      } catch (error) {
        lastError = error
      }
    }
    throw lastError
  }

  const validJobPayload = (value, expectedId) => value && value.id === expectedId
    && Number.isInteger(value.width) && value.width > 0
    && Number.isInteger(value.height) && value.height > 0

  const reconcileJob = async (jobId) => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`, { cache: 'no-store' })
      if (response.status === 404) return { state: 'unknown' }
      if (response.status === 410) {
        try {
          const value = await response.json()
          return value?.state === 'tombstoned' || value?.state === 'failed' ? { state: 'deleted' } : { state: 'unknown' }
        } catch { return { state: 'unknown' } }
      }
      if (response.status === 202) return { state: 'creating' }
      if (!response.ok) return { state: 'unknown' }
      const value = await response.json()
      return validJobPayload(value, jobId) ? { state: 'present', job: value } : { state: 'unknown' }
    } catch {
      return { state: 'unknown' }
    }
  }

  const legacyIngest = useCallback(async (file) => {
    if (!file || ingestionRef.current || mutationRef.current || exportRef.current || deletionRef.current || activePointerRef.current !== null) return
    const operation = Symbol('ingestion')
    ingestionRef.current = operation
    setProcessing(true)
    clearOwnedError(errorOwnerRef.current)
    let oldJob = jobRef.current
    const requestId = crypto.randomUUID().replaceAll('-', '')
    const form = new FormData()
    form.append('file', file)
    form.append('job_id', requestId)
    try {
      if (stateBlocked()) {
        const cleanupIds = cleanupJobIds()
        for (const cleanupId of cleanupIds) await deleteJob(cleanupId, 'Could not finish pending cleanup.')
        replaceUncertainty({})
        if (oldJob && cleanupIds.includes(oldJob.id)) {
          oldJob = null
          jobRef.current = null
          setJob(null); clearBrushState(); replacePreviewUrl('')
        }
      }

      let response
      let uploadFailure = null
      try {
        response = await postJob(form)
      } catch (error) {
        uploadFailure = error
      }
      if (response && !response.ok) throw new Error(await apiError(response, 'Upload failed.'))
      let nextJob
      if (response) {
        try { nextJob = await response.json() } catch (error) { uploadFailure = error }
        if (!validJobPayload(nextJob, requestId)) uploadFailure = uploadFailure || new Error('Upload returned an invalid result.')
      }
      if (uploadFailure) {
        const recovered = await reconcileJob(requestId)
        if (recovered.state === 'present') nextJob = recovered.job
        else if (recovered.state === 'deleted') throw uploadFailure
        else {
          addUncertainty(`upload:${requestId}`, 'upload-outcome', [oldJob?.id, requestId])
          throw new Error('The upload may have succeeded, but its result could not be verified. All affected images are preserved and editing is blocked until cleanup is retried.')
        }
      }
      if (ingestionRef.current !== operation) return

      if (oldJob && oldJob.id !== nextJob.id) {
        try {
          await deleteJob(oldJob.id, 'Could not remove the previous image.')
        } catch (deleteError) {
          if (deleteError.deleteTransportFailure) {
            addUncertainty(`replacement:${requestId}`, 'delete-outcome', [oldJob.id, nextJob.id])
            throw new Error('The previous image deletion could not be verified. Both image IDs remain authoritative and editing is blocked until cleanup is retried.')
          }
          try {
            await deleteJob(nextJob.id, 'Could not clean up the replacement image.')
          } catch (cleanupError) {
            addUncertainty(`rollback:${requestId}`, 'rollback-cleanup', [oldJob.id, nextJob.id], [nextJob.id])
            throw new Error(`${deleteError.message} ${cleanupError.message}`)
          }
          throw deleteError
        }
      }
      jobRef.current = nextJob
      setJob(nextJob)
      setThreshold(0); setFeather(0); changePreviewSetting(setBackground, 'transparent'); setCompare(50)
      clearBrushState()
      replacePreviewUrl('')
      serverRevisionRef.current = 0
      setPreviewNonce((value) => value + 1)
    } catch (caught) {
      if (ingestionRef.current === operation) setOwnedError(caught.message || 'Upload failed.', stateBlocked() ? 'uncertainty' : operation)
    } finally {
      if (ingestionRef.current === operation) {
        ingestionRef.current = null
        setProcessing(false)
        if (inputRef.current) inputRef.current.value = ''
      }
    }
  }, [replacePreviewUrl])

  const waitForBatchCreate = async (jobId, attempts = 3) => {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const outcome = await reconcileJob(jobId)
      if (outcome.state !== 'creating') return outcome
      if (attempt + 1 < attempts) await new Promise((resolve) => window.setTimeout(resolve, 25))
    }
    return { state: 'creating' }
  }

  const cancelBatchJob = useCallback(async (jobId) => {
    const response = await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
    if (response.status === 204) {
      const removed = removeCleanupId(jobId)
      if (!removed.ok) throw new Error('Backend cleanup completed, but browser cleanup storage could not be updated.')
      return 'complete'
    }
    if (response.status === 202) return 'pending'
    throw new Error(await apiError(response, 'Cleanup failed.'))
  }, [])

  const ingest = useCallback((fileOrFiles) => {
    const files = Array.from(fileOrFiles instanceof FileList || Array.isArray(fileOrFiles) ? fileOrFiles : [fileOrFiles]).filter(Boolean)
    const slots = Math.max(0, 10 - batchRef.current.items.length)
    if (!files.length || !slots || queueOperationRef.current || mutationRef.current || exportRef.current || deletionRef.current) return
    const admitted = createBatchItems(files.slice(0, slots), {
      localIdFactory: () => `local-${localItemSequenceRef.current += 1}`,
      jobIdFactory: () => crypto.randomUUID().replaceAll('-', ''),
    })
    admitted.forEach((item) => liveItemIdsRef.current.add(item.localId))
    batchDispatch(batchActions.admit(admitted))
    for (const item of admitted) {
      createThumbnail(item.file).then((thumbnail) => {
        if (liveItemIdsRef.current.has(item.localId)) batchDispatch(batchActions.thumbnailReady(item.localId, thumbnail))
        else thumbnail.revoke()
      }).catch((caught) => {
        batchDispatch(batchActions.thumbnailFailed(item.localId, caught.message || 'Thumbnail unavailable'))
      })
    }
    if (inputRef.current) inputRef.current.value = ''
  }, [])

  useEffect(() => {
    const next = selectNextQueuedItem(batch)
    if (!next || queuePaused || queueOperationRef.current) return undefined
    const generation = batchGenerationRef.current
    const operation = Symbol(next.localId)
    queueOperationRef.current = operation
    batchDispatch(batchActions.processing(next.localId))
    setQueueProcessing(true)
    const run = async () => {
      const ledger = addCleanupId(next.clientJobId)
      if (!ledger.ok) throw new Error(ledger.corrupt ? 'Cleanup ledger is corrupt. Reload this page before uploading.' : 'Browser cleanup storage is unavailable.')
      const form = new FormData()
      form.append('file', next.file)
      form.append('job_id', next.clientJobId)
      let response
      let transportError
      try {
        response = await fetchWithTimeout(
          '/api/jobs',
          { method: 'POST', body: form },
          BATCH_UPLOAD_TIMEOUT_MS,
          'Image processing timed out while waiting for the inference worker. Retry when Runpod is ready.',
        )
      } catch (caught) { transportError = caught }
      let nextJob
      if (response?.ok) {
        try { nextJob = await response.json() } catch (caught) { transportError = caught }
        if (!validJobPayload(nextJob, next.clientJobId)) transportError = transportError || new Error('Upload returned an invalid result.')
      } else if (response) {
        if (response.status === 507) { setQueuePaused(true); queuePausedItemRef.current = next.localId }
        transportError = new Error(await apiError(response, 'Upload failed.'))
      }
      if (transportError) {
        const recovered = await waitForBatchCreate(next.clientJobId)
        if (recovered.state === 'present') nextJob = recovered.job
        else if (recovered.state === 'deleted') throw transportError
        else {
          try {
            await cancelBatchJob(next.clientJobId)
          } catch (cleanupError) {
            batchDispatch(batchActions.cleanupStatus(next.localId, 'unverified', transportError.message || 'Upload result could not be verified.'))
            setAnnouncement(`${next.file.name} is awaiting safe cleanup.`)
            return
          }
          throw transportError
        }
      }
      if (generation !== batchGenerationRef.current) {
        try { await cancelBatchJob(next.clientJobId) } catch (caught) { setOwnedError(caught.message || 'Cleanup storage update failed.', `cleanup:${next.clientJobId}`) }
        return
      }
      batchDispatch(batchActions.ready(next.localId, nextJob))
      setAnnouncement(`${next.file.name} is ready.`)
    }
    run().catch((caught) => {
      if (generation === batchGenerationRef.current) {
        batchDispatch(batchActions.failed(next.localId, caught.message || 'Processing failed.'))
        setAnnouncement(`${next.file.name} failed.`)
      }
    }).finally(() => {
      if (queueOperationRef.current === operation) {
        queueOperationRef.current = null
        setQueueProcessing(false)
      }
    })
    return undefined
  }, [batch, cancelBatchJob, queuePaused])

  useEffect(() => {
    const item = batch.items.find((candidate) => candidate.localId === batch.selectedLocalId && candidate.status === BATCH_STATUS.READY)
    if (!item || selectedLocalIdRef.current === item.localId) return
    selectedLocalIdRef.current = item.localId
    const editor = item.editor || {}
    const nextJob = { id: item.clientJobId, width: item.backendWidth, height: item.backendHeight }
    jobRef.current = nextJob
    setJob(nextJob)
    setThreshold(editor.threshold ?? 0); setFeather(editor.feather ?? 0); setBackground(editor.background ?? 'transparent'); setColor(editor.color ?? '#ffffff'); setCompare(editor.compare ?? 50)
    setMode(editor.mode ?? 'remove'); setBrushSize(editor.brushSize ?? 36); setSoftness(editor.softness ?? 0.35); setStrokeCount(editor.strokeCount ?? 0)
    serverRevisionRef.current = editor.revision ?? 0
    replacePreviewUrl('')
    setPreviewNonce((value) => value + 1)
  }, [batch.selectedLocalId, batch.items, replacePreviewUrl])

  useEffect(() => {
    if (!batch.selectedLocalId) return
    batchDispatch(batchActions.editorPatch(batch.selectedLocalId, { threshold, feather, background, color, compare, mode, brushSize, softness, strokeCount, revision: serverRevisionRef.current }))
  }, [threshold, feather, background, color, compare, mode, brushSize, softness, strokeCount, batch.selectedLocalId])

  useEffect(() => {
    const ledger = readCleanupLedger()
    if (ledger.corrupt) {
      setOwnedError('Cleanup ledger is corrupt. Reload the page before uploading.', 'ledger')
      return
    }
    ledger.ids.forEach((jobId) => {
      const owned = batchRef.current.items.some((item) => item.clientJobId === jobId && (item.status === BATCH_STATUS.PROCESSING || item.status === BATCH_STATUS.READY))
      if (owned) return
      cancelBatchJob(jobId).then(() => {
        const item = batchRef.current.items.find((candidate) => candidate.clientJobId === jobId && candidate.status === BATCH_STATUS.CLEANUP_PENDING)
        if (item) batchDispatch(batchActions.failed(item.localId, item.cleanup?.error || 'Upload result could not be verified.'))
      }).catch((caught) => setOwnedError(caught.message || 'Cleanup storage update failed.', `cleanup:${jobId}`))
    })
  }, [cancelBatchJob])

  useEffect(() => {
    const timer = window.setInterval(() => {
      const ready = batchRef.current.items.filter((item) => item.status === BATCH_STATUS.READY)
      const active = new Set(batchRef.current.items.filter((item) => item.status === BATCH_STATUS.PROCESSING).map((item) => item.clientJobId))
      ready.forEach((item) => { fetch(`/api/jobs/${item.clientJobId}/touch`, { method: 'POST' }).catch(() => {}) })
      const ledger = readCleanupLedger()
      if (!ledger.corrupt) ledger.ids.filter((id) => !ready.some((item) => item.clientJobId === id) && !active.has(id)).forEach((id) => {
        cancelBatchJob(id).then(() => {
          const item = batchRef.current.items.find((candidate) => candidate.clientJobId === id && candidate.status === BATCH_STATUS.CLEANUP_PENDING)
          if (item) batchDispatch(batchActions.failed(item.localId, item.cleanup?.error || 'Upload result could not be verified.'))
        }).catch((caught) => setOwnedError(caught.message || 'Cleanup storage update failed.', `cleanup:${id}`))
      })
    }, 10 * 60 * 1000)
    return () => window.clearInterval(timer)
  }, [cancelBatchJob])

  const retryBatchItem = async (item) => {
    try {
      await cancelBatchJob(item.clientJobId)
      batchDispatch(batchActions.retry(item.localId, crypto.randomUUID().replaceAll('-', '')))
    } catch (caught) { setOwnedError(caught.message || 'Retry cleanup failed.', `retry:${item.localId}`) }
  }

  const removeBatchItem = async (item) => {
    try {
      await cancelBatchJob(item.clientJobId)
      item.thumbnailRevoke?.()
      liveItemIdsRef.current.delete(item.localId)
      batchDispatch(batchActions.remove(item.localId))
      if (selectedLocalIdRef.current === item.localId) { selectedLocalIdRef.current = null; jobRef.current = null; setJob(null); replacePreviewUrl('') }
    } catch (caught) { setOwnedError(caught.message || 'Remove failed.', `remove:${item.localId}`) }
  }

  const resetBatch = async () => {
    batchGenerationRef.current += 1
    const items = batchRef.current.items
    liveItemIdsRef.current.clear()
    items.forEach((item) => { item.thumbnailRevoke?.(); cancelBatchJob(item.clientJobId).catch((caught) => setOwnedError(caught.message || 'Cleanup storage update failed.', `cleanup:${item.clientJobId}`)) })
    selectedLocalIdRef.current = null; jobRef.current = null; setJob(null); replacePreviewUrl(''); clearBrushState()
    batchDispatch(batchActions.reset())
    setQueuePaused(false)
    queuePausedItemRef.current = null
    setAnnouncement('Started a new batch.')
  }

  useEffect(() => {
    const onPaste = (event) => {
      if (mutationRef.current || exportRef.current || deletionRef.current || activePointerRef.current !== null) return
      const item = Array.from(event.clipboardData?.items || []).find((entry) => entry.type.startsWith('image/'))
      if (item) ingest(item.getAsFile())
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [ingest])

  const updateImageRect = useCallback(() => {
    if (stageRef.current && job) setImageRect(fittedRect(stageRef.current, job.width, job.height))
  }, [job])

  useEffect(() => {
    updateImageRect()
    if (!stageRef.current) return undefined
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updateImageRect)
    observer?.observe(stageRef.current)
    window.addEventListener('resize', updateImageRect)
    return () => { observer?.disconnect(); window.removeEventListener('resize', updateImageRect) }
  }, [updateImageRect])

  useEffect(() => {
    if (!job || (background === 'solid' && !/^#[0-9a-fA-F]{6}$/.test(color))) {
      invalidatePreview()
      setPreviewing(false)
      return undefined
    }
    const controller = new AbortController()
    const requestId = ++previewRequestRef.current
    const previewJobId = job.id
    const previewErrorOwner = 'preview'
    previewReadyRef.current = false
    setPreviewReady(false)
    const timer = window.setTimeout(async () => {
      setPreviewing(true)
      const params = new URLSearchParams({ threshold: String(threshold / 100), feather: String(feather), background: background === 'transparent' ? 'transparent' : color, revision: String(serverRevisionRef.current) })
      try {
        const response = await fetch(`/api/jobs/${job.id}/preview?${params}`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error(await apiError(response, 'Preview failed.'))
        const blob = await response.blob()
        if (requestId !== previewRequestRef.current || jobRef.current?.id !== previewJobId) return
        const url = URL.createObjectURL(blob)
        replacePreviewUrl(url, { jobId: previewJobId, url, requestId })
      } catch (caught) {
        if (
          caught.name !== 'AbortError'
          && requestId === previewRequestRef.current
          && jobRef.current?.id === previewJobId
        ) setOwnedError(caught.message || 'Preview failed.', previewErrorOwner)
      } finally {
        if (!controller.signal.aborted && requestId === previewRequestRef.current) setPreviewing(false)
      }
    }, 180)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [job, threshold, feather, background, color, previewNonce, replacePreviewUrl])

  useEffect(() => () => { if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current) }, [])

  const runMutation = async (path, options) => {
    const currentJob = jobRef.current
    if (!currentJob || stateBlocked() || mutationRef.current || ingestionRef.current || exportRef.current || deletionRef.current || activePointerRef.current !== null) return null
    const jobId = currentJob.id
    const operation = Symbol('mutation')
    mutationRef.current = operation
    setMutating(true)
    clearOwnedError(errorOwnerRef.current)
    try {
      let response
      try {
        response = await fetch(`/api/jobs/${jobId}${path}`, options)
      } catch (transportError) {
        if (mutationRef.current === operation && jobRef.current?.id === jobId) {
          addUncertainty(`mutation:${jobId}`, 'mutation-outcome', [jobId]); invalidatePreview()
          setOwnedError('The mask update may have succeeded, but its response was lost. Editing and export are blocked; choose New image to restore a known state.', 'uncertainty')
        }
        return null
      }
      if (response.status === 404 || response.status === 410) {
        expireCurrentJob(jobId)
        return null
      }
      if (!response.ok) throw new Error(await apiError(response, 'Mask update failed.'))
      let result
      try {
        result = await response.json()
      } catch {
        if (mutationRef.current === operation && jobRef.current?.id === jobId) {
          addUncertainty(`mutation:${jobId}`, 'mutation-result', [jobId]); invalidatePreview()
          setOwnedError('The mask update may have succeeded, but its result was incomplete. Editing and export are blocked; choose New image to restore a known state.', 'uncertainty')
        }
        return null
      }
      if (!result || !Number.isInteger(result.count) || result.count < 0 || !Number.isInteger(result.revision) || result.revision < 0) {
        if (mutationRef.current === operation && jobRef.current?.id === jobId) {
          addUncertainty(`mutation:${jobId}`, 'mutation-invalid-result', [jobId]); invalidatePreview()
          setOwnedError('The mask update returned an invalid result. Editing and export are blocked; choose New image to restore a known state.', 'uncertainty')
        }
        return null
      }
      if (mutationRef.current !== operation || jobRef.current?.id !== jobId) return null
      setStrokeCount(result.count)
      serverRevisionRef.current = result.revision
      invalidatePreview()
      setPreviewNonce((value) => value + 1)
      return result
    } catch (caught) {
      if (mutationRef.current === operation && jobRef.current?.id === jobId) setOwnedError(caught.message || 'Mask update failed.', operation)
      return null
    } finally {
      if (mutationRef.current === operation) {
        mutationRef.current = null
        setMutating(false)
      }
    }
  }

  const pointerPosition = (event, viewport = null, clamp = false) => {
    if (!stageRef.current) return null
    const geometry = viewport || (imageRect ? { stageRect: stageRef.current.getBoundingClientRect(), imageRect: { ...imageRect } } : null)
    if (!geometry) return null
    const point = normalizedPoint(event, geometry, clamp)
    if (!point) return null
    const rect = geometry.imageRect
    return { normalized: point, pixel: [rect.left + point[0] * rect.width, rect.top + point[1] * rect.height], viewport: geometry }
  }

  const onPointerDown = (event) => {
    if (!previewIsCurrent() || stateBlocked() || compare !== 0 || ingestionRef.current || mutationRef.current || exportRef.current || deletionRef.current || activePointerRef.current !== null || event.isPrimary === false || event.button !== 0) return
    if (typeof event.currentTarget.setPointerCapture !== 'function') return
    const position = pointerPosition(event)
    if (!position) return
    event.preventDefault()
    activePointerRef.current = event.pointerId
    normalizedPointsRef.current = createPointStream(position.normalized, {
      width: position.viewport.imageRect.width,
      height: position.viewport.imageRect.height,
    })
    activeBrushRef.current = { mode, brushSize, softness, viewport: position.viewport }
    setLivePoints([position.pixel])
    setCursor(position.pixel)
    setDrawing(true)
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      activePointerRef.current = null
      normalizedPointsRef.current = null
      activeBrushRef.current = null
      setDrawing(false)
      setLivePoints([])
      setCursor(null)
    }
  }

  const onPointerMove = (event) => {
    const active = activePointerRef.current === event.pointerId
    if (activePointerRef.current !== null && !active) return
    const hoverPosition = pointerPosition(event)
    const canDraw = previewIsCurrent() && !stateBlocked() && compare === 0 && !ingestionRef.current && !mutationRef.current && !exportRef.current && !deletionRef.current
    if (!active) setCursor(canDraw ? (hoverPosition?.pixel || null) : null)
    if (!active) return
    const activeBrush = activeBrushRef.current
    const position = pointerPosition(event, activeBrush.viewport, true)
    if (!position) return
    const stream = normalizedPointsRef.current
    const last = stream.active[stream.active.length - 1]
    const dx = (position.normalized[0] - last[0]) * activeBrush.viewport.imageRect.width
    const dy = (position.normalized[1] - last[1]) * activeBrush.viewport.imageRect.height
    if (Math.hypot(dx, dy) < Math.max(1.5, activeBrush.brushSize / 8)) return
    normalizedPointsRef.current = appendStreamPoint(stream, position.normalized)
    setLivePoints((current) => current.length < MAX_POINTS ? [...current, position.pixel] : [...current.slice(1), position.pixel])
    setCursor(position.pixel)
  }

  const discardStroke = (event) => {
    if (activePointerRef.current !== event.pointerId) return
    activePointerRef.current = null
    try { event.currentTarget.releasePointerCapture?.(event.pointerId) } catch {}
    normalizedPointsRef.current = null
    activeBrushRef.current = null
    setDrawing(false)
    setLivePoints([])
    setCursor(null)
  }

  const finishStroke = async (event, includeTerminal = true) => {
    if (activePointerRef.current !== event.pointerId) return
    const activeBrush = activeBrushRef.current
    const terminal = includeTerminal
      ? pointerPosition(event, activeBrush.viewport, true)
      : null
    activePointerRef.current = null
    try { event.currentTarget.releasePointerCapture?.(event.pointerId) } catch {}
    let points = streamPoints(normalizedPointsRef.current)
    normalizedPointsRef.current = null
    activeBrushRef.current = null
    if (terminal) {
      const last = points[points.length - 1]
      if (!last || terminal.normalized[0] !== last[0] || terminal.normalized[1] !== last[1]) points.push(terminal.normalized)
    }
    points = compactPoints(points, MAX_POINTS, {
      width: activeBrush.viewport.imageRect.width,
      height: activeBrush.viewport.imageRect.height,
    })
    if (points.length === 1) {
      const [x, y] = points[0]
      const epsilon = Math.min(1, 1 / activeBrush.viewport.imageRect.width)
      points.push([x >= 1 ? Math.max(0, x - epsilon) : Math.min(1, x + epsilon), y])
    }
    setDrawing(false)
    setLivePoints([])
    if (!includeTerminal) setCursor(null)
    if (points.length < 2) return
    const radius = Math.max(0.0001, Math.min(1, activeBrush.brushSize / Math.min(activeBrush.viewport.imageRect.width, activeBrush.viewport.imageRect.height)))
    await runMutation('/strokes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: activeBrush.mode, radius, softness: activeBrush.softness, points }) })
  }

  const undoStroke = async () => {
    if (!strokeCount || ingestionRef.current || mutationRef.current || exportRef.current || activePointerRef.current !== null) return
    await runMutation('/strokes/last', { method: 'DELETE' })
  }
  const resetStrokes = async () => {
    if (!strokeCount || ingestionRef.current || mutationRef.current || exportRef.current || activePointerRef.current !== null) return
    await runMutation('/strokes', { method: 'DELETE' })
  }

  const reset = async () => {
    if (ingestionRef.current || mutationRef.current || exportRef.current || deletionRef.current || activePointerRef.current !== null) return
    const oldJob = jobRef.current
    const cleanupIds = [...new Set([oldJob?.id, ...affectedJobIds()].filter(Boolean))]
    if (!cleanupIds.length) return
    const operation = Symbol('deletion')
    deletionRef.current = operation
    setDeleting(true)
    clearOwnedError(errorOwnerRef.current)
    try {
      for (const cleanupId of cleanupIds) await deleteJob(cleanupId, 'Could not remove this image.')
      if (deletionRef.current !== operation) return
      jobRef.current = null
      replaceUncertainty({})
      setJob(null); clearBrushState(); replacePreviewUrl('')
    } catch (caught) {
      if (deletionRef.current === operation) {
        if (caught.deleteTransportFailure) addUncertainty(`cleanup:${cleanupIds.join(':')}`, 'cleanup-outcome', cleanupIds)
        setOwnedError(caught.message || 'Could not remove this image.', stateBlocked() ? 'uncertainty' : operation)
      }
    } finally {
      if (deletionRef.current === operation) {
        deletionRef.current = null
        setDeleting(false)
      }
    }
  }

  const exportImage = async (format, bg) => {
    const currentJob = jobRef.current
    if (!currentJob || stateBlocked() || ingestionRef.current || mutationRef.current || exportRef.current || deletionRef.current || activePointerRef.current !== null) return
    const operation = Symbol('export')
    exportRef.current = operation
    setExporting(true)
    clearOwnedError(errorOwnerRef.current)
    const params = new URLSearchParams({ threshold: String(threshold / 100), feather: String(feather), background: bg, format })
    try {
      const response = await fetch(`/api/jobs/${currentJob.id}/export?${params}`, { cache: 'no-store' })
      if (response.status === 404 || response.status === 410) {
        expireCurrentJob(currentJob.id)
        return
      }
      if (!response.ok) throw new Error(await apiError(response, 'Export failed.'))
      const blob = await response.blob()
      if (exportRef.current !== operation || jobRef.current?.id !== currentJob.id) return
      const url = URL.createObjectURL(blob)
      try {
        const link = document.createElement('a')
        link.href = url
        link.download = format === 'png' ? 'background-studio.png' : 'background-studio.jpg'
        document.body.appendChild(link); link.click(); link.remove()
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch (caught) {
      if (exportRef.current === operation) setOwnedError(caught.message || 'Export failed.', operation)
    } finally {
      if (exportRef.current === operation) {
        exportRef.current = null
        setExporting(false)
      }
    }
  }

  const onStageKeyDown = async (event) => {
    if (!previewIsCurrent() || stateBlocked() || compare !== 0 || ingestionRef.current || mutationRef.current || exportRef.current || deletionRef.current || activePointerRef.current !== null || !imageRect) return
    const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }
    if (arrows[event.key]) {
      event.preventDefault()
      const stepX = Math.max(1, brushSize / 2) / imageRect.width
      const stepY = Math.max(1, brushSize / 2) / imageRect.height
      const [dx, dy] = arrows[event.key]
      const point = keyboardPointRef.current
      keyboardPointRef.current = [Math.max(0, Math.min(1, point[0] + dx * stepX)), Math.max(0, Math.min(1, point[1] + dy * stepY))]
      setCursor([imageRect.left + keyboardPointRef.current[0] * imageRect.width, imageRect.top + keyboardPointRef.current[1] * imageRect.height])
      return
    }
    if (event.key !== ' ' && event.key !== 'Enter') return
    event.preventDefault()
    const [x, y] = keyboardPointRef.current
    const epsilon = Math.min(1, 1 / imageRect.width)
    const points = [[x, y], [x >= 1 ? Math.max(0, x - epsilon) : Math.min(1, x + epsilon), y]]
    const radius = Math.max(0.0001, Math.min(1, brushSize / Math.min(imageRect.width, imageRect.height)))
    await runMutation('/strokes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, radius, softness, points }) })
  }

  const stateUncertain = Object.keys(uncertainty.causes).length > 0
  const validColor = /^#[0-9a-fA-F]{6}$/.test(color)
  const paintColor = mode === 'remove' ? '#ef4444' : '#22c55e'
  const painting = drawing || mutating
  const globallyBusy = processing || mutating || exporting || deleting || drawing
  const controlsBlocked = globallyBusy || stateUncertain
  const brushEnabled = previewReady && !stateUncertain && compare === 0 && !globallyBusy
  const readyItems = batch.items.filter((item) => item.status === BATCH_STATUS.READY)
  const readyIndex = readyItems.findIndex((item) => item.localId === batch.selectedLocalId)
  const editorBusy = mutating || exporting || deleting || drawing || activePointerRef.current !== null
  const resumeQueue = () => {
    const item = batchRef.current.items.find((candidate) => candidate.localId === queuePausedItemRef.current && candidate.status === BATCH_STATUS.FAILED)
    if (item) batchDispatch(batchActions.retry(item.localId, crypto.randomUUID().replaceAll('-', '')))
    queuePausedItemRef.current = null
    setQueuePaused(false)
  }

  useEffect(() => {
    if (!brushEnabled && activePointerRef.current === null) setCursor(null)
  }, [brushEnabled])

  return <main className="shell">
    <header className="app-header"><div><p className="eyebrow">Image editing workspace</p><h1>Background Studio</h1></div>
      {(batch.items.length > 0 || stateUncertain) && <button className="secondary" disabled={mutating || exporting || deleting || drawing} onClick={resetBatch}>New batch</button>}
    </header>
    {error && <div className="error" role="alert">{error}</div>}
    <p className="sr-only" aria-live="polite">{announcement}</p>
    {batch.items.length > 0 && <section className="batch-queue" aria-label="Batch queue">
      <div className="batch-heading"><h2>Photos</h2><span>{batch.items.length} / 10</span>{queuePaused && <button className="secondary" disabled={editorBusy || !batch.items.some((item) => item.localId === queuePausedItemRef.current && item.status === BATCH_STATUS.FAILED)} onClick={resumeQueue}>Resume queue</button>}</div>
      <ul className="batch-items">{batch.items.map((item, index) => <li key={item.localId} className={`batch-item status-${item.status}`} aria-current={item.localId === batch.selectedLocalId ? 'true' : undefined}>
        <button className="batch-select" disabled={item.status !== BATCH_STATUS.READY || editorBusy} onClick={() => batchDispatch(batchActions.select(item.localId))} aria-label={`Select ${item.file.name}`}>
          {item.thumbnailUrl ? <img src={item.thumbnailUrl} alt=""/> : <span className="thumbnail-placeholder" aria-hidden="true">{index + 1}</span>}
          <span><strong>{item.file.name}</strong><small>{item.status.replace('_', ' ')}</small></span>
          {item.localId === batch.selectedLocalId && <span className="active-marker">Selected</span>}
        </button>
        <div className="batch-actions">
          {item.status === BATCH_STATUS.FAILED && <button className="secondary" disabled={editorBusy} onClick={() => retryBatchItem(item)} aria-label={`Retry ${item.file.name}`}>Retry</button>}
          {item.status !== BATCH_STATUS.PROCESSING && <button className="secondary" disabled={editorBusy} onClick={() => removeBatchItem(item)} aria-label={`Remove ${item.file.name}`}>Remove</button>}
        </div>
      </li>)}</ul>
    </section>}
    {!job ? <section className={`dropzone ${dragging ? 'dragging' : ''}`} onDragEnter={(e) => { e.preventDefault(); setDragging(true) }} onDragOver={(e) => e.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); ingest(e.dataTransfer.files) }}>
      <input ref={inputRef} id="image-input" type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={mutating || batch.items.length >= 10} onChange={(e) => ingest(e.target.files)}/>
      <h2>{queueProcessing ? 'Processing photos…' : 'Drop up to 10 images here'}</h2><p>JPEG, PNG, or WebP. Photos process one at a time.</p>
      <label className={`primary ${batch.items.length >= 10 ? 'disabled' : ''}`} htmlFor="image-input">Choose photos</label>
    </section> : <section className="workspace">
      <div className="preview-panel">
        {readyItems.length > 1 && <nav className="ready-navigation" aria-label="Ready photos"><button className="secondary" disabled={readyIndex <= 0 || globallyBusy} onClick={() => batchDispatch(batchActions.select(readyItems[readyIndex - 1].localId))}>Previous</button><span>{readyIndex + 1} of {readyItems.length}</span><button className="secondary" disabled={readyIndex < 0 || readyIndex >= readyItems.length - 1 || globallyBusy} onClick={() => batchDispatch(batchActions.select(readyItems[readyIndex + 1].localId))}>Next</button></nav>}
        <div ref={stageRef} className={`checker stage ${cursor ? 'over-image' : ''}`} aria-label="Mask brush canvas" aria-description="Use arrow keys to move the brush. Press Space or Enter to apply a dab." role="application" tabIndex={0} onKeyDown={onStageKeyDown} onContextMenu={(event) => event.preventDefault()} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={finishStroke} onPointerCancel={discardStroke} onLostPointerCapture={(event) => finishStroke(event, false)} onPointerLeave={() => { if (activePointerRef.current === null) setCursor(null) }}>
          {previewUrl && previewIdentity && <img key={`${previewIdentity.jobId}:${previewIdentity.requestId}:${previewIdentity.url}`} className="result" src={previewUrl} alt="Background removal result" onLoad={() => { if (previewIdentityRef.current === previewIdentity && previewIdentity.jobId === jobRef.current?.id && previewIdentity.requestId === previewRequestRef.current) { previewReadyRef.current = true; setPreviewReady(true); clearOwnedError('preview') } }} onError={() => { if (previewIdentityRef.current === previewIdentity && previewIdentity.jobId === jobRef.current?.id && previewIdentity.requestId === previewRequestRef.current) { previewReadyRef.current = false; setPreviewReady(false); setOwnedError('The current preview image could not be decoded.', 'preview') } }}/>}
          <img className={`original ${painting ? 'brush-reference' : ''}`} src={`/api/jobs/${job.id}/original`} alt="Original" style={{ clipPath: painting ? 'none' : `inset(0 ${100 - compare}% 0 0)` }}/>
          {imageRect && <svg className="brush-overlay" aria-hidden="true" width="100%" height="100%">
            {livePoints.length > 0 && <polyline points={livePoints.map((p) => p.join(',')).join(' ')} fill="none" stroke={paintColor} strokeOpacity={0.3 + (1 - softness) * 0.45} strokeWidth={brushSize * 2} strokeLinecap="round" strokeLinejoin="round"/>}
            {cursor && <circle cx={cursor[0]} cy={cursor[1]} r={brushSize} fill={paintColor} fillOpacity="0.12" stroke={paintColor} strokeWidth="2"/>}
          </svg>}
          {(previewing || mutating) && <span className="working">{mutating ? 'Applying brush…' : 'Updating preview…'}</span>}
        </div>
        <label className="range-row"><span>Original / result</span><input aria-label="Comparison" type="range" min="0" max="100" value={painting ? 0 : compare} disabled={globallyBusy || activePointerRef.current !== null} onChange={(e) => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) setCompare(Number(e.target.value)) }}/></label>
        <p className="dimensions">{job.width} × {job.height} pixels</p>
      </div>
      <aside className="controls">
        <fieldset disabled={controlsBlocked}><legend>Manual mask brush</legend>
          <div className="mode-choices" role="radiogroup" aria-label="Brush mode">
            <label className="choice"><input type="radio" name="brush-mode" value="remove" checked={mode === 'remove'} disabled={!brushEnabled || drawing} onChange={() => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) setMode('remove') }}/>Remove</label>
            <label className="choice"><input type="radio" name="brush-mode" value="restore" checked={mode === 'restore'} disabled={!brushEnabled || drawing} onChange={() => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) setMode('restore') }}/>Restore</label>
          </div>
          <label className="control-row"><span>Brush size <output>{brushSize}px</output></span><input aria-label="Brush size" type="range" min="2" max="160" value={brushSize} disabled={!brushEnabled || drawing} onChange={(e) => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) setBrushSize(Number(e.target.value)) }}/></label>
          <label className="control-row"><span>Softness <output>{Math.round(softness * 100)}%</output></span><input aria-label="Brush softness" type="range" min="0" max="1" step="0.05" value={softness} disabled={!brushEnabled || drawing} onChange={(e) => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) setSoftness(Number(e.target.value)) }}/></label>
          <p className="stroke-count" aria-live="polite">{strokeCount} {strokeCount === 1 ? 'stroke' : 'strokes'}</p>
          <div className="brush-actions"><button className="secondary" disabled={!strokeCount || globallyBusy} onClick={undoStroke}>Undo stroke</button><button className="secondary" disabled={!strokeCount || globallyBusy} onClick={resetStrokes}>Reset strokes</button></div>
        </fieldset>
        <fieldset disabled={controlsBlocked || activePointerRef.current !== null}><legend>Mask</legend>
          <label className="control-row"><span>Threshold <output>{threshold}</output></span><input aria-label="Threshold" type="range" min="0" max="100" value={threshold} onChange={(e) => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) changePreviewSetting(setThreshold, Number(e.target.value)) }}/></label>
          <label className="control-row"><span>Feather <output>{feather}px</output></span><input aria-label="Feather" type="range" min="0" max="32" step="0.5" value={feather} onChange={(e) => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) changePreviewSetting(setFeather, Number(e.target.value)) }}/></label>
        </fieldset>
        <fieldset disabled={controlsBlocked || activePointerRef.current !== null}><legend>Background</legend>
          <label className="choice"><input type="radio" name="background-mode" checked={background === 'transparent'} onChange={() => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) changePreviewSetting(setBackground, 'transparent') }}/>Transparent</label>
          <label className="choice"><input type="radio" name="background-mode" checked={background === 'solid'} onChange={() => { if (!ingestionRef.current && !mutationRef.current && !exportRef.current && activePointerRef.current === null) changePreviewSetting(setBackground, 'solid') }}/>Solid color</label>
          <div className="color-row"><input aria-label="Color picker" type="color" value={color} onChange={(e) => { invalidatePreview(); setColor(e.target.value); setBackground('solid') }}/><input aria-label="Hex color" value={color} maxLength="7" onChange={(e) => changePreviewSetting(setColor, e.target.value)} onBlur={() => { if (!validColor) changePreviewSetting(setColor, '#ffffff') }}/></div>
          <div className="presets">{presets.map(([label, value]) => <button key={label} className="secondary" onClick={() => { invalidatePreview(); setColor(value); setBackground('solid') }}>{label}</button>)}</div>
        </fieldset>
        <fieldset className="export-actions" disabled={controlsBlocked || activePointerRef.current !== null}><legend>Export full resolution</legend>
          <button className="primary wide" disabled={globallyBusy} onClick={() => exportImage('png', 'transparent')}>Transparent PNG</button>
          <button className="secondary wide" disabled={!validColor || globallyBusy} onClick={() => exportImage('png', color)}>Solid PNG</button>
          <button className="secondary wide" disabled={!validColor || globallyBusy} onClick={() => exportImage('jpeg', color)}>Solid JPEG</button>
        </fieldset>
      </aside>
    </section>}
  </main>
}
