import { describe, expect, it } from "vitest";
import { stableStreamingText } from "./streamingText";

describe("stableStreamingText", () => {
  it("holds an unfinished paragraph", () => {
    expect(stableStreamingText("Still writing this paragraph")).toBe("");
  });

  it("reveals completed paragraphs and holds the active one", () => {
    expect(stableStreamingText("First paragraph.\n\nSecond para")).toBe("First paragraph.\n\n");
  });

  it("reveals tight list items one item behind", () => {
    expect(stableStreamingText("- First\n- Second\n- Thi")).toBe("- First\n- Second\n");
  });

  it("does not split at blank lines inside a code fence", () => {
    expect(stableStreamingText("```ts\nconst a = 1;\n\nconst b = 2;\n")).toBe("");
  });

  it("reveals a closed code fence", () => {
    const block = "```ts\nconst a = 1;\n```\n";
    expect(stableStreamingText(`${block}\nTail`)).toBe(`${block}\n`);
  });
});
