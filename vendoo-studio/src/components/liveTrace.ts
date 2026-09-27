/** What a running generate or chat reply has done so far, in stream order.
 *
 * T3 Code shows a turn's work inline in the transcript as it happens. The
 * stream carries the pieces: `status` starts a phase, `step` is one finished
 * action inside it (a web search), `thinking` is reasoning text, and `posted`
 * names a chat message (the evidence or comps card) the run just saved, so the
 * card shows up where it happened instead of at the end.
 */
export type LiveTraceEntry =
  | { kind: "phase"; text: string }
  | { kind: "step"; text: string }
  | { kind: "thought"; text: string }
  | { kind: "posted"; id: string };

/** The status the server sends when the model starts writing the listing. */
const WRITING_STATUS = "thinking";
const WRITING_PHASE = "Writing the listing…";

function lastPhaseText(trace: LiveTraceEntry[]): string | null {
  for (let index = trace.length - 1; index >= 0; index -= 1) {
    const entry = trace[index];
    if (entry.kind === "phase") return entry.text;
  }
  return null;
}

/** Fold one SSE data line into the trace. Returns the same array when nothing changed.
 *
 * `continued` is true for the second and later data lines of one event, which
 * the server uses for multi-line text.
 */
export function appendLiveTrace(
  trace: LiveTraceEntry[],
  event: string,
  text: string,
  continued = false,
): LiveTraceEntry[] {
  const last = trace[trace.length - 1];
  if (event === "thinking") {
    if (!text) return trace;
    if (last?.kind === "thought") {
      return [...trace.slice(0, -1), { kind: "thought", text: last.text + text }];
    }
    return [...trace, { kind: "thought", text }];
  }
  if (event === "status") {
    if (continued && last?.kind === "phase") {
      return [...trace.slice(0, -1), { kind: "phase", text: last.text + text }];
    }
    const phase = (text.trim() === WRITING_STATUS ? WRITING_PHASE : text).trim();
    // Keepalive pulses resend the current status every few seconds.
    if (!phase || lastPhaseText(trace) === phase) return trace;
    return [...trace, { kind: "phase", text: phase }];
  }
  if (event === "step") {
    const step = text.trim();
    return step ? [...trace, { kind: "step", text: step }] : trace;
  }
  if (event === "posted") {
    const id = text.trim();
    if (!id || trace.some((entry) => entry.kind === "posted" && entry.id === id)) return trace;
    return [...trace, { kind: "posted", id }];
  }
  return trace;
}

/** Index of the phase still running: the newest one, while the run is live. */
export function currentPhaseIndex(trace: LiveTraceEntry[], live: boolean): number {
  if (!live) return -1;
  for (let index = trace.length - 1; index >= 0; index -= 1) {
    if (trace[index].kind === "phase") return index;
  }
  return -1;
}

/** A finished phase reads as done: "Analyzing photos…" becomes "Analyzing photos". */
export function settledPhaseText(text: string): string {
  return text.replace(/\s*(?:…|\.\.\.)\s*$/, "");
}

/** One-line preview of a thought for its collapsed header: the newest line, markdown stripped. */
export function thoughtPreview(text: string): string {
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  const line = lines[lines.length - 1] || "";
  return line
    .replace(/^#{1,6}\s+/, "")
    .replace(/^(?:[-*+]|\d+\.)\s+(?:\[[ xX]\]\s+)?/, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}
