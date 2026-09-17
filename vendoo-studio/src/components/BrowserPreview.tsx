import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { api } from "../api/client";
import type { BrowserField, BrowserInputEvent, BrowserRect, BrowserViewport } from "../api/client";
import { addToast } from "../ui/toast";
import { OpenListingButton } from "./OpenListingButton";

interface PreviewFrame {
  mime: string;
  data: string;
  url?: string;
  step?: string;
  width?: number | null;
  height?: number | null;
  viewport_width?: number | null;
  viewport_height?: number | null;
}

type Tool = "interact" | "pick" | "box" | "pen";

interface Point {
  x: number;
  y: number;
}

interface Mark {
  id: number;
  kind: "box" | "pen";
  points: Point[];
}

interface Props {
  jobId: string | null;
  step?: string | null;
  status?: string | null;
  vendooItemId?: string | null;
  vendooUrl?: string | null;
  onCancel?: () => void;
  cancelling?: boolean;
  /** The seller opened this draft to work in it, not just to watch a fill. */
  interactive?: boolean;
  /** Studio is typing into the draft right now. Input and annotation wait. */
  automationRunning?: boolean;
  onClose?: () => void;
  /** The pane fills the whole workspace instead of sharing it with chat. */
  expanded?: boolean;
  onToggleExpanded?: () => void;
  /** Fields the seller pointed at; they ride along with the next chat message. */
  selected: BrowserField[];
  onSelectedChange: (fields: BrowserField[]) => void;
  onGoToChat?: () => void;
}

const TOOLS: { id: Tool; label: string; title: string }[] = [
  { id: "interact", label: "Use", title: "Click, scroll, and type in the Vendoo draft" },
  { id: "pick", label: "Pick", title: "Click a field to point Studio at it" },
  { id: "box", label: "Box", title: "Drag a box around fields" },
  { id: "pen", label: "Pen", title: "Circle fields freehand" },
];

const MARKET_LABELS: Record<string, string> = {
  general: "Vendoo",
  ebay: "eBay",
  etsy: "Etsy",
  poshmark: "Poshmark",
  mercari: "Mercari",
  depop: "Depop",
};

const MOVE_FLUSH_MS = 50;
const SNAPSHOT_REFRESH_MS = 3000;
const SNAPSHOT_SETTLE_MS = 700;
const DOUBLE_CLICK_MS = 400;
const MIN_BOX_RATIO = 0.01;

const MOUSE_BUTTONS = ["left", "middle", "right"] as const;

function fieldId(field: BrowserField): string {
  return `${field.marketplace}:${field.key || field.label.toLowerCase()}`;
}

function marketLabel(marketplace: string): string {
  return MARKET_LABELS[marketplace] || marketplace;
}

function modifierMask(event: { altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }): number {
  return (event.altKey ? 1 : 0) | (event.ctrlKey ? 2 : 0) | (event.metaKey ? 4 : 0) | (event.shiftKey ? 8 : 0);
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function rectRatios(rect: BrowserRect, viewport: BrowserViewport | null) {
  if (!viewport?.width || !viewport?.height) return null;
  return {
    left: rect.x / viewport.width,
    top: rect.y / viewport.height,
    width: rect.width / viewport.width,
    height: rect.height / viewport.height,
  };
}

function boundsOf(points: Point[]) {
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const left = Math.min(...xs);
  const top = Math.min(...ys);
  return { left, top, width: Math.max(...xs) - left, height: Math.max(...ys) - top };
}

function intersects(
  a: { left: number; top: number; width: number; height: number },
  b: { left: number; top: number; width: number; height: number },
): boolean {
  return a.left < b.left + b.width && b.left < a.left + a.width && a.top < b.top + b.height && b.top < a.top + a.height;
}

function markPath(points: Point[]): string {
  return points.map((point, index) => `${index ? "L" : "M"}${point.x} ${point.y}`).join(" ");
}

export function BrowserPreview({
  jobId,
  step,
  status,
  vendooItemId,
  vendooUrl,
  onCancel,
  cancelling,
  interactive = false,
  automationRunning = false,
  onClose,
  expanded = false,
  onToggleExpanded,
  selected,
  onSelectedChange,
  onGoToChat,
}: Props) {
  const [frame, setFrame] = useState<PreviewFrame | null>(null);
  const [live, setLive] = useState(false);
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [tool, setTool] = useState<Tool>("interact");
  const [showMissed, setShowMissed] = useState(false);
  const [fields, setFields] = useState<BrowserField[]>([]);
  const [fieldsViewport, setFieldsViewport] = useState<BrowserViewport | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [marks, setMarks] = useState<Mark[]>([]);
  const [drawing, setDrawing] = useState<Mark | null>(null);

  const stageRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const pendingEvents = useRef<BrowserInputEvent[]>([]);
  const pendingMove = useRef<BrowserInputEvent | null>(null);
  const pendingWheel = useRef<{ x: number; y: number; dx: number; dy: number } | null>(null);
  const flushTimer = useRef<number | null>(null);
  const lastPress = useRef<{ at: number; x: number; y: number; count: number } | null>(null);
  const snapshotInFlight = useRef(false);
  const settleTimer = useRef<number | null>(null);
  const markSeq = useRef(0);
  // Input must reach Chrome in order; parallel requests reorder keystrokes.
  const inputChain = useRef<Promise<unknown>>(Promise.resolve());

  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  const controlsEnabled = interactive && !automationRunning && Boolean(jobId);
  const annotating = tool !== "interact";

  useEffect(() => {
    if (!jobId) {
      setFrame(null);
      setLive(false);
      return;
    }

    const source = new EventSource(`/api/jobs/${jobId}/preview`);
    source.onopen = () => setLive(true);
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as PreviewFrame;
        if (payload?.data) {
          setFrame(payload);
        }
      } catch {
        /* ignore malformed frames */
      }
    };
    source.onerror = () => setLive(false);

    return () => {
      source.close();
      setLive(false);
    };
  }, [jobId]);

  useLayoutEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(([entry]) => {
      setStageSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);

  const surfaceSize = useMemo(() => {
    const width = natural?.width || frame?.viewport_width || 0;
    const height = natural?.height || frame?.viewport_height || 0;
    if (!width || !height || !stageSize.width || !stageSize.height) return null;
    const scale = Math.min(stageSize.width / width, stageSize.height / height);
    return { width: Math.floor(width * scale), height: Math.floor(height * scale) };
  }, [natural, frame?.viewport_width, frame?.viewport_height, stageSize]);

  const refreshSnapshot = useCallback(async () => {
    if (!jobId || !controlsEnabled || snapshotInFlight.current) return;
    snapshotInFlight.current = true;
    try {
      const result = await api.jobs.browser.snapshot(jobId);
      setFields(result.fields || []);
      setFieldsViewport(result.viewport || null);
      const byId = new Map((result.fields || []).map((field) => [fieldId(field), field]));
      const current = selectedRef.current;
      if (current.some((field) => byId.has(fieldId(field)))) {
        onSelectedChange(current.map((field) => byId.get(fieldId(field)) || field));
      }
    } catch {
      /* the next refresh retries; picks still work without a snapshot */
    } finally {
      snapshotInFlight.current = false;
    }
  }, [jobId, controlsEnabled, onSelectedChange]);

  const settleSnapshot = useCallback(() => {
    if (!annotating && !showMissed) return;
    if (settleTimer.current) window.clearTimeout(settleTimer.current);
    settleTimer.current = window.setTimeout(() => {
      settleTimer.current = null;
      void refreshSnapshot();
    }, SNAPSHOT_SETTLE_MS);
  }, [annotating, showMissed, refreshSnapshot]);

  useEffect(() => {
    if (!controlsEnabled || (!annotating && !showMissed)) return;
    void refreshSnapshot();
    const timer = window.setInterval(() => void refreshSnapshot(), SNAPSHOT_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [controlsEnabled, annotating, showMissed, refreshSnapshot]);

  useEffect(() => () => {
    if (flushTimer.current) window.clearTimeout(flushTimer.current);
    if (settleTimer.current) window.clearTimeout(settleTimer.current);
  }, []);

  useEffect(() => {
    setMarks([]);
    setFields([]);
  }, [jobId]);

  useEffect(() => {
    // Sending the chat message consumes the picks; drop the drawings with them.
    if (!selected.length) setMarks([]);
  }, [selected.length]);

  const flushInput = useCallback(() => {
    if (flushTimer.current) {
      window.clearTimeout(flushTimer.current);
      flushTimer.current = null;
    }
    const events = pendingEvents.current;
    if (pendingMove.current) {
      events.push(pendingMove.current);
      pendingMove.current = null;
    }
    const wheel = pendingWheel.current;
    if (wheel) {
      events.push({
        kind: "mouse",
        type: "mouseWheel",
        x_ratio: wheel.x,
        y_ratio: wheel.y,
        delta_x: Math.max(-2000, Math.min(2000, wheel.dx)),
        delta_y: Math.max(-2000, Math.min(2000, wheel.dy)),
      });
      pendingWheel.current = null;
      settleSnapshot();
    }
    pendingEvents.current = [];
    if (!jobId || !events.length) return;
    for (let index = 0; index < events.length; index += 40) {
      const batch = events.slice(index, index + 40);
      inputChain.current = inputChain.current
        .then(() => api.jobs.browser.input(jobId, batch))
        .catch(() => {});
    }
  }, [jobId, settleSnapshot]);

  const queueInput = useCallback((event: BrowserInputEvent, { immediate = false } = {}) => {
    if (event.type === "mouseMoved") {
      pendingMove.current = event;
    } else {
      if (pendingMove.current) {
        pendingEvents.current.push(pendingMove.current);
        pendingMove.current = null;
      }
      pendingEvents.current.push(event);
    }
    if (immediate) {
      flushInput();
      return;
    }
    if (!flushTimer.current) {
      flushTimer.current = window.setTimeout(flushInput, MOVE_FLUSH_MS);
    }
  }, [flushInput]);

  const ratioOf = useCallback((clientX: number, clientY: number): Point | null => {
    const surface = surfaceRef.current;
    if (!surface) return null;
    const rect = surface.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return { x: clamp01((clientX - rect.left) / rect.width), y: clamp01((clientY - rect.top) / rect.height) };
  }, []);

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface || !controlsEnabled) return;
    const onWheel = (event: WheelEvent) => {
      if (tool !== "interact") return;
      event.preventDefault();
      const point = ratioOf(event.clientX, event.clientY);
      if (!point) return;
      const scale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1;
      const current = pendingWheel.current || { x: point.x, y: point.y, dx: 0, dy: 0 };
      pendingWheel.current = {
        x: point.x,
        y: point.y,
        dx: current.dx + event.deltaX * scale,
        dy: current.dy + event.deltaY * scale,
      };
      if (!flushTimer.current) flushTimer.current = window.setTimeout(flushInput, MOVE_FLUSH_MS);
    };
    surface.addEventListener("wheel", onWheel, { passive: false });
    return () => surface.removeEventListener("wheel", onWheel);
    // surfaceRef only mounts once the first frame arrives, so this must re-run then too.
  }, [controlsEnabled, tool, ratioOf, flushInput, Boolean(frame)]);

  const fieldBoxes = useMemo(() => fields
    .map((field) => ({ field, box: rectRatios(field.rect, fieldsViewport) }))
    .filter((entry): entry is { field: BrowserField; box: NonNullable<ReturnType<typeof rectRatios>> } => (
      Boolean(entry.box) && entry.box!.width > 0 && entry.box!.height > 0
      && entry.box!.top < 1 && entry.box!.top + entry.box!.height > 0
    )), [fields, fieldsViewport]);

  const selectedIds = useMemo(() => new Set(selected.map(fieldId)), [selected]);

  const addFields = useCallback((incoming: BrowserField[]) => {
    const usable = incoming.filter((field) => field.label && !field.disabled);
    if (!usable.length) return 0;
    const current = selectedRef.current;
    const ids = new Set(current.map(fieldId));
    onSelectedChange([...current, ...usable.filter((field) => !ids.has(fieldId(field)))]);
    return usable.length;
  }, [onSelectedChange]);

  const toggleField = useCallback((field: BrowserField) => {
    const current = selectedRef.current;
    onSelectedChange(
      current.some((item) => fieldId(item) === fieldId(field))
        ? current.filter((item) => fieldId(item) !== fieldId(field))
        : [...current, field],
    );
  }, [onSelectedChange]);

  const pickAt = useCallback(async (point: Point) => {
    if (!jobId) return;
    try {
      const result = await api.jobs.browser.pick(jobId, point.x, point.y);
      if (result.field) {
        toggleField(result.field);
      } else {
        addToast({
          type: "error",
          title: "No field there",
          description: result.element?.text
            ? `That is "${result.element.text.slice(0, 60)}", not a listing field.`
            : "Click on a listing field or its label.",
        });
      }
    } catch (err) {
      addToast({ type: "error", title: "Could not pick that field", description: (err as Error).message });
    }
  }, [jobId, toggleField]);

  const finishMark = useCallback((mark: Mark) => {
    const bounds = boundsOf(mark.points);
    if (bounds.width < MIN_BOX_RATIO && bounds.height < MIN_BOX_RATIO) return;
    setMarks((current) => [...current, mark]);
    const inside = fieldBoxes.filter(({ box }) => intersects(bounds, box)).map(({ field }) => field);
    const added = addFields(inside);
    if (!added) {
      addToast({
        type: "error",
        title: "No fields inside that mark",
        description: "Scroll the fields into view, then draw around them again.",
      });
    }
  }, [fieldBoxes, addFields]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!controlsEnabled) return;
    const point = ratioOf(event.clientX, event.clientY);
    if (!point) return;
    surfaceRef.current?.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    if (tool === "interact") {
      const now = Date.now();
      const last = lastPress.current;
      const repeat = last && now - last.at < DOUBLE_CLICK_MS && Math.abs(last.x - point.x) < 0.01 && Math.abs(last.y - point.y) < 0.01;
      const count = repeat ? Math.min(3, last.count + 1) : 1;
      lastPress.current = { at: now, x: point.x, y: point.y, count };
      const button = MOUSE_BUTTONS[event.button] || "left";
      queueInput({ kind: "mouse", type: "mouseMoved", x_ratio: point.x, y_ratio: point.y, button: "none" });
      queueInput({
        kind: "mouse",
        type: "mousePressed",
        x_ratio: point.x,
        y_ratio: point.y,
        button,
        buttons: event.buttons,
        click_count: count,
        modifiers: modifierMask(event),
      }, { immediate: true });
    } else if (tool === "box" || tool === "pen") {
      markSeq.current += 1;
      setDrawing({ id: markSeq.current, kind: tool, points: [point, point] });
    }
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!controlsEnabled) return;
    const point = ratioOf(event.clientX, event.clientY);
    if (!point) return;
    if (tool === "interact") {
      queueInput({
        kind: "mouse",
        type: "mouseMoved",
        x_ratio: point.x,
        y_ratio: point.y,
        button: event.buttons & 1 ? "left" : "none",
        buttons: event.buttons,
        modifiers: modifierMask(event),
      });
      return;
    }
    if (drawing) {
      setDrawing({
        ...drawing,
        points: drawing.kind === "box" ? [drawing.points[0], point] : [...drawing.points, point],
      });
      return;
    }
    if (tool === "pick") {
      const hit = fieldBoxes.find(({ box }) => (
        point.x >= box.left && point.x <= box.left + box.width && point.y >= box.top && point.y <= box.top + box.height
      ));
      setHovered(hit ? fieldId(hit.field) : null);
    }
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!controlsEnabled) return;
    const point = ratioOf(event.clientX, event.clientY);
    if (!point) return;
    if (tool === "interact") {
      queueInput({
        kind: "mouse",
        type: "mouseReleased",
        x_ratio: point.x,
        y_ratio: point.y,
        button: MOUSE_BUTTONS[event.button] || "left",
        buttons: event.buttons,
        click_count: lastPress.current?.count || 1,
        modifiers: modifierMask(event),
      }, { immediate: true });
      settleSnapshot();
    } else if (tool === "pick") {
      void pickAt(point);
    } else if (drawing) {
      const done = { ...drawing, points: drawing.kind === "box" ? [drawing.points[0], point] : [...drawing.points, point] };
      setDrawing(null);
      finishMark(done);
    }
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!controlsEnabled || tool !== "interact" || event.nativeEvent.isComposing) return;
    const shortcut = event.metaKey || event.ctrlKey;
    // Let the paste event carry clipboard text instead of a synthetic Cmd+V.
    if (shortcut && event.key.toLowerCase() === "v") return;
    event.preventDefault();
    queueInput({ kind: "key", type: "down", key: event.key, code: event.code, modifiers: modifierMask(event) }, { immediate: true });
  };

  const handleKeyUp = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!controlsEnabled || tool !== "interact") return;
    if (event.key.length === 1 && event.key !== " ") return;
    event.preventDefault();
    queueInput({ kind: "key", type: "up", key: event.key, code: event.code, modifiers: modifierMask(event) }, { immediate: true });
    settleSnapshot();
  };

  const url = frame?.url || "";
  const label = step || frame?.step || status || "idle";
  const isMissed = (field: BrowserField) => !field.filled && !field.disabled && !field.account_managed;
  // Select covers every empty field on the page; outlines only draw the ones in frame.
  const missedFields = showMissed ? fields.filter((field) => field.label && isMissed(field)) : [];
  const missed = showMissed ? fieldBoxes.filter(({ field }) => isMissed(field)) : [];
  const selectedBoxes = fieldBoxes.filter(({ field }) => selectedIds.has(fieldId(field)));
  const hoveredBox = tool === "pick" && hovered ? fieldBoxes.find(({ field }) => fieldId(field) === hovered) : null;

  return (
    <section className="browser-preview is-open" aria-label="Live listing browser">
      <div className="browser-preview-bar">
        <span className="browser-preview-title">Browser</span>
        <span className="browser-preview-url" title={url}>
          {url || "Waiting for Vendoo…"}
        </span>
        <span className={`browser-preview-live${live && frame ? " on" : live ? " wait" : ""}`}>
          {live && frame ? "Live" : live ? "Connecting" : "Standby"}
        </span>
        <span className="browser-preview-step">{label.replace(/_/g, " ")}</span>
        <div className="browser-preview-actions">
          {jobId && (vendooItemId || vendooUrl) ? (
            <OpenListingButton
              jobId={jobId}
              vendooItemId={vendooItemId}
              vendooUrl={vendooUrl}
              className="browser-preview-open"
            />
          ) : null}
          {onCancel && automationRunning && (
            <button
              type="button"
              className="browser-preview-cancel"
              onClick={onCancel}
              disabled={cancelling}
            >
              {cancelling ? "Cancelling…" : "Cancel"}
            </button>
          )}
          {onToggleExpanded && (
            <button
              type="button"
              className="browser-preview-cancel"
              onClick={onToggleExpanded}
              aria-pressed={expanded}
              title={expanded ? "Share the workspace with chat again" : "Give the browser the whole workspace"}
            >
              {expanded ? "Shrink" : "Expand"}
            </button>
          )}
          {interactive && onClose && (
            <button type="button" className="browser-preview-cancel" onClick={onClose}>
              Close
            </button>
          )}
        </div>
      </div>

      {interactive && (
        <div className="browser-tools" role="toolbar" aria-label="Browser tools">
          {TOOLS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`browser-tool${tool === item.id ? " is-active" : ""}`}
              title={item.title}
              aria-pressed={tool === item.id}
              disabled={!controlsEnabled}
              onClick={() => setTool(item.id)}
            >
              {item.label}
            </button>
          ))}
          <span className="browser-tools-sep" aria-hidden="true" />
          <button
            type="button"
            className={`browser-tool${showMissed ? " is-active" : ""}`}
            title="Outline listing fields that are still empty"
            aria-pressed={showMissed}
            disabled={!controlsEnabled}
            onClick={() => setShowMissed((value) => !value)}
          >
            Missed fields
          </button>
          {showMissed && missedFields.length > 0 && (
            <button
              type="button"
              className="browser-tool"
              title="Point Studio at every empty field on the page, including ones scrolled out of view"
              disabled={!controlsEnabled}
              onClick={() => addFields(missedFields)}
            >
              Select {missedFields.length} empty
            </button>
          )}
          {marks.length > 0 && (
            <button type="button" className="browser-tool" onClick={() => setMarks([])}>
              Clear marks
            </button>
          )}
          <span className="browser-tools-status">
            {automationRunning ? "Studio is filling this draft" : tool === "interact" ? "You are driving" : "Annotating"}
          </span>
        </div>
      )}

      <div className="browser-preview-stage" ref={stageRef}>
        {frame ? (
          <div
            ref={surfaceRef}
            className={`browser-surface tool-${tool}${controlsEnabled ? " is-interactive" : ""}`}
            style={surfaceSize ? { width: surfaceSize.width, height: surfaceSize.height } : undefined}
            tabIndex={controlsEnabled ? 0 : -1}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={() => setHovered(null)}
            onKeyDown={handleKeyDown}
            onKeyUp={handleKeyUp}
            onPaste={(event) => {
              if (!controlsEnabled || tool !== "interact") return;
              const text = event.clipboardData.getData("text/plain");
              if (!text) return;
              event.preventDefault();
              queueInput({ kind: "text", text: text.slice(0, 2000) }, { immediate: true });
            }}
            onContextMenu={(event) => controlsEnabled && event.preventDefault()}
          >
            <img
              className="browser-preview-frame"
              src={`data:${frame.mime};base64,${frame.data}`}
              alt="Live Vendoo listing"
              draggable={false}
              onLoad={(event) => {
                const img = event.currentTarget;
                if (img.naturalWidth && img.naturalHeight && (img.naturalWidth !== natural?.width || img.naturalHeight !== natural?.height)) {
                  setNatural({ width: img.naturalWidth, height: img.naturalHeight });
                }
              }}
            />
            {interactive && (
              <div className="browser-overlay" aria-hidden="true">
                {missed.map(({ field, box }) => (
                  <div
                    key={`missed-${fieldId(field)}`}
                    className={`browser-field-box is-missed${field.required ? " is-required" : ""}`}
                    style={{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }}
                  />
                ))}
                {hoveredBox && (
                  <div
                    className="browser-field-box is-hover"
                    style={{ left: `${hoveredBox.box.left * 100}%`, top: `${hoveredBox.box.top * 100}%`, width: `${hoveredBox.box.width * 100}%`, height: `${hoveredBox.box.height * 100}%` }}
                  >
                    <span className="browser-field-tag">{marketLabel(hoveredBox.field.marketplace)} / {hoveredBox.field.label}</span>
                  </div>
                )}
                {selectedBoxes.map(({ field, box }) => (
                  <div
                    key={`selected-${fieldId(field)}`}
                    className="browser-field-box is-selected"
                    style={{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }}
                  />
                ))}
                <svg className="browser-marks" viewBox="0 0 1 1" preserveAspectRatio="none">
                  {[...marks, ...(drawing ? [drawing] : [])].map((mark) => {
                    if (mark.kind === "box") {
                      const bounds = boundsOf(mark.points);
                      return <rect key={mark.id} x={bounds.left} y={bounds.top} width={bounds.width} height={bounds.height} />;
                    }
                    return <path key={mark.id} d={markPath(mark.points)} />;
                  })}
                </svg>
              </div>
            )}
          </div>
        ) : (
          <div className="browser-preview-empty">
            <p>{live ? "Connecting to the Vendoo tab…" : "Starting live view…"}</p>
            <p className="text-xs text-muted">
              {interactive
                ? "Opening the Vendoo draft in Chrome. You can click, type, and point at fields here once it loads."
                : "Chrome is filling the listing in its own window. That window closes when the draft is saved."}
            </p>
          </div>
        )}
      </div>

      {interactive && onGoToChat && selected.length > 0 && (
        <div className="browser-composer">
          <div className="browser-composer-row">
            <span className="browser-composer-hint">
              {selected.length} field{selected.length === 1 ? "" : "s"} picked. They go with your next chat message.
            </span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onSelectedChange([])}>
              Clear
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={onGoToChat}>
              Write in chat
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
