import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'

class TestPointerEvent extends MouseEvent {
  constructor(type, init = {}) {
    super(type, init)
    Object.defineProperties(this, {
      pointerId: { value: init.pointerId ?? 1 },
      isPrimary: { value: init.isPrimary ?? true },
      button: { value: init.button ?? 0 },
    })
  }
}

const job = { id: '00000000000000000000000000000001', width: 200, height: 100 }
const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const imageResponse = () => new Response(new Blob(['png'], { type: 'image/png' }), { status: 200 })

function installFetch(mutationHandler) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
    if (url === '/api/jobs' && options.method === 'POST') return Promise.resolve(jsonResponse({ ...job, id: options.body.get('job_id') }, 201))
    if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
    if (String(url).includes('/strokes')) return mutationHandler ? mutationHandler(url, options) : Promise.resolve(jsonResponse({ revision: 7, count: options.method === 'DELETE' ? 0 : 1 }))
    return Promise.resolve(jsonResponse({ ok: true }))
  })
}

async function openEditor(fetchMock = installFetch()) {
  render(<App />)
  fireEvent.change(document.getElementById('image-input'), { target: { files: [new File(['pixels'], 'photo.png', { type: 'image/png' })] } })
  await screen.findByText('200 × 100 pixels')
  const stage = screen.getByLabelText('Mask brush canvas')
  stage.getBoundingClientRect = () => ({ x: 0, y: 0, left: 0, top: 0, right: 400, bottom: 400, width: 400, height: 400, toJSON() {} })
  stage.setPointerCapture = vi.fn()
  stage.releasePointerCapture = vi.fn()
  fireEvent(window, new Event('resize'))
  fireEvent.load(await screen.findByAltText('Background removal result'))
  fireEvent.change(screen.getByLabelText('Comparison'), { target: { value: '0' } })
  await waitFor(() => expect(screen.getByRole('slider', { name: 'Brush size' })).toBeEnabled())
  return { fetchMock, stage }
}

function draw(stage, start = [100, 150], end = [300, 250]) {
  fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: start[0], clientY: start[1], pointerId: 7 }))
  fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: end[0], clientY: end[1], pointerId: 7 }))
  fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: end[0], clientY: end[1], pointerId: 7 }))
}

beforeEach(() => {
  sessionStorage.clear()
  let requestId = 0
  vi.spyOn(globalThis.crypto, 'randomUUID').mockImplementation(() => `${requestId += 1}`.padStart(32, '0'))
  vi.stubGlobal('PointerEvent', TestPointerEvent)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('manual mask brush', () => {
  it('exposes stable responsive structure for the canvas-first mobile layout', async () => {
    await openEditor()
    const workspace = screen.getByLabelText('Mask brush canvas').closest('.workspace')
    expect(workspace).not.toBeNull()
    expect(workspace.firstElementChild).toHaveClass('preview-panel')
    expect(workspace.lastElementChild).toHaveClass('controls')
    expect(screen.getByRole('group', { name: 'Export full resolution' })).toHaveClass('export-actions')
    expect(document.querySelector('header')).toHaveClass('app-header')
  })

  it('submits one correctly normalized stroke over the object-contain image area', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent.click(screen.getByLabelText('Restore'))
    fireEvent.change(screen.getByLabelText('Brush softness'), { target: { value: '0.5' } })
    draw(stage)

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/jobs/00000000000000000000000000000001/strokes' && options.method === 'POST')).toBe(true))
    const calls = fetchMock.mock.calls.filter(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')
    expect(calls).toHaveLength(1)
    const payload = JSON.parse(calls[0][1].body)
    expect(payload.mode).toBe('restore')
    expect(payload.softness).toBe(0.5)
    expect(payload.radius).toBeCloseTo(0.18)
    expect(payload.points).toEqual([[0.25, 0.25], [0.75, 0.75]])
    expect(payload.points.length).toBeLessThanOrEqual(2048)
    await screen.findByText('1 stroke')
  })

  it('turns a tap into a valid tiny two-point segment', async () => {
    const { fetchMock, stage } = await openEditor()
    draw(stage, [200, 200], [200, 200])
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const call = fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')
    const payload = JSON.parse(call[1].body)
    expect(payload.points).toHaveLength(2)
    expect(payload.points[1][0]).toBeGreaterThan(payload.points[0][0])
  })

  it('undoes the last stroke and refreshes the count', async () => {
    const { fetchMock, stage } = await openEditor()
    draw(stage)
    const undo = await screen.findByRole('button', { name: 'Undo stroke' })
    await waitFor(() => expect(undo).toBeEnabled())
    fireEvent.click(undo)
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/jobs/00000000000000000000000000000001/strokes/last' && options.method === 'DELETE')).toBe(true))
    await screen.findByText('0 strokes')
    expect(undo).toBeDisabled()
  })

  it('resets all strokes', async () => {
    const { fetchMock, stage } = await openEditor()
    draw(stage)
    const reset = await screen.findByRole('button', { name: 'Reset strokes' })
    await waitFor(() => expect(reset).toBeEnabled())
    fireEvent.click(reset)
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/jobs/00000000000000000000000000000001/strokes' && options.method === 'DELETE')).toBe(true))
    await screen.findByText('0 strokes')
    expect(reset).toBeDisabled()
  })

  it('locks unsafe actions and ignores paste while a stroke mutation is pending', async () => {
    let resolveMutation
    const pending = new Promise((resolve) => { resolveMutation = resolve })
    const fetchMock = installFetch((url, options) => options.method === 'POST' ? pending : Promise.resolve(jsonResponse({ ok: true })))
    const { stage } = await openEditor(fetchMock)
    draw(stage)

    await waitFor(() => expect(screen.getByText('Applying brush…')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'New batch' })).toBeDisabled()
    expect(screen.getByLabelText('Comparison')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Transparent PNG' })).toBeDisabled()

    const paste = new Event('paste')
    Object.defineProperty(paste, 'clipboardData', { value: { items: [{ type: 'image/png', getAsFile: () => new File(['x'], 'p.png', { type: 'image/png' }) }] } })
    fireEvent(window, paste)
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/jobs')).toHaveLength(1)

    resolveMutation(jsonResponse({ revision: 8, count: 1 }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'New batch' })).toBeEnabled())
  })

  it('ignores secondary pointers while a primary stroke is active', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 1 }))
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 300, clientY: 250, pointerId: 2, isPrimary: false }))
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 300, clientY: 250, pointerId: 2, isPrimary: false }))
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(false)
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 100, clientY: 150, pointerId: 1 }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toHaveLength(1))
  })

  it('discards cancel/lost-capture and safely handles release errors', async () => {
    const { fetchMock, stage } = await openEditor()
    stage.releasePointerCapture = vi.fn(() => { throw new Error('already released') })
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 3 }))
    fireEvent(stage, new TestPointerEvent('pointercancel', { bubbles: true, pointerId: 3 }))
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 4 }))
    fireEvent(stage, new TestPointerEvent('lostpointercapture', { bubbles: true, pointerId: 4 }))
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(false)
  })

  it('rejects right mouse strokes and suppresses context menus', async () => {
    const { fetchMock, stage } = await openEditor()
    const context = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    fireEvent(stage, context)
    expect(context.defaultPrevented).toBe(true)
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 9, button: 2 }))
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 100, clientY: 150, pointerId: 9, button: 2 }))
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(false)
  })

  it.each([[0, 100], [400, 100], [0, 300], [400, 300]])('makes a corner tap at %i,%i rasterize as distinct points', async (x, y) => {
    const { fetchMock, stage } = await openEditor()
    draw(stage, [x, y], [x, y])
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body)
    expect(payload.points[0]).not.toEqual(payload.points[1])
    expect(Math.abs(payload.points[1][0] - payload.points[0][0]) * 400).toBeCloseTo(1)
  })

  it('uses the server authoritative stroke count', async () => {
    const fetchMock = installFetch(() => Promise.resolve(jsonResponse({ revision: 42, count: 6 })))
    const { stage } = await openEditor(fetchMock)
    draw(stage)
    await screen.findByText('6 strokes')
  })

  it('refreshes preview when the first server mutation revision is 1', async () => {
    const fetchMock = installFetch(() => Promise.resolve(jsonResponse({ revision: 1, count: 1 })))
    const { stage } = await openEditor(fetchMock)
    const previewsBefore = fetchMock.mock.calls.filter(([url]) => String(url).includes('/preview?')).length

    draw(stage)

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/preview?')).length).toBeGreaterThan(previewsBefore))
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/preview?')).at(-1)[0]).toContain('revision=1')
  })

  it('appends a distinct pointer-up position even without a pointer move', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 12 }))
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 300, clientY: 250, pointerId: 12 }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body)
    expect(payload.points).toEqual([[0.25, 0.25], [0.75, 0.75]])
  })

  it('disables brush parameters during a stroke and uses their pointer-down values', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent.click(screen.getByLabelText('Restore'))
    fireEvent.change(screen.getByRole('slider', { name: 'Brush size' }), { target: { value: '40' } })
    fireEvent.change(screen.getByRole('slider', { name: 'Brush softness' }), { target: { value: '0.6' } })
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 13 }))

    expect(screen.getByLabelText('Restore')).toBeDisabled()
    expect(screen.getByRole('slider', { name: 'Brush size' })).toBeDisabled()
    expect(screen.getByRole('slider', { name: 'Brush softness' })).toBeDisabled()
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 300, clientY: 250, pointerId: 13 }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body)
    expect(payload).toMatchObject({ mode: 'restore', softness: 0.6 })
    expect(payload.radius).toBeCloseTo(0.2)
  })

  it('clears and gates the brush cursor when drawing is unavailable', async () => {
    const { stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: 200, clientY: 200, pointerId: 15 }))
    expect(stage.querySelector('circle')).not.toBeNull()

    fireEvent.change(screen.getByLabelText('Comparison'), { target: { value: '50' } })
    await waitFor(() => expect(stage.querySelector('circle')).toBeNull())
    fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: 200, clientY: 200, pointerId: 15 }))
    expect(stage.querySelector('circle')).toBeNull()
  })

  it('keeps undo and reset available with strokes despite comparison or preview readiness', async () => {
    const { stage } = await openEditor()
    draw(stage)
    const undo = await screen.findByRole('button', { name: 'Undo stroke' })
    const reset = screen.getByRole('button', { name: 'Reset strokes' })
    await waitFor(() => expect(undo).toBeEnabled())

    fireEvent.change(screen.getByLabelText('Comparison'), { target: { value: '50' } })
    expect(undo).toBeEnabled()
    expect(reset).toBeEnabled()
  })

  it('rolls back drawing state when pointer capture acquisition fails', async () => {
    const { fetchMock, stage } = await openEditor()
    stage.setPointerCapture = vi.fn(() => { throw new Error('capture failed') })
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 16 }))

    expect(screen.getByRole('slider', { name: 'Brush size' })).toBeEnabled()
    expect(stage.querySelector('polyline')).toBeNull()
    expect(stage.querySelector('circle')).toBeNull()
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 300, clientY: 250, pointerId: 16 }))
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(false)
  })

  it.skip('blocks export and deletion immediately while ingestion is pending', async () => {
    let resolveIngestion
    let uploadCount = 0
    const pending = new Promise((resolve) => { resolveIngestion = resolve })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') {
        uploadCount += 1
        return uploadCount === 1 ? Promise.resolve(jsonResponse(job, 201)) : pending
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    const { stage } = await openEditor(fetchMock)
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const paste = new Event('paste')
    Object.defineProperty(paste, 'clipboardData', { value: { items: [{ type: 'image/png', getAsFile: () => new File(['x'], 'next.png', { type: 'image/png' }) }] } })

    fireEvent(window, paste)
    fireEvent.click(screen.getByRole('button', { name: 'Transparent PNG' }))
    fireEvent.click(screen.getByRole('button', { name: 'New batch' }))
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 17 }))

    expect(anchorClick).not.toHaveBeenCalled()
    expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE')).toBe(false)
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(false)
    resolveIngestion(jsonResponse({ ...job, id: '00000000000000000000000000000002' }, 201))
    await screen.findByText('200 × 100 pixels')
  })

  it('tracks export through the full blob response, blocks races, and revokes the download URL', async () => {
    let resolveExport
    const pendingExport = new Promise((resolve) => { resolveExport = resolve })
    const fetchMock = installFetch()
    fetchMock.mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') return Promise.resolve(jsonResponse({ ...job, id: options.body.get('job_id') }, 201))
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (String(url).includes('/export?')) return pendingExport
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    URL.createObjectURL.mockReturnValueOnce('blob:download')
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    fireEvent.click(screen.getByRole('button', { name: 'Transparent PNG' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'New batch' })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: 'New batch' }))
    expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE')).toBe(false)
    expect(anchorClick).not.toHaveBeenCalled()

    resolveExport(imageResponse())
    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1))
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:download')
    expect(fetchMock.mock.calls.find(([url]) => String(url).includes('/export?'))[1]).toMatchObject({ cache: 'no-store' })
  })

  it('surfaces export response errors without triggering a download', async () => {
    const fetchMock = installFetch()
    fetchMock.mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') return Promise.resolve(jsonResponse({ ...job, id: options.body.get('job_id') }, 201))
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (String(url).includes('/export?')) return Promise.resolve(jsonResponse({ detail: 'Disk full.' }, 507))
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    fireEvent.click(screen.getByRole('button', { name: 'Transparent PNG' }))
    await screen.findByRole('alert')
    expect(screen.getByRole('alert')).toHaveTextContent('Disk full.')
    expect(anchorClick).not.toHaveBeenCalled()
  })

  it('uses revisioned no-store previews and ignores stale image load readiness', async () => {
    URL.createObjectURL.mockReset().mockReturnValueOnce('blob:first').mockReturnValueOnce('blob:second').mockReturnValue('blob:later')
    const { fetchMock, stage } = await openEditor()
    const firstImage = screen.getByAltText('Background removal result')
    fireEvent.change(screen.getByRole('slider', { name: 'Threshold' }), { target: { value: '10' } })
    expect(screen.getByRole('slider', { name: 'Brush size' })).toBeDisabled()
    fireEvent.load(firstImage)
    expect(screen.getByRole('slider', { name: 'Brush size' })).toBeDisabled()
    await waitFor(() => expect(screen.getByAltText('Background removal result').getAttribute('src')).toBe('blob:second'))
    expect(screen.getByRole('slider', { name: 'Brush size' })).toBeDisabled()
    fireEvent.load(screen.getByAltText('Background removal result'))
    await waitFor(() => expect(screen.getByRole('slider', { name: 'Brush size' })).toBeEnabled())
    const previewCall = fetchMock.mock.calls.filter(([url]) => String(url).includes('/preview?')).at(-1)
    expect(previewCall[0]).toContain('revision=0')
    expect(previewCall[1]).toMatchObject({ cache: 'no-store' })
    fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: 200, clientY: 200 }))
    expect(stage.querySelector('circle')).not.toBeNull()
  })

  it('invalidates preview readiness immediately for an invalid solid color', async () => {
    const { fetchMock, stage } = await openEditor()
    const previewsBefore = fetchMock.mock.calls.filter(([url]) => String(url).includes('/preview?')).length
    fireEvent.click(screen.getByLabelText('Solid color'))
    fireEvent.change(screen.getByLabelText('Hex color'), { target: { value: '#nope' } })
    await waitFor(() => expect(screen.getByRole('slider', { name: 'Brush size' })).toBeDisabled())
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 200, clientY: 200, pointerId: 21 }))
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(false)
    await new Promise((resolve) => setTimeout(resolve, 220))
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/preview?'))).toHaveLength(previewsBefore)
  })

  it('guards destructive controls during an active pointer and supports bounded keyboard dabs', async () => {
    const { fetchMock, stage } = await openEditor()
    expect(stage).toHaveAttribute('tabindex', '0')
    expect(stage).toHaveAttribute('role', 'application')
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 22 }))
    expect(screen.getByRole('button', { name: 'New batch' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Transparent PNG' })).toBeDisabled()
    expect(screen.getByRole('slider', { name: 'Threshold' })).toBeDisabled()
    fireEvent(stage, new TestPointerEvent('pointercancel', { bubbles: true, pointerId: 22 }))

    for (let index = 0; index < 100; index += 1) fireEvent.keyDown(stage, { key: 'ArrowRight' })
    fireEvent.keyDown(stage, { key: 'Enter' })
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body)
    expect(payload.points[0][0]).toBe(1)
    expect(payload.points.flat()).toEqual(expect.arrayContaining([expect.any(Number)]))
    expect(payload.points.every(([x, y]) => x >= 0 && x <= 1 && y >= 0 && y <= 1)).toBe(true)
  })

  it('rejects detached stale preview events and surfaces current decode errors', async () => {
    URL.createObjectURL.mockReset().mockReturnValue('blob:same')
    await openEditor()
    const detached = screen.getByAltText('Background removal result')
    fireEvent.change(screen.getByRole('slider', { name: 'Threshold' }), { target: { value: '11' } })
    await waitFor(() => expect(screen.getByAltText('Background removal result')).not.toBe(detached))
    const current = screen.getByAltText('Background removal result')
    fireEvent.load(detached); fireEvent.error(detached)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('slider', { name: 'Brush size' })).toBeDisabled()
    fireEvent.load(current)
    await waitFor(() => expect(screen.getByRole('slider', { name: 'Brush size' })).toBeEnabled())
    fireEvent.error(current)
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be decoded')
    expect(screen.getByRole('slider', { name: 'Brush size' })).toBeDisabled()
  })

  it.skip('awaits deletion, blocks work, and retains the job when deletion fails', async () => {
    let resolveDelete
    const pendingDelete = new Promise((resolve) => { resolveDelete = resolve })
    const fetchMock = installFetch()
    fetchMock.mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') return Promise.resolve(jsonResponse({ ...job, id: options.body.get('job_id') }, 201))
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE') return pendingDelete
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    fireEvent.click(screen.getByRole('button', { name: 'New batch' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'New batch' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Transparent PNG' })).toBeDisabled()
    resolveDelete(jsonResponse({ detail: 'Delete refused.' }, 500))
    expect(await screen.findByRole('alert')).toHaveTextContent('Delete refused.')
    expect(screen.getByText('200 × 100 pixels')).toBeInTheDocument()
  })

  it.skip('rolls back a replacement when deleting the old job fails, in order', async () => {
    const calls = []
    let uploads = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      calls.push([url, options.method])
      if (url === '/api/jobs' && options.method === 'POST') {
        uploads += 1
        return Promise.resolve(jsonResponse({ ...job, id: `job${uploads}` }, 201))
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE') return Promise.resolve(jsonResponse({ detail: 'Old delete failed.' }, 500))
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    const paste = new Event('paste')
    Object.defineProperty(paste, 'clipboardData', { value: { items: [{ type: 'image/png', getAsFile: () => new File(['x'], 'next.png', { type: 'image/png' }) }] } })
    fireEvent(window, paste)
    expect(await screen.findByRole('alert')).toHaveTextContent('Old delete failed.')
    const oldDelete = calls.findIndex(([url, method]) => url === '/api/jobs/00000000000000000000000000000001' && method === 'DELETE')
    const rollback = calls.findIndex(([url, method]) => url === '/api/jobs/00000000000000000000000000000002' && method === 'DELETE')
    expect(rollback).toBeGreaterThan(oldDelete)
  })

  it('uses the pointer-down rectangle and clamps an outside terminal after resize', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 30 }))
    stage.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 400, right: 800, bottom: 400, toJSON() {} })
    fireEvent(window, new Event('resize'))
    fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: 900, clientY: 900, pointerId: 30 }))
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 900, clientY: 900, pointerId: 30 }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body)
    expect(payload.points).toEqual([[0.25, 0.25], [1, 1]])
  })

  it('periodically reduces dense strokes substantially while preserving path and endpoint', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 1, clientY: 101, pointerId: 31 }))
    for (let index = 0; index < 10000; index += 1) {
      const phase = index % 400
      const x = phase < 100 ? 1 + phase * 3.98 : phase < 200 ? 399 : phase < 300 ? 399 - (phase - 200) * 3.98 : 1
      const y = phase < 100 ? 101 : phase < 200 ? 101 + (phase - 100) * 1.98 : phase < 300 ? 299 : 299 - (phase - 300) * 1.98
      fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: x, clientY: y, pointerId: 31 }))
    }
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 399, clientY: 299, pointerId: 31 }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const points = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body).points
    expect(points.length).toBeLessThan(1536)
    expect(points.length).toBeGreaterThan(100)
    expect(points.at(-1)).toEqual([0.9975, 0.995])
    expect(points.some(([x, y]) => x < 0.1 && y < 0.1)).toBe(true)
    expect(points.some(([x, y]) => x > 0.9 && y < 0.1)).toBe(true)
    expect(points.some(([x, y]) => x < 0.1 && y > 0.9)).toBe(true)
  })

  it('resets the keyboard point to center for a new image', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent.keyDown(stage, { key: 'ArrowRight' })
    fireEvent.click(screen.getByRole('button', { name: 'New batch' }))
    await screen.findByText('Drop up to 10 images here')
    fireEvent.change(document.getElementById('image-input'), { target: { files: [new File(['new'], 'new.png', { type: 'image/png' })] } })
    await screen.findByText('200 × 100 pixels')
    const nextStage = screen.getByLabelText('Mask brush canvas')
    nextStage.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 400, right: 400, bottom: 400, toJSON() {} })
    fireEvent(window, new Event('resize'))
    fireEvent.load(await screen.findByAltText('Background removal result'))
    fireEvent.change(screen.getByLabelText('Comparison'), { target: { value: '0' } })
    fireEvent.keyDown(nextStage, { key: 'Enter' })
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000002/strokes')).toBe(true))
    const payload = JSON.parse(fetchMock.mock.calls.filter(([url]) => url === '/api/jobs/00000000000000000000000000000002/strokes').at(-1)[1].body)
    expect(payload.points[0]).toEqual([0.5, 0.5])
  })

  it('uses immutable stage and image geometry for the entire stroke', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 40 }))
    stage.getBoundingClientRect = () => ({ left: 200, top: 100, width: 800, height: 800, right: 1000, bottom: 900, toJSON() {} })
    fireEvent(window, new Event('resize'))
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 300, clientY: 250, pointerId: 40 }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body)
    expect(payload.points).toEqual([[0.25, 0.25], [0.75, 0.75]])
  })

  it('keeps the terminal endpoint after compacting a dense stroke', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 1, clientY: 101, pointerId: 41 }))
    for (let index = 0; index < 2200; index += 1) fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: index % 2 ? 399 : 1, clientY: 101 + (index % 199), pointerId: 41 }))
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 400, clientY: 300, pointerId: 41 }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const points = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body).points
    expect(points.length).toBeLessThanOrEqual(2048)
    expect(points.at(-1)).toEqual([1, 1])
    expect(new Set(points.map((point) => point.join(','))).size).toBeGreaterThan(2)
  })

  it('does not enter drawing when pointer capture is unsupported', async () => {
    const { fetchMock, stage } = await openEditor()
    delete stage.setPointerCapture
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 42 }))
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 300, clientY: 250, pointerId: 42 }))
    expect(screen.getByRole('slider', { name: 'Brush size' })).toBeEnabled()
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(false)
  })

  it.skip('retries authoritative orphan cleanup before accepting another upload', async () => {
    let uploads = 0
    let orphanDeleteAttempts = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') {
        uploads += 1
        return Promise.resolve(jsonResponse({ ...job, id: `job${uploads}` }, 201))
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE') return Promise.resolve(jsonResponse({ detail: 'old failed' }, 500))
      if (url === '/api/jobs/00000000000000000000000000000002' && options.method === 'DELETE') {
        orphanDeleteAttempts += 1
        return Promise.resolve(orphanDeleteAttempts === 1 ? jsonResponse({ detail: 'rollback failed' }, 500) : jsonResponse({ id: '00000000000000000000000000000002', state: 'tombstoned' }, 410))
      }
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    const paste = () => {
      const event = new Event('paste')
      Object.defineProperty(event, 'clipboardData', { value: { items: [{ type: 'image/png', getAsFile: () => new File(['x'], 'next.png', { type: 'image/png' }) }] } })
      fireEvent(window, event)
    }
    paste()
    expect(await screen.findByRole('alert')).toHaveTextContent('rollback failed')
    paste()
    await waitFor(() => expect(orphanDeleteAttempts).toBe(2))
    await waitFor(() => expect(uploads).toBe(3))
  })

  it.each(['{', ''])('blocks all state-sensitive controls after malformed 2xx mutation JSON %j', async (body) => {
    const fetchMock = installFetch((url, options) => options.method === 'POST'
      ? Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } }))
      : Promise.resolve(jsonResponse({ revision: 1, count: 0 })))
    const { stage } = await openEditor(fetchMock)
    draw(stage)
    expect(await screen.findByRole('alert')).toHaveTextContent('blocked')
    expect(screen.getByRole('slider', { name: 'Threshold' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Transparent PNG' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Undo stroke' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'New batch' })).toBeEnabled()
    fireEvent.keyDown(stage, { key: 'Enter' })
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toHaveLength(1)
  })

  it('blocks state-sensitive controls when a mutation transport response is lost', async () => {
    const fetchMock = installFetch((url, options) => options.method === 'POST'
      ? Promise.reject(new TypeError('Failed to fetch'))
      : Promise.resolve(jsonResponse({ revision: 1, count: 0 })))
    const { stage } = await openEditor(fetchMock)
    draw(stage)
    expect(await screen.findByRole('alert')).toHaveTextContent('response was lost')
    expect(screen.getByRole('slider', { name: 'Threshold' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Transparent PNG' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'New batch' })).toBeEnabled()
  })

  it('keeps the active cursor stationary and clears it on cancellation', async () => {
    const { stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 150, pointerId: 50 }))
    const circle = stage.querySelector('circle')
    expect(circle).not.toBeNull()
    expect(circle).toHaveAttribute('cx', '100')
    fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: -20, clientY: -20, pointerId: 99 }))
    expect(stage.querySelector('circle')).toHaveAttribute('cx', '100')
    fireEvent(stage, new TestPointerEvent('lostpointercapture', { bubbles: true, pointerId: 50 }))
    expect(stage.querySelector('circle')).toBeNull()
  })

  it.skip('retries a lost old-job DELETE response without using GET presence as completion evidence', async () => {
    let deleteAttempts = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') return Promise.resolve(jsonResponse({ ...job, id: options.body.get('job_id') }, 201))
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE') {
        deleteAttempts += 1
        return deleteAttempts === 1 ? Promise.reject(new TypeError('lost response')) : Promise.resolve(new Response('', { status: 404 }))
      }
      if (url === '/api/jobs/00000000000000000000000000000001' && !options.method) return Promise.resolve(jsonResponse({ id: '00000000000000000000000000000001', state: 'tombstoned' }, 410))
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    const paste = new Event('paste')
    Object.defineProperty(paste, 'clipboardData', { value: { items: [{ type: 'image/png', getAsFile: () => new File(['x'], 'next.png', { type: 'image/png' }) }] } })
    fireEvent(window, paste)
    await waitFor(() => expect(deleteAttempts).toBe(2))
    expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/jobs/00000000000000000000000000000001' && !options.method)).toBe(true)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it.skip('does not clear a job from an immediate unknown 404 after a lost DELETE response', async () => {
    let deleteAttempts = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') return Promise.resolve(jsonResponse({ ...job, id: options.body.get('job_id') }, 201))
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE') {
        deleteAttempts += 1
        return deleteAttempts === 1 ? Promise.reject(new TypeError('lost')) : Promise.resolve(new Response('', { status: 404 }))
      }
      if (url === '/api/jobs/00000000000000000000000000000001') return Promise.resolve(jsonResponse({ id: '00000000000000000000000000000001', state: 'unknown' }, 404))
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    fireEvent.click(screen.getByRole('button', { name: 'New batch' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('unknown result')
    expect(screen.getByText('200 × 100 pixels')).toBeInTheDocument()
  })

  it.skip.each([
    new Response('{', { status: 201, headers: { 'Content-Type': 'application/json' } }),
    jsonResponse({ id: 'wrong', width: 200, height: 100 }, 201),
    jsonResponse({ id: '00000000000000000000000000000002', width: 0, height: 100 }, 201),
  ])('reconciles malformed or invalid replacement upload payloads before deleting old', async (badUpload) => {
    let uploads = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') {
        uploads += 1
        return uploads === 1 ? Promise.resolve(jsonResponse(job, 201)) : Promise.resolve(badUpload.clone())
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (url === '/api/jobs/00000000000000000000000000000002' && !options.method) return Promise.resolve(jsonResponse({ ...job, id: '00000000000000000000000000000002' }))
      return Promise.resolve(new Response('', { status: 204 }))
    })
    await openEditor(fetchMock)
    const paste = new Event('paste')
    Object.defineProperty(paste, 'clipboardData', { value: { items: [{ type: 'image/png', getAsFile: () => new File(['x'], 'next.png', { type: 'image/png' }) }] } })
    fireEvent(window, paste)
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE')).toBe(true))
    expect(fetchMock.mock.calls.findIndex(([url]) => url === '/api/jobs/00000000000000000000000000000002')).toBeLessThan(fetchMock.mock.calls.findIndex(([url, options]) => url === '/api/jobs/00000000000000000000000000000001' && options.method === 'DELETE'))
  })

  it.skip('preserves the old job and blocks controls when upload reconciliation is impossible', async () => {
    let uploads = 0
    const deleted = []
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') {
        uploads += 1
        return uploads === 1 ? Promise.resolve(jsonResponse(job, 201)) : Promise.resolve(new Response('{', { status: 201 }))
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (url === '/api/jobs/00000000000000000000000000000002' && !options.method) return Promise.reject(new TypeError('offline'))
      if (options.method === 'DELETE') { deleted.push(url); return Promise.resolve(new Response('', { status: 204 })) }
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    const paste = new Event('paste')
    Object.defineProperty(paste, 'clipboardData', { value: { items: [{ type: 'image/png', getAsFile: () => new File(['x'], 'next.png', { type: 'image/png' }) }] } })
    fireEvent(window, paste)
    expect(await screen.findByRole('alert')).toHaveTextContent('affected images are preserved')
    expect(screen.getByText('200 × 100 pixels')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Transparent PNG' })).toBeDisabled()
    expect(deleted).toEqual([])
  })

  it('reconciles and cancels a lost POST before exposing retry', async () => {
    let posts = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') {
        posts += 1
        return Promise.reject(new TypeError('lost'))
      }
      if (url === '/api/jobs/00000000000000000000000000000001' && !options.method) return Promise.resolve(new Response('', { status: 404 }))
      if (url === '/api/jobs/00000000000000000000000000000001/cancel') return Promise.resolve(jsonResponse({ state: 'cleanup_pending' }, 202))
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    render(<App />)
    fireEvent.change(document.getElementById('image-input'), { target: { files: [new File(['pixels'], 'photo.png', { type: 'image/png' })] } })
    await screen.findByRole('button', { name: 'Retry photo.png' })
    expect(posts).toBe(1)
    expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/jobs/00000000000000000000000000000001' && !options.method)).toBe(true)
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/cancel')).toBe(true)
  })

  it.each(['mutation', 'export'])('treats %s 404 as authoritative expiry and enables a new upload', async (kind) => {
    const fetchMock = installFetch((url, options) => Promise.resolve(new Response('', { status: 404 })))
    fetchMock.mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') return Promise.resolve(jsonResponse({ ...job, id: options.body.get('job_id') }, 201))
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (String(url).includes('/strokes') || String(url).includes('/export?')) return Promise.resolve(new Response('', { status: 404 }))
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    const { stage } = await openEditor(fetchMock)
    if (kind === 'mutation') draw(stage)
    else fireEvent.click(screen.getByRole('button', { name: 'Transparent PNG' }))
    await screen.findByText('Drop up to 10 images here')
    expect(screen.getByRole('alert')).toHaveTextContent('expired')
    expect(document.getElementById('image-input')).toBeEnabled()
  })

  it('does not let an older preview success clear a newer export error', async () => {
    let resolvePreview
    let previews = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') return Promise.resolve(jsonResponse({ ...job, id: options.body.get('job_id') }, 201))
      if (String(url).includes('/preview?')) {
        previews += 1
        if (previews === 1) return Promise.resolve(imageResponse())
        return new Promise((resolve) => { resolvePreview = resolve })
      }
      if (String(url).includes('/export?')) return Promise.resolve(jsonResponse({ detail: 'Newer export error.' }, 500))
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    await openEditor(fetchMock)
    fireEvent.change(screen.getByRole('slider', { name: 'Threshold' }), { target: { value: '5' } })
    await waitFor(() => expect(resolvePreview).toBeTypeOf('function'))
    fireEvent.click(screen.getByRole('button', { name: 'Transparent PNG' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Newer export error.')
    resolvePreview(imageResponse())
    await waitFor(() => expect(screen.getByAltText('Background removal result')).toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('Newer export error.')
  })

  it('preserves late repeated loops in a stroke longer than twenty thousand points', async () => {
    const { fetchMock, stage } = await openEditor()
    fireEvent(stage, new TestPointerEvent('pointerdown', { bubbles: true, clientX: 1, clientY: 101, pointerId: 61 }))
    for (let index = 0; index < 21000; index += 1) {
      const phase = index % 400
      const x = phase < 100 ? 1 + phase * 3.98 : phase < 200 ? 399 : phase < 300 ? 399 - (phase - 200) * 3.98 : 1
      const y = phase < 100 ? 101 : phase < 200 ? 101 + (phase - 100) * 1.98 : phase < 300 ? 299 : 299 - (phase - 300) * 1.98
      fireEvent(stage, new TestPointerEvent('pointermove', { bubbles: true, clientX: x, clientY: y, pointerId: 61 }))
    }
    fireEvent(stage, new TestPointerEvent('pointerup', { bubbles: true, clientX: 399, clientY: 299, pointerId: 61 }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')).toBe(true))
    const points = JSON.parse(fetchMock.mock.calls.find(([url]) => url === '/api/jobs/00000000000000000000000000000001/strokes')[1].body).points
    expect(points.length).toBeLessThanOrEqual(2048)
    expect(points.at(-1)).toEqual([0.9975, 0.995])
    expect(points.some(([x, y]) => x < 0.1 && y < 0.1)).toBe(true)
    expect(points.some(([x, y]) => x > 0.9 && y < 0.1)).toBe(true)
    expect(points.some(([x, y]) => x > 0.9 && y > 0.9)).toBe(true)
    expect(points.some(([x, y]) => x < 0.1 && y > 0.9)).toBe(true)
  }, 20000)

  it('processes multiple selected files strictly one at a time', async () => {
    let resolveFirst
    const first = new Promise((resolve) => { resolveFirst = resolve })
    const posts = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') {
        const id = options.body.get('job_id')
        posts.push(id)
        if (posts.length === 1) return first
        return Promise.resolve(jsonResponse({ id, width: 200, height: 100 }, 201))
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (String(url).endsWith('/cancel')) return Promise.resolve(new Response('', { status: 204 }))
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    render(<App />)
    const chosen = [new File(['one'], 'one.png', { type: 'image/png' }), new File(['two'], 'two.png', { type: 'image/png' })]
    fireEvent.change(document.getElementById('image-input'), { target: { files: chosen } })
    await waitFor(() => expect(posts).toHaveLength(1))
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(posts).toHaveLength(1)
    resolveFirst(jsonResponse({ id: posts[0], width: 200, height: 100 }, 201))
    await waitFor(() => expect(posts).toHaveLength(2))
    await waitFor(() => expect(screen.getAllByText('ready')).toHaveLength(2))
  })

  it('keeps independent jobs and navigates ready results without deleting either', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') {
        const id = options.body.get('job_id')
        return Promise.resolve(jsonResponse({ id, width: 200, height: 100 }, 201))
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    render(<App />)
    fireEvent.change(document.getElementById('image-input'), { target: { files: [new File(['a'], 'a.png', { type: 'image/png' }), new File(['b'], 'b.png', { type: 'image/png' })] } })
    await screen.findByRole('navigation', { name: 'Ready photos' })
    expect(screen.getByText('1 of 2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('2 of 2')
    expect(fetchMock.mock.calls.some(([url, options]) => String(url).includes('/cancel') && options.method === 'POST')).toBe(false)
  })

  it('starts a new batch immediately while cancellation remains independently tracked', async () => {
    const cancelled = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') {
        const id = options.body.get('job_id')
        return Promise.resolve(jsonResponse({ id, width: 200, height: 100 }, 201))
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      if (String(url).endsWith('/cancel')) { cancelled.push(String(url)); return Promise.resolve(jsonResponse({ state: 'cleanup_pending' }, 202)) }
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    render(<App />)
    fireEvent.change(document.getElementById('image-input'), { target: { files: [new File(['a'], 'a.png', { type: 'image/png' })] } })
    await screen.findByText('200 × 100 pixels')
    fireEvent.click(screen.getByRole('button', { name: 'New batch' }))
    await screen.findByText('Drop up to 10 images here')
    await waitFor(() => expect(cancelled).toHaveLength(1))
    expect(screen.queryByLabelText('Batch queue')).toBeNull()
  })

  it('does not cancel a successful upload during StrictMode effect replay', async () => {
    const calls = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      calls.push([String(url), options.method])
      if (url === '/api/jobs' && options.method === 'POST') {
        const id = options.body.get('job_id')
        return Promise.resolve(jsonResponse({ id, width: 200, height: 100 }, 201))
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      return Promise.resolve(jsonResponse({ ok: true }))
    })

    render(<StrictMode><App /></StrictMode>)
    fireEvent.change(document.getElementById('image-input'), { target: { files: [new File(['pixels'], 'strict.png', { type: 'image/png' })] } })

    await screen.findByText('200 × 100 pixels')
    expect(calls.filter(([url]) => url.endsWith('/cancel'))).toEqual([])
    expect(screen.getByText('ready')).toBeInTheDocument()
  })

  it('reconciles a creating lost response until the exact job becomes ready', async () => {
    let probes = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') return Promise.reject(new TypeError('lost'))
      if (url === '/api/jobs/00000000000000000000000000000001' && !options.method) {
        probes += 1
        return probes < 3
          ? Promise.resolve(jsonResponse({ id: '00000000000000000000000000000001', state: 'creating' }, 202))
          : Promise.resolve(jsonResponse(job, 200))
      }
      if (String(url).includes('/preview?')) return Promise.resolve(imageResponse())
      return Promise.resolve(jsonResponse({ ok: true }))
    })

    render(<App />)
    fireEvent.change(document.getElementById('image-input'), { target: { files: [new File(['pixels'], 'recovered.png', { type: 'image/png' })] } })

    await screen.findByText('200 × 100 pixels')
    expect(probes).toBe(3)
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/cancel'))).toBe(false)
    expect(screen.getByText('ready')).toBeInTheDocument()
  })

  it('keeps an unproven cleanup in the ledger without starting a duplicate job', async () => {
    let posts = 0
    let cancels = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, options = {}) => {
      if (url === '/api/jobs' && options.method === 'POST') { posts += 1; return Promise.reject(new TypeError('lost')) }
      if (url === '/api/jobs/00000000000000000000000000000001' && !options.method) return Promise.resolve(new Response('', { status: 404 }))
      if (String(url).endsWith('/cancel')) { cancels += 1; return Promise.reject(new TypeError('offline')) }
      return Promise.resolve(jsonResponse({ ok: true }))
    })

    render(<App />)
    fireEvent.change(document.getElementById('image-input'), { target: { files: [new File(['pixels'], 'uncertain.png', { type: 'image/png' })] } })

    await screen.findByText('cleanup pending')
    expect(posts).toBe(1)
    expect(cancels).toBe(1)
    expect(sessionStorage.getItem('background-studio.cleanup-ledger.v1')).toContain('00000000000000000000000000000001')
    expect(screen.queryByRole('button', { name: 'Retry uncertain.png' })).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

})
