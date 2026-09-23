import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { captureChatSelection } from "./chatCitationDom";
import { CITATION_MAX_TEXT_LENGTH, type ChatCitation } from "./chatCitations";
import {
  observeSelectionActions,
  resolveSelectionActionPosition,
  type SelectionActionPoint,
} from "./selectionActions";

function QuoteIcon() {
  return (
    <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 11H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v8a4 4 0 0 1-4 4" />
      <path d="M20 11h-4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v8a4 4 0 0 1-4 4" />
    </svg>
  );
}

interface Props {
  /** The scroll container holding the messages; citations come from inside it. */
  viewport: HTMLElement | null;
  /** Returns false when the citation was rejected, leaving the button open. */
  onCite: (citation: ChatCitation) => boolean;
}

/** Floating "Cite" button over a text selection in a chat message. */
export function CiteSelectionToolbar({ viewport, onCite }: Props) {
  const [selection, setSelection] = useState<{
    citation: ChatCitation;
    position: SelectionActionPoint;
  } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const actionsRef = useRef<ReturnType<typeof observeSelectionActions> | null>(null);

  useLayoutEffect(() => {
    const button = buttonRef.current;
    if (!button || !selection) return;
    const rect = button.getBoundingClientRect();
    button.style.left = `${Math.max(8, Math.min(selection.position.x, window.innerWidth - rect.width - 8))}px`;
    button.style.top = `${Math.max(8, Math.min(selection.position.y, window.innerHeight - rect.height - 8))}px`;
  }, [selection]);

  useEffect(() => {
    if (!viewport) return;
    const clear = () => setSelection(null);
    const update = (pointer: SelectionActionPoint | null) => {
      const captured = captureChatSelection(viewport, window.getSelection());
      if (!captured) {
        clear();
        return;
      }
      const rect = captured.range.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      if (rect.bottom < viewportRect.top || rect.top > viewportRect.bottom || rect.width === 0) {
        clear();
        return;
      }
      const rects = captured.range.getClientRects();
      setSelection({
        citation: {
          id: `${captured.messageId}:${captured.selector.start}:${captured.selector.end}`,
          messageId: captured.messageId,
          ...captured.selector,
        },
        position: resolveSelectionActionPosition({
          bounds: viewportRect,
          selectionRect: rects.item(rects.length - 1) ?? rect,
          pointer,
          viewport: { width: window.innerWidth, height: window.innerHeight },
        }),
      });
    };
    const actions = observeSelectionActions({
      element: viewport,
      getActionElement: () => buttonRef.current,
      onSelection: update,
      onDismiss: clear,
    });
    actionsRef.current = actions;
    document.addEventListener("selectionchange", actions.selectionChanged);
    return () => {
      document.removeEventListener("selectionchange", actions.selectionChanged);
      actions.dispose();
      actionsRef.current = null;
    };
  }, [viewport]);

  if (!selection) return null;
  const tooLong = selection.citation.text.length > CITATION_MAX_TEXT_LENGTH;
  const dismiss = () => {
    actionsRef.current?.cancel();
    setSelection(null);
  };
  return createPortal(
    <button
      ref={buttonRef}
      type="button"
      className="cite-selection"
      disabled={tooLong}
      title={tooLong ? "Selection is too long to cite" : "Quote this text in your message"}
      aria-label={tooLong ? "Selection is too long to cite" : "Cite selection in composer"}
      style={{ left: selection.position.x, top: selection.position.y }}
      onPointerDown={(event) => event.preventDefault()}
      onClick={() => {
        if (tooLong || !onCite(selection.citation)) return;
        window.getSelection()?.removeAllRanges();
        dismiss();
      }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Escape" && !event.nativeEvent.isComposing) {
          event.preventDefault();
          dismiss();
        }
      }}
    >
      <QuoteIcon />
      {tooLong ? "Shorten selection" : "Cite"}
    </button>,
    document.body,
  );
}
