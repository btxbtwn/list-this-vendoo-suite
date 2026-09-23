/**
 * Quoting assistant text in the composer, modelled on T3 Code's assistant
 * citations: a selection is stored as the exact quoted text plus normalized
 * offsets and surrounding context, so it can be found again in a message whose
 * markdown has since re-rendered.
 */

export const CITATION_CONTEXT_LENGTH = 32;
export const CITATION_MAX_TEXT_LENGTH = 8000;

export interface ChatCitationSelector {
  readonly text: string;
  readonly start: number;
  readonly end: number;
  readonly prefix: string;
  readonly suffix: string;
}

export interface ChatCitation extends ChatCitationSelector {
  readonly id: string;
  readonly messageId: string;
}

function normalizeWhitespace(text: string): string {
  return text.replace(/\s+/g, " ");
}

function splitsSurrogatePair(text: string, offset: number): boolean {
  const before = text.charCodeAt(offset - 1);
  const after = text.charCodeAt(offset);
  return before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff;
}

/** Keeps the exact captured text while storing normalized UTF-16 positions and context. */
export function createChatCitationSelector(
  text: string,
  rawStart: number,
  rawEnd: number,
): ChatCitationSelector | null {
  const quote = text.slice(rawStart, rawEnd);
  if (quote.trim().length === 0) return null;

  const normalized = normalizeWhitespace(text);
  let start = normalizeWhitespace(text.slice(0, rawStart)).length;
  // A selection starting inside a whitespace run includes its normalized space.
  if (rawStart > 0 && /\s/.test(text[rawStart - 1]!) && /\s/.test(text[rawStart]!)) {
    start -= 1;
  }
  const end = normalizeWhitespace(text.slice(0, rawEnd)).length;
  let prefixStart = Math.max(0, start - CITATION_CONTEXT_LENGTH);
  let suffixEnd = Math.min(normalized.length, end + CITATION_CONTEXT_LENGTH);
  // A split pair would become a replacement character inside the context.
  if (splitsSurrogatePair(normalized, prefixStart)) prefixStart += 1;
  if (splitsSurrogatePair(normalized, suffixEnd)) suffixEnd -= 1;
  return {
    text: quote,
    start,
    end,
    prefix: normalized.slice(prefixStart, start),
    suffix: normalized.slice(end, suffixEnd),
  };
}

/**
 * Matches case-sensitive text after collapsing each whitespace run to one
 * space. Positions are UTF-16 units in that normalized stream, not markdown
 * offsets, so the quote survives re-rendering and soft-wrap changes. A quote
 * that repeats in the message needs its context to pick one occurrence; saved
 * offsets alone cannot break the tie, since they may have drifted.
 */
export function findChatCitationText(
  text: string,
  selector: ChatCitationSelector,
): { start: number; end: number } | null {
  const normalized = normalizeWhitespace(text);
  const quote = normalizeWhitespace(selector.text);
  if (quote.trim().length === 0) return null;

  const prefix = normalizeWhitespace(selector.prefix);
  const suffix = normalizeWhitespace(selector.suffix);
  const matchesContext = (start: number, end: number) =>
    normalized.slice(Math.max(0, start - prefix.length), start) === prefix &&
    normalized.slice(end, end + suffix.length) === suffix;

  let match =
    Number.isSafeInteger(selector.start) &&
    Number.isSafeInteger(selector.end) &&
    selector.start >= 0 &&
    selector.end - selector.start === quote.length &&
    normalized.slice(selector.start, selector.end) === quote &&
    matchesContext(selector.start, selector.end)
      ? { start: selector.start, end: selector.end }
      : null;
  let onlyQuote: { start: number; end: number } | null = null;
  let quoteCount = 0;

  for (
    let start = normalized.indexOf(quote);
    start !== -1;
    start = normalized.indexOf(quote, start + 1)
  ) {
    const end = start + quote.length;
    quoteCount += 1;
    onlyQuote = { start, end };
    if (!matchesContext(start, end)) continue;
    if (match !== null && match.start !== start) return null;
    match = { start, end };
  }

  return match ?? (quoteCount === 1 ? onlyQuote : null);
}

/** Maps a normalized offset back to an offset in the original text. */
export function rawTextOffset(text: string, normalizedOffset: number): number {
  let offset = 0;
  for (const match of text.matchAll(/\s+|\S+/g)) {
    const whitespace = /\s/.test(match[0][0]!);
    const length = whitespace ? 1 : match[0].length;
    if (normalizedOffset <= offset + length) {
      return (
        match.index +
        (whitespace && normalizedOffset > offset ? match[0].length : normalizedOffset - offset)
      );
    }
    offset += length;
  }
  return text.length;
}

/** One-line label for a citation chip. */
export function citationPreview(citation: ChatCitationSelector, limit = 52): string {
  const preview = normalizeWhitespace(citation.text).trim();
  return preview.length > limit ? `${preview.slice(0, limit)}…` : preview;
}

function escapeMarkdown(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/[\\`*_[\]{}()#+.!|~-]/g, "\\$&");
}

/**
 * The sent message carries its quotes inline, so the model reads them as
 * reference material and the user bubble shows what was cited.
 */
export function formatCitedMessage(citations: readonly ChatCitationSelector[], text: string): string {
  const body = text.trim();
  if (citations.length === 0) return body;
  const quotes = citations.map((citation) => {
    const lines = escapeMarkdown(citation.text.trim())
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
    return `> Quoted from your earlier reply:\n${lines}`;
  });
  return [...quotes, body].filter(Boolean).join("\n\n");
}
