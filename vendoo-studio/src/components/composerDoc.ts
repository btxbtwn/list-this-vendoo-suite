/**
 * Document model for the composer, following T3 Code's rich-text composer: the
 * stored prompt stays markdown — a cited quote is its canonical link — while
 * the editor holds text plus inline atom chips. This module translates both
 * ways and is DOM-free so it can be tested without a browser.
 */
import { collectChatCitations, serializeChatCitation, type ChatCitation } from "./chatCitations";

export const CITATION_NODE = "composer-citation";

export interface ComposerNode {
  type: string;
  text?: string;
  attrs?: Record<string, unknown>;
  content?: ComposerNode[];
}

/** Splits one line into its text runs and the citations sitting between them. */
function lineContent(line: string): ComposerNode[] {
  const content: ComposerNode[] = [];
  let cursor = 0;
  for (const match of collectChatCitations(line)) {
    if (match.start > cursor) content.push({ type: "text", text: line.slice(cursor, match.start) });
    content.push({
      type: CITATION_NODE,
      attrs: { citation: match.citation, source: match.source },
    });
    cursor = match.end;
  }
  if (cursor < line.length) content.push({ type: "text", text: line.slice(cursor) });
  return content;
}

/** The prompt's lines become paragraphs, its citation links become chips. */
export function promptToDoc(prompt: string): ComposerNode {
  const lines = prompt.split("\n");
  return {
    type: "doc",
    content: lines.map((line) => {
      const content = lineContent(line);
      return content.length ? { type: "paragraph", content } : { type: "paragraph" };
    }),
  };
}

function inlineText(node: ComposerNode): string {
  if (node.type === "text") return node.text ?? "";
  if (node.type === "hardBreak") return "\n";
  if (node.type !== CITATION_NODE) return "";
  const source = node.attrs?.source;
  if (typeof source === "string" && source) return source;
  const citation = node.attrs?.citation;
  return citation ? serializeChatCitation(citation as ChatCitation) : "";
}

/** The editor document back to the prompt that gets sent and stored. */
export function docToPrompt(doc: ComposerNode): string {
  return (doc.content ?? [])
    .map((block) => (block.content ?? []).map(inlineText).join(""))
    .join("\n");
}

/** A chip the editor can insert at the caret. */
export function citationNode(citation: ChatCitation): ComposerNode {
  return {
    type: CITATION_NODE,
    attrs: { citation, source: serializeChatCitation(citation) },
  };
}
