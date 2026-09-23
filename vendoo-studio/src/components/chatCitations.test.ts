import { describe, expect, it } from "vitest";
import {
  chatCitationId,
  citationPreview,
  collectChatCitations,
  createChatCitationSelector,
  findChatCitationText,
  formatChatCitationHref,
  parseChatCitationHref,
  rawTextOffset,
  serializeChatCitation,
  withChatCitationComment,
  type ChatCitation,
} from "./chatCitations";

const MESSAGE = "The jacket is wool.\nThe lining is silk.";

function selectorFor(text: string, quote: string, occurrence = 0) {
  let start = -1;
  for (let i = 0; i <= occurrence; i += 1) start = text.indexOf(quote, start + 1);
  const selector = createChatCitationSelector(text, start, start + quote.length);
  if (!selector) throw new Error("expected a selector");
  return selector;
}

function citationFor(messageId: string, text: string, quote: string): ChatCitation {
  const selector = selectorFor(text, quote);
  return { id: chatCitationId(messageId, selector), messageId, ...selector };
}

describe("createChatCitationSelector", () => {
  it("keeps the exact quote and captures its context", () => {
    const selector = selectorFor(MESSAGE, "lining");
    expect(selector.text).toBe("lining");
    expect(selector.prefix).toBe("The jacket is wool. The ");
    expect(selector.suffix).toBe(" is silk.");
  });

  it("rejects a whitespace-only selection", () => {
    expect(createChatCitationSelector("a  b", 1, 3)).toBeNull();
  });

  it("stores offsets in the whitespace-normalized stream", () => {
    const selector = selectorFor(MESSAGE, "The lining");
    expect(selector.start).toBe(20);
    expect(selector.end).toBe(30);
  });
});

describe("findChatCitationText", () => {
  it("finds a quote after the message re-wraps", () => {
    const selector = selectorFor(MESSAGE, "lining");
    const rerendered = "The jacket is wool.\n\n   The lining is   silk.";
    const match = findChatCitationText(rerendered, selector);
    expect(match).not.toBeNull();
    expect(rerendered.slice(rawTextOffset(rerendered, match!.start), rawTextOffset(rerendered, match!.end))).toBe("lining");
  });

  it("uses context to pick between repeated quotes", () => {
    const text = "Measure the sleeve. Then measure the sleeve again.";
    const selector = selectorFor(text, "the sleeve", 1);
    const match = findChatCitationText(text, selector);
    expect(match?.start).toBe(text.indexOf("the sleeve", 20));
  });

  it("gives up when a repeated quote lost its context", () => {
    const text = "Measure the sleeve. Then measure the sleeve again.";
    const selector = { ...selectorFor(text, "the sleeve", 1), prefix: "", suffix: "" };
    expect(findChatCitationText(text, selector)).toBeNull();
  });

  it("returns a lone match even when the offsets drifted", () => {
    const selector = selectorFor(MESSAGE, "lining");
    const shifted = `Sizing note.\n${MESSAGE}`;
    expect(findChatCitationText(shifted, selector)).toEqual({
      start: shifted.indexOf("lining"),
      end: shifted.indexOf("lining") + "lining".length,
    });
  });

  it("returns null when the text is gone", () => {
    expect(findChatCitationText("Nothing alike here.", selectorFor(MESSAGE, "lining"))).toBeNull();
  });
});

describe("citation links", () => {
  it("round-trips a quote through its href", () => {
    const citation = citationFor("m1", MESSAGE, "The lining is silk.");
    const parsed = parseChatCitationHref(formatChatCitationHref(citation));
    expect(parsed).toEqual(citation);
  });

  it("round-trips the seller's comment", () => {
    const citation = withChatCitationComment(citationFor("m1", MESSAGE, "wool"), "  wrong fibre ");
    expect(citation.comment).toBe("wrong fibre");
    expect(parseChatCitationHref(formatChatCitationHref(citation))?.comment).toBe("wrong fibre");
  });

  it("drops the comment when it is cleared", () => {
    const citation = withChatCitationComment(
      withChatCitationComment(citationFor("m1", MESSAGE, "wool"), "note"),
      "   ",
    );
    expect(citation.comment).toBeUndefined();
    expect(formatChatCitationHref(citation)).not.toContain("comment=");
  });

  it("keeps message ids with slashes and spaces intact", () => {
    const citation = citationFor("msg 1/2", MESSAGE, "wool");
    expect(parseChatCitationHref(formatChatCitationHref(citation))?.messageId).toBe("msg 1/2");
  });

  it("rejects hrefs that are not citations", () => {
    expect(parseChatCitationHref("https://example.com")).toBeNull();
    expect(parseChatCitationHref("studio-citation://v1/m1?text=hi")).toBeNull();
    expect(parseChatCitationHref("studio-citation://v2/m1?text=hi&start=0&end=2&prefix=&suffix=")).toBeNull();
  });

  it("rejects an empty quote and a backwards range", () => {
    expect(
      parseChatCitationHref("studio-citation://v1/m1?text=%20&start=0&end=2&prefix=&suffix="),
    ).toBeNull();
    expect(
      parseChatCitationHref("studio-citation://v1/m1?text=hi&start=4&end=2&prefix=&suffix="),
    ).toBeNull();
  });

  it("collects the quotes sitting inline in a sent message", () => {
    const first = citationFor("m1", MESSAGE, "wool");
    const second = citationFor("m2", "Price: *$40*", "*$40*");
    const message = `Make ${serializeChatCitation(first)} cotton and drop ${serializeChatCitation(second)}.`;
    expect(collectChatCitations(message).map((match) => match.citation)).toEqual([first, second]);
  });
});

describe("citationPreview", () => {
  it("collapses whitespace and truncates", () => {
    expect(citationPreview({ text: "The\n jacket  is wool.", start: 0, end: 1, prefix: "", suffix: "" }, 10)).toBe(
      "The jacket…",
    );
  });
});
