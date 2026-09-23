import { describe, expect, it } from "vitest";
import remarkParse from "remark-parse";
import { unified } from "unified";
import {
  createIncrementalMarkdownPlugin,
  shouldParseIncrementally,
} from "./markdownIncremental";

const DOCUMENT = [
  "Here is the fix.",
  "",
  "```json",
  '{"title": "Wool coat"}',
  "```",
  "",
  "Then a second paragraph.",
  "",
  "```sh",
  "npm test",
  "```",
  "",
  "Done.",
].join("\n");

function parseAll(text: string) {
  return unified().use(remarkParse).parse(text);
}

describe("createIncrementalMarkdownPlugin", () => {
  it("matches a full parse for every prefix of a streamed document", () => {
    // One plugin instance keeps the cache across renders, as the renderer does.
    const plugin = createIncrementalMarkdownPlugin();
    const processor = unified().use(remarkParse).use(plugin);
    for (let length = 1; length <= DOCUMENT.length; length += 1) {
      const prefix = DOCUMENT.slice(0, length);
      expect(processor.parse(prefix)).toEqual(parseAll(prefix));
    }
  });

  it("falls back to a full parse when the text carries definitions", () => {
    const withDefinition = "[ref]: https://example.com\n\n```js\nok\n```\n\nSee [it][ref].";
    const processor = unified().use(remarkParse).use(createIncrementalMarkdownPlugin());
    expect(processor.parse(withDefinition)).toEqual(parseAll(withDefinition));
  });
});

describe("shouldParseIncrementally", () => {
  it("only pays for the cache once a fence is open", () => {
    expect(shouldParseIncrementally("Still writing prose")).toBe(false);
    expect(shouldParseIncrementally("Here it is:\n\n```json\n{")).toBe(true);
    expect(shouldParseIncrementally("~~~\ncode\n")).toBe(true);
  });
});
