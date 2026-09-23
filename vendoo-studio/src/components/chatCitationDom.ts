/**
 * Reads and re-finds cited text in the rendered chat, following T3 Code's
 * approach: a message's displayed text is streamed from the DOM (not its
 * markdown), so a quote resolves back to a live Range after re-render.
 */
import {
  createChatCitationSelector,
  findChatCitationText,
  rawTextOffset,
  type ChatCitation,
  type ChatCitationSelector,
} from "./chatCitations";

export const CITATION_SOURCE_ATTR = "data-citation-source";
const CITATION_HIGHLIGHT = "chat-citation";
// T3 Code's citation pulse: two beats, a hold so a late glance still finds the
// quote, then a fade.
const CITATION_PULSE_DURATION_MS = 650;
const CITATION_HIGHLIGHT_HOLD_MS = 1575;
const CITATION_HIGHLIGHT_FADE_MS = 450;
const CITATION_HIGHLIGHT_TOTAL_MS =
  1.5 * CITATION_PULSE_DURATION_MS + CITATION_HIGHLIGHT_HOLD_MS + CITATION_HIGHLIGHT_FADE_MS;
const CITATION_HIGHLIGHT_OPACITY = "--chat-citation-highlight-opacity";
const CITATION_HIGHLIGHT_PEAK = 0.45;

const CONTROL_SELECTOR = "button, input, textarea, select, [role=button], [contenteditable]";
const EXCLUDED_SELECTOR = `${CONTROL_SELECTOR}, [hidden], [aria-hidden=true], script, style, template, noscript, svg`;
const BLOCK_SELECTOR =
  "address, article, aside, blockquote, dd, div, dl, dt, figcaption, figure, footer, h1, h2, h3, h4, h5, h6, header, hr, li, main, nav, ol, p, pre, section, table, td, th, tr, ul";

interface TextChunk {
  node: Text;
  start: number;
  end: number;
}

/**
 * DOM text order, with a line break between blocks and at <br>. Controls and
 * hidden subtrees contribute nothing; no layout reads or generated content
 * enter the stream, so reflow cannot move it.
 */
function readMessageText(root: HTMLElement): { text: string; chunks: TextChunk[] } {
  const parts: string[] = [];
  const chunks: TextChunk[] = [];
  let length = 0;
  let separator = false;

  const visit = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node as Text;
      if (text.length === 0) return;
      if (separator && length > 0) {
        parts.push("\n");
        length += 1;
      }
      separator = false;
      chunks.push({ node: text, start: length, end: length + text.length });
      parts.push(text.data);
      length += text.length;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const element = node as Element;
    if (element.matches(EXCLUDED_SELECTOR)) return;
    const block = element.matches(BLOCK_SELECTOR);
    if (block || element.tagName === "BR") separator = true;
    for (const child of element.childNodes) visit(child);
    if (block) separator = true;
  };

  visit(root);
  return { text: parts.join(""), chunks };
}

function excludedAncestor(node: Node): Element | null {
  const element = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement;
  return element?.closest(EXCLUDED_SELECTOR) ?? null;
}

function isUsableRange(root: HTMLElement, range: Range): boolean {
  return (
    !range.collapsed &&
    root.contains(range.startContainer) &&
    root.contains(range.endContainer) &&
    excludedAncestor(range.startContainer) === null &&
    excludedAncestor(range.endContainer) === null
  );
}

function selectedTextBoundary(range: Range, node: Node, last: boolean): Text | null {
  if (!range.intersectsNode(node)) return null;
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node as Text;
    const start = node === range.startContainer ? range.startOffset : 0;
    const end = node === range.endContainer ? range.endOffset : text.length;
    return start < end ? text : null;
  }
  for (
    let child = last ? node.lastChild : node.firstChild;
    child !== null;
    child = last ? child.previousSibling : child.nextSibling
  ) {
    const boundary = selectedTextBoundary(range, child, last);
    if (boundary !== null) return boundary;
  }
  return null;
}

export interface CapturedChatSelection {
  source: HTMLElement;
  messageId: string;
  selector: ChatCitationSelector;
  range: Range;
}

/** Captures the ordered native range, including selections dragged backwards. */
export function captureChatSelection(
  viewport: HTMLElement,
  selection: Selection | null,
): CapturedChatSelection | null {
  if (selection === null || selection.isCollapsed || selection.rangeCount !== 1) return null;
  const range = selection.getRangeAt(0).cloneRange();
  const first = selectedTextBoundary(range, range.commonAncestorContainer, false);
  const last = selectedTextBoundary(range, range.commonAncestorContainer, true);
  if (first === null || last === null) return null;
  const source = first.parentElement?.closest<HTMLElement>(`[${CITATION_SOURCE_ATTR}]`);
  const messageId = source?.dataset.citationSource;
  if (!source || !messageId || !viewport.contains(source)) return null;

  // A paragraph selection can end at the next block's offset 0 or at a parent
  // boundary. Validate the text actually selected, not that empty endpoint.
  range.setStart(first, first === range.startContainer ? range.startOffset : 0);
  range.setEnd(last, last === range.endContainer ? range.endOffset : last.length);
  if (!isUsableRange(source, range)) return null;

  const stream = readMessageText(source);
  let rawStart: number | null = null;
  let rawEnd = 0;
  for (const chunk of stream.chunks) {
    if (!range.intersectsNode(chunk.node)) continue;
    const start = range.startContainer === chunk.node ? range.startOffset : 0;
    const end = range.endContainer === chunk.node ? range.endOffset : chunk.node.length;
    if (start === end) continue;
    rawStart ??= chunk.start + start;
    rawEnd = chunk.start + end;
  }
  if (rawStart === null) return null;
  const selector = createChatCitationSelector(stream.text, rawStart, rawEnd);
  return selector === null ? null : { source, messageId, selector, range };
}

/** Resolves a saved quote against the current DOM without touching the selection. */
export function resolveChatCitationRange(
  root: HTMLElement,
  selector: ChatCitationSelector,
): Range | null {
  if (excludedAncestor(root) !== null) return null;
  const stream = readMessageText(root);
  const match = findChatCitationText(stream.text, selector);
  if (match === null) return null;

  const start = rawTextOffset(stream.text, match.start);
  const end = rawTextOffset(stream.text, match.end);
  const first = stream.chunks.find((chunk) => chunk.end > start);
  let last: TextChunk | undefined;
  for (const chunk of stream.chunks) {
    if (chunk.start < end) last = chunk;
  }
  if (first === undefined || last === undefined) return null;

  const range = root.ownerDocument.createRange();
  range.setStart(first.node, Math.max(0, start - first.start));
  range.setEnd(last.node, Math.min(last.node.length, end - last.start));
  return isUsableRange(root, range) ? range : null;
}

export function findChatCitationSource(
  viewport: HTMLElement,
  messageId: string,
): HTMLElement | null {
  return [...viewport.querySelectorAll<HTMLElement>(`[${CITATION_SOURCE_ATTR}]`)].find(
    (element) => element.dataset.citationSource === messageId,
  ) ?? null;
}

let activePulse: Animation | null = null;

/** Scrolls the quoted text into view and pulses it, following T3 Code. */
export function revealChatCitation(viewport: HTMLElement, citation: ChatCitation): boolean {
  const source = findChatCitationSource(viewport, citation.messageId);
  const range = source ? resolveChatCitationRange(source, citation) : null;
  if (!source || !range) return false;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const rect = range.getBoundingClientRect();
  const viewportRect = viewport.getBoundingClientRect();
  if (rect.top < viewportRect.top + 24 || rect.bottom > viewportRect.bottom - 24) {
    viewport.scrollTo({
      top: Math.max(0, viewport.scrollTop + rect.top - viewportRect.top - viewportRect.height / 3),
      behavior: reducedMotion ? "auto" : "smooth",
    });
  }

  if (typeof Highlight === "undefined" || typeof CSS === "undefined" || !CSS.highlights) {
    return true;
  }
  activePulse?.cancel();
  const highlight = new Highlight(range);
  CSS.highlights.set(CITATION_HIGHLIGHT, highlight);
  const at = (milliseconds: number) => milliseconds / CITATION_HIGHLIGHT_TOTAL_MS;
  const holdEnd = at(CITATION_HIGHLIGHT_TOTAL_MS - CITATION_HIGHLIGHT_FADE_MS);
  const pulse = source.animate(
    reducedMotion
      ? [
          { offset: 0, [CITATION_HIGHLIGHT_OPACITY]: CITATION_HIGHLIGHT_PEAK },
          { offset: holdEnd, [CITATION_HIGHLIGHT_OPACITY]: CITATION_HIGHLIGHT_PEAK },
          { offset: 1, [CITATION_HIGHLIGHT_OPACITY]: 0 },
        ]
      : [
          { offset: 0, [CITATION_HIGHLIGHT_OPACITY]: 0 },
          {
            offset: at(CITATION_PULSE_DURATION_MS * 0.5),
            [CITATION_HIGHLIGHT_OPACITY]: CITATION_HIGHLIGHT_PEAK,
          },
          { offset: at(CITATION_PULSE_DURATION_MS), [CITATION_HIGHLIGHT_OPACITY]: 0 },
          {
            offset: at(CITATION_PULSE_DURATION_MS * 1.5),
            [CITATION_HIGHLIGHT_OPACITY]: CITATION_HIGHLIGHT_PEAK,
          },
          { offset: holdEnd, [CITATION_HIGHLIGHT_OPACITY]: CITATION_HIGHLIGHT_PEAK },
          { offset: 1, [CITATION_HIGHLIGHT_OPACITY]: 0 },
        ],
    { duration: CITATION_HIGHLIGHT_TOTAL_MS, easing: "ease-in-out" },
  );
  activePulse = pulse;
  const clear = () => {
    if (activePulse !== pulse) return;
    activePulse = null;
    if (CSS.highlights.get(CITATION_HIGHLIGHT) === highlight) {
      CSS.highlights.delete(CITATION_HIGHLIGHT);
    }
  };
  void pulse.finished.then(clear, clear);
  return true;
}
