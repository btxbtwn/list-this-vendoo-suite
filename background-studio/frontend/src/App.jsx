import { useCallback, useEffect, useRef, useState } from 'react'

const presets = [['White', '#ffffff'], ['Black', '#000000'], ['Marketplace', '#f5f5f5']]
const MAX_POINTS = 2048
const REBALANCE_POINTS = 1024

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

  useEffect(() => { jobRef.current = job }, [job])
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

  const ingest = useCallback(async (file) => {
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

  const finishStroke = async (event) => {
    if (activePointerRef.current !== event.pointerId) return
    const activeBrush = activeBrushRef.current
    const terminal = pointerPosition(event, activeBrush.viewport, true)
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

  useEffect(() => {
    if (!brushEnabled && activePointerRef.current === null) setCursor(null)
  }, [brushEnabled])

  return <main className="shell">
    <header className="app-header"><div><p className="eyebrow">Image editing workspace</p><h1>Background Studio</h1></div>
      {(job || stateUncertain) && <button className="secondary" disabled={globallyBusy || activePointerRef.current !== null} onClick={reset}>New image</button>}
    </header>
    {error && <div className="error" role="alert">{error}</div>}
    {!job ? <section className={`dropzone ${dragging ? 'dragging' : ''}`} onDragEnter={(e) => { e.preventDefault(); setDragging(true) }} onDragOver={(e) => e.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); ingest(e.dataTransfer.files[0]) }}>
      <input ref={inputRef} id="image-input" type="file" accept="image/jpeg,image/png,image/webp" disabled={processing || mutating} onChange={(e) => ingest(e.target.files[0])}/>
      <h2>{processing ? 'Removing background…' : 'Drop an image here'}</h2><p>JPEG, PNG, or WebP. You can also paste an image.</p>
      <label className={`primary ${processing ? 'disabled' : ''}`} htmlFor="image-input">{processing ? 'Processing' : 'Choose image'}</label>
    </section> : <section className="workspace">
      <div className="preview-panel">
        <div ref={stageRef} className={`checker stage ${cursor ? 'over-image' : ''}`} aria-label="Mask brush canvas" aria-description="Use arrow keys to move the brush. Press Space or Enter to apply a dab." role="application" tabIndex={0} onKeyDown={onStageKeyDown} onContextMenu={(event) => event.preventDefault()} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={finishStroke} onPointerCancel={discardStroke} onLostPointerCapture={discardStroke} onPointerLeave={() => { if (activePointerRef.current === null) setCursor(null) }}>
          {previewUrl && previewIdentity && <img key={`${previewIdentity.jobId}:${previewIdentity.requestId}:${previewIdentity.url}`} className="result" src={previewUrl} alt="Background removal result" onLoad={() => { if (previewIdentityRef.current === previewIdentity && previewIdentity.jobId === jobRef.current?.id && previewIdentity.requestId === previewRequestRef.current) { previewReadyRef.current = true; setPreviewReady(true); clearOwnedError('preview') } }} onError={() => { if (previewIdentityRef.current === previewIdentity && previewIdentity.jobId === jobRef.current?.id && previewIdentity.requestId === previewRequestRef.current) { previewReadyRef.current = false; setPreviewReady(false); setOwnedError('The current preview image could not be decoded.', 'preview') } }}/>}
          {!painting && <img className="original" src={`/api/jobs/${job.id}/original`} alt="Original" style={{ clipPath: `inset(0 ${100 - compare}% 0 0)` }}/>}
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
