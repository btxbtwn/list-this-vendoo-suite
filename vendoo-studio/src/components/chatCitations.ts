/**
 * Quoting assistant text in the composer, modelled on T3 Code's assistant
 * citations: a selection is stored as the exact quoted text plus normalized
 * offsets and surrounding context, so it can be found again in a message whose
 * markdown has since re-rendered.
 */

export const CITATION_CONTEXT_LENGTH = 32;
export const CITATION_MAX_TEXT_LENGTH = 8000;
export const CITATION_MAX_COMMENT_LENGTH = 8000;

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
  /** A note the seller wrote about this quote; it rides along with the quote. */
  readonly comment?: string;
}

/** Identifies one quote of one message, so a repeated cite does not stack up. */
export function chatCitationId(messageId: string, selector: ChatCitationSelector): string {
  return `${messageId}:${selector.start}:${selector.end}`;
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

/** One-line label for a citation chip; the seller's note wins over the quote. */
export function citationPreview(
  citation: ChatCitationSelector & { comment?: string },
  limit = 64,
): string {
  const preview = normalizeWhitespace(citation.comment?.trim() || citation.text).trim();
  return preview.length > limit ? `${preview.slice(0, limit)}…` : preview;
}

/** Edits only the note, leaving the quote and its source selector unchanged. */
export function withChatCitationComment(citation: ChatCitation, comment: string): ChatCitation {
  const { comment: _previous, ...source } = citation;
  const trimmed = comment.trim();
  return trimmed ? { ...source, comment: trimmed } : source;
}

/**
 * Citation links, following T3 Code: the sent message carries each quote as a
 * self-contained link, so the bubble renders a chip that leads back to the
 * source and the server expands the same link into reference material for the
 * model.
 */
const CITATION_PROTOCOL = "studio-citation:";
const CITATION_HREF_PREFIX = `${CITATION_PROTOCOL}//v1/`;
export const CITATION_LINK_LABEL = "Quoted text";
// Percent encoding needs up to nine characters per UTF-16 code unit; 16k covers selectors.
const MAX_CITATION_HREF_LENGTH =
  9 * (CITATION_MAX_TEXT_LENGTH + CITATION_MAX_COMMENT_LENGTH) + 16_000;
const CITATION_LINK = new RegExp(
  String.raw`\[${CITATION_LINK_LABEL}\]\((${CITATION_HREF_PREFIX}[^\s)]{1,${MAX_CITATION_HREF_LENGTH - CITATION_HREF_PREFIX.length}})\)`,
  "g",
);

function encodePathPart(value: string): string {
  return encodeURIComponent(value).replace(
    /[!'()*]/g,
    (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

/** Self-contained, so the composer draft and the sent message agree. */
export function formatChatCitationHref(citation: ChatCitation): string {
  const query = new URLSearchParams({
    text: citation.text,
    start: String(citation.start),
    end: String(citation.end),
    prefix: citation.prefix,
    suffix: citation.suffix,
  });
  if (citation.comment !== undefined) query.set("comment", citation.comment);
  return `${CITATION_HREF_PREFIX}${encodePathPart(citation.messageId)}?${query}`;
}

export function parseChatCitationHref(href: string): ChatCitation | null {
  if (!href.startsWith(CITATION_HREF_PREFIX) || href.length > MAX_CITATION_HREF_LENGTH) {
    return null;
  }
  try {
    const url = new URL(href);
    const parts = url.pathname.slice(1).split("/");
    if (
      url.protocol !== CITATION_PROTOCOL ||
      url.hostname !== "v1" ||
      parts.length !== 1 ||
      url.username ||
      url.password ||
      url.port ||
      url.hash
    ) {
      return null;
    }
    const requiredKeys = ["text", "start", "end", "prefix", "suffix"];
    const comment = url.searchParams.get("comment");
    if (
      url.searchParams.size !== requiredKeys.length + (comment === null ? 0 : 1) ||
      requiredKeys.some((key) => url.searchParams.getAll(key).length !== 1)
    ) {
      return null;
    }
    const rawStart = url.searchParams.get("start") ?? "";
    const rawEnd = url.searchParams.get("end") ?? "";
    if (!/^\d{1,16}$/.test(rawStart) || !/^\d{1,16}$/.test(rawEnd)) return null;
    const start = Number(rawStart);
    const end = Number(rawEnd);
    const messageId = decodeURIComponent(parts[0]!);
    const text = url.searchParams.get("text") ?? "";
    const prefix = url.searchParams.get("prefix") ?? "";
    const suffix = url.searchParams.get("suffix") ?? "";
    if (
      !messageId ||
      text.trim().length === 0 ||
      text.length > CITATION_MAX_TEXT_LENGTH ||
      (comment !== null && comment.length > CITATION_MAX_COMMENT_LENGTH) ||
      prefix.length > CITATION_CONTEXT_LENGTH ||
      suffix.length > CITATION_CONTEXT_LENGTH ||
      !Number.isSafeInteger(start) ||
      !Number.isSafeInteger(end) ||
      end <= start
    ) {
      return null;
    }
    const selector: ChatCitationSelector = { text, start, end, prefix, suffix };
    return {
      id: chatCitationId(messageId, selector),
      messageId,
      ...selector,
      ...(comment === null ? {} : { comment }),
    };
  } catch {
    return null;
  }
}

export function serializeChatCitation(citation: ChatCitation): string {
  return `[${CITATION_LINK_LABEL}](${formatChatCitationHref(citation)})`;
}

export function collectChatCitations(text: string) {
  const citations: { citation: ChatCitation; source: string; start: number; end: number }[] = [];
  for (const match of text.matchAll(CITATION_LINK)) {
    const citation = parseChatCitationHref(match[1]!);
    if (!citation) continue;
    citations.push({
      citation,
      source: match[0],
      start: match.index,
      end: match.index + match[0].length,
    });
  }
  return citations;
}

/**
 * The sent message carries its quotes as links above the typed text, so the
 * bubble shows chips that lead back to the source.
 */
export function formatCitedMessage(citations: readonly ChatCitation[], text: string): string {
  const body = text.trim();
  if (citations.length === 0) return body;
  return [...citations.map(serializeChatCitation), body].filter(Boolean).join("\n\n");
}
