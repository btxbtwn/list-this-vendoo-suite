import { describe, expect, it } from "vitest";
import {
  citationPreview,
  createChatCitationSelector,
  findChatCitationText,
  formatCitedMessage,
  rawTextOffset,
} from "./chatCitations";

const MESSAGE = "The jacket is wool.\nThe lining is silk.";

function selectorFor(text: string, quote: string, occurrence = 0) {
  let start = -1;
  for (let i = 0; i <= occurrence; i += 1) start = text.indexOf(quote, start + 1);
  const selector = createChatCitationSelector(text, start, start + quote.length);
  if (!selector) throw new Error("expected a selector");
  return selector;
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

describe("formatCitedMessage", () => {
  it("returns the typed text when nothing is cited", () => {
    expect(formatCitedMessage([], "  Change the title  ")).toBe("Change the title");
  });

  it("quotes each citation above the message and escapes its markdown", () => {
    const message = formatCitedMessage(
      [selectorFor(MESSAGE, "The lining is silk."), selectorFor("Price: *$40*", "*$40*")],
      "Fix both.",
    );
    expect(message).toBe(
      "> Quoted from your earlier reply:\n> The lining is silk\\.\n\n" +
        "> Quoted from your earlier reply:\n> \\*$40\\*\n\n" +
        "Fix both.",
    );
  });

  it("sends the quote alone when the composer is empty", () => {
    expect(formatCitedMessage([selectorFor(MESSAGE, "wool")], "")).toBe(
      "> Quoted from your earlier reply:\n> wool",
    );
  });

  it("keeps a multi-line quote inside one block", () => {
    expect(formatCitedMessage([selectorFor(MESSAGE, MESSAGE)], "")).toBe(
      "> Quoted from your earlier reply:\n> The jacket is wool\\.\n> The lining is silk\\.",
    );
  });
});

describe("citationPreview", () => {
  it("collapses whitespace and truncates", () => {
    expect(citationPreview({ text: "The\n jacket  is wool.", start: 0, end: 1, prefix: "", suffix: "" }, 10)).toBe(
      "The jacket…",
    );
  });
});
