export type ThinkingTodo = {
  text: string;
  done: boolean;
  current: boolean;
};

const BOLD_STEP = /\*\*([^*]+)\*\*/g;
const TASK_LINE = /^(?:[-*+]|\d+[.)])\s+\[([ xX])\]\s+(.+)$/;
const BULLET_LINE = /^(?:[-*+]|•|\d+[.)])\s+(.+)$/;
const HEADING_LINE = /^#{1,6}\s+(.+)$/;

function cleanStep(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function toTodos(items: string[], finished: boolean): ThinkingTodo[] {
  return items.filter(Boolean).map((text, index, all) => {
    const current = !finished && index === all.length - 1;
    return { text, done: finished || index < all.length - 1, current };
  });
}

function looksLikeStep(text: string, partial = false): boolean {
  if (text.length < (partial ? 3 : 8) || text.length > 100) return false;
  if ((text.match(/[.!?]/g) || []).length > 1) return false;
  return text.split(" ").length <= 14;
}

function extractBoldSteps(text: string): string[] {
  const items: string[] = [];
  const closed = new RegExp(BOLD_STEP.source, "g");
  let match: RegExpExecArray | null;
  let lastIndex = 0;
  while ((match = closed.exec(text))) {
    const step = cleanStep(match[1]);
    if (step && looksLikeStep(step)) items.push(step);
    lastIndex = closed.lastIndex;
  }
  const unclosed = text.slice(lastIndex).match(/^\s*\*\*([^*]+)$/);
  if (unclosed) {
    const step = cleanStep(unclosed[1]);
    if (step && looksLikeStep(step, true)) items.push(step);
  }
  return items;
}

function lineSteps(
  lines: string[],
  pattern: RegExp,
  valueIndex: number,
): string[] | null {
  if (!lines.length) return null;
  const matches = lines.map((line) => line.match(pattern));
  if (matches.some((match) => !match)) return null;
  return matches.map((match) => cleanStep(match![valueIndex]));
}

function taskTodos(lines: string[], finished: boolean): ThinkingTodo[] | null {
  if (!lines.length) return null;
  const matches = lines.map((line) => line.match(TASK_LINE));
  if (matches.some((match) => !match)) return null;
  const firstOpen = matches.findIndex((match) => match![1].toLowerCase() !== "x");
  return matches.map((match, index) => {
    const markedDone = match![1].toLowerCase() === "x";
    const current = !finished && (firstOpen === -1 ? index === matches.length - 1 : index === firstOpen);
    return {
      text: cleanStep(match![2]),
      done: finished || markedDone,
      current,
    };
  });
}

export function parseThinkingTodos(raw: string, finished = false): ThinkingTodo[] {
  const text = raw.replace(/\r\n/g, "\n").trim();
  if (!text) return [];

  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  const fromTasks = taskTodos(lines, finished);
  if (fromTasks) return fromTasks;

  const bold = extractBoldSteps(text);
  if (bold.length) return toTodos(bold, finished);

  const headings = lineSteps(lines, HEADING_LINE, 1);
  if (headings && headings.length) return toTodos(headings, finished);

  const bullets = lineSteps(lines, BULLET_LINE, 1);
  if (bullets && bullets.length) return toTodos(bullets, finished);

  return toTodos([text], finished);
}
