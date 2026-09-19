import { useCallback, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from "react";

const STORAGE_PREFIX = "vendoo-studio.panel-width.";
const KEY_STEP = 16;

export type PanelWidthLimits = {
  /** Smallest width the panel may take, in pixels. */
  min: number;
  /** Largest width in pixels; the CSS clamps it to `maxVw` of the viewport as well. */
  max: number;
  maxVw: number;
};

export function clampPanelWidth(width: number, min: number, max: number): number {
  return Math.round(Math.min(Math.max(width, min), Math.max(min, max)));
}

function readWidth(key: string): number | null {
  try {
    const value = Number(localStorage.getItem(STORAGE_PREFIX + key));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

/** A panel width the seller dragged to, remembered across launches. `null` means the CSS default. */
export function usePanelWidth(key: string): [number | null, (width: number | null) => void] {
  const [width, setWidthState] = useState(() => readWidth(key));
  const setWidth = useCallback(
    (next: number | null) => {
      setWidthState(next);
      try {
        if (next === null) localStorage.removeItem(STORAGE_PREFIX + key);
        else localStorage.setItem(STORAGE_PREFIX + key, String(next));
      } catch {
        /* ignore quota / private-mode failures */
      }
    },
    [key],
  );
  return [width, setWidth];
}

type PanelResizeHandleProps = PanelWidthLimits & {
  label: string;
  /** Which sibling of the handle is the panel being resized. */
  panel: "before" | "after";
  width: number | null;
  onResize: (width: number | null) => void;
  /** The flexible panel that gives up (or takes back) the width. */
  absorberRef: RefObject<HTMLElement | null>;
  absorberMin: number;
};

/** A vertical splitter between two panels: drag, arrow keys, or double-click to reset. */
export function PanelResizeHandle({
  label,
  panel,
  width,
  onResize,
  absorberRef,
  absorberMin,
  min,
  max,
  maxVw,
}: PanelResizeHandleProps) {
  const drag = useRef<{ startX: number; startWidth: number; max: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const direction = panel === "before" ? 1 : -1;

  const measure = (handle: HTMLElement) => {
    const target = panel === "before" ? handle.previousElementSibling : handle.nextElementSibling;
    const current = target?.getBoundingClientRect().width ?? width ?? min;
    const room = Math.max(0, (absorberRef.current?.getBoundingClientRect().width ?? 0) - absorberMin);
    return { current, max: Math.min(max, (window.innerWidth * maxVw) / 100, current + room) };
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const { current, max: limit } = measure(event.currentTarget);
    drag.current = { startX: event.clientX, startWidth: current, max: limit };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    const next = state.startWidth + (event.clientX - state.startX) * direction;
    onResize(clampPanelWidth(next, min, state.max));
  };

  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setDragging(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const { current, max: limit } = measure(event.currentTarget);
    let next: number;
    if (event.key === "ArrowLeft") next = current - KEY_STEP * direction;
    else if (event.key === "ArrowRight") next = current + KEY_STEP * direction;
    else if (event.key === "Home") next = min;
    else if (event.key === "End") next = limit;
    else return;
    event.preventDefault();
    onResize(clampPanelWidth(next, min, limit));
  };

  return (
    <div
      className={`panel-resize-handle${dragging ? " is-dragging" : ""}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width ?? undefined}
      tabIndex={0}
      title="Drag to resize · double-click to reset"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={onKeyDown}
      onDoubleClick={() => onResize(null)}
    />
  );
}
