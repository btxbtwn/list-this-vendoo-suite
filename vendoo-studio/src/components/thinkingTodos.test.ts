import { describe, expect, it } from "vitest";
import { parseThinkingTodos, splitThinkingProse } from "./thinkingTodos";

describe("parseThinkingTodos", () => {
  it("returns nothing for empty reasoning", () => {
    expect(parseThinkingTodos("  \n ")).toEqual([]);
  });

  it("uses markdown task state and marks the first open task current", () => {
    const todos = parseThinkingTodos("- [x] Read photos\n- [ ] Pick category\n- [ ] Write title");
    expect(todos.map(({ text, done, current }) => ({ text, done, current }))).toEqual([
      { text: "Read photos", done: true, current: false },
      { text: "Pick category", done: false, current: true },
      { text: "Write title", done: false, current: false },
    ]);
  });

  it("treats bold headings as steps with the last one in progress", () => {
    const todos = parseThinkingTodos("**Reading the label** some notes **Checking sold comps** more");
    expect(todos.map((todo) => todo.text)).toEqual(["Reading the label", "Checking sold comps"]);
    expect(todos.map((todo) => todo.current)).toEqual([false, true]);
  });

  it("marks every step done once finished", () => {
    const todos = parseThinkingTodos("1. Measure the jacket\n2. Price it", true);
    expect(todos.every((todo) => todo.done && !todo.current)).toBe(true);
  });

  it("falls back to prose chunks for freeform reasoning", () => {
    const todos = parseThinkingTodos("The tag says medium. The fabric looks like cotton twill with a faded wash.");
    expect(todos.length).toBeGreaterThan(0);
    expect(todos.every((todo) => todo.prose)).toBe(true);
  });
});

describe("splitThinkingProse", () => {
  it("keeps paragraphs separate", () => {
    expect(splitThinkingProse("First idea.\n\nSecond idea.")).toEqual(["First idea.", "Second idea."]);
  });
});
