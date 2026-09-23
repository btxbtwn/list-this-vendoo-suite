import { describe, expect, it } from "vitest";
import {
  chatCitationId,
  createChatCitationSelector,
  serializeChatCitation,
  withChatCitationComment,
  type ChatCitation,
} from "./chatCitations";
import { CITATION_NODE, citationNode, docToPrompt, promptToDoc } from "./composerDoc";

const MESSAGE = "The jacket is wool. The lining is silk.";

function citationFor(quote: string): ChatCitation {
  const start = MESSAGE.indexOf(quote);
  const selector = createChatCitationSelector(MESSAGE, start, start + quote.length)!;
  return { id: chatCitationId("m1", selector), messageId: "m1", ...selector };
}

const WOOL = citationFor("wool");
const SILK = withChatCitationComment(citationFor("silk"), "check the label");

describe("promptToDoc", () => {
  it("keeps a quote inline where the seller typed it", () => {
    const prompt = `Make ${serializeChatCitation(WOOL)} cotton.`;
    expect(promptToDoc(prompt)).toEqual({
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "Make " },
            { type: CITATION_NODE, attrs: { citation: WOOL, source: serializeChatCitation(WOOL) } },
            { type: "text", text: " cotton." },
          ],
        },
      ],
    });
  });

  it("gives each line its own paragraph, including empty ones", () => {
    const doc = promptToDoc("first\n\nthird");
    expect(doc.content).toHaveLength(3);
    expect(doc.content?.[1]).toEqual({ type: "paragraph" });
  });
});

describe("docToPrompt", () => {
  it("round-trips a prompt with quotes in it", () => {
    const prompt = `Make ${serializeChatCitation(WOOL)} cotton\nand ${serializeChatCitation(SILK)} too.`;
    expect(docToPrompt(promptToDoc(prompt))).toBe(prompt);
  });

  it("writes a quote inserted at the caret as its link", () => {
    const doc = {
      type: "doc",
      content: [{ type: "paragraph", content: [citationNode(SILK), { type: "text", text: " ok" }] }],
    };
    expect(docToPrompt(doc)).toBe(`${serializeChatCitation(SILK)} ok`);
  });

  it("serializes a comment edited on a chip from its citation", () => {
    const commented = withChatCitationComment(WOOL, "use cotton");
    const doc = {
      type: "doc",
      content: [{ type: "paragraph", content: [{ type: CITATION_NODE, attrs: { citation: commented, source: serializeChatCitation(commented) } }] }],
    };
    expect(docToPrompt(doc)).toContain("comment=use+cotton");
  });

  it("turns a hard break into a newline", () => {
    const doc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [{ type: "text", text: "one" }, { type: "hardBreak" }, { type: "text", text: "two" }],
        },
      ],
    };
    expect(docToPrompt(doc)).toBe("one\ntwo");
  });
});
