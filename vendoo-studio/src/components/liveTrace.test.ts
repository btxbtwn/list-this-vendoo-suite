import { describe, expect, it } from "vitest";
import {
  appendLiveTrace,
  currentPhaseIndex,
  settledPhaseText,
  thoughtPreview,
  type LiveTraceEntry,
} from "./liveTrace";

function fold(events: [string, string][]): LiveTraceEntry[] {
  return events.reduce<LiveTraceEntry[]>((trace, [event, text]) => appendLiveTrace(trace, event, text), []);
}

describe("appendLiveTrace", () => {
  it("records a generate run in stream order", () => {
    const trace = fold([
      ["status", "Analyzing photos…"],
      ["thinking", "**Reading the tag**"],
      ["thinking", "\n\nThe tag says Levi's."],
      ["posted", "m1"],
      ["status", "Identifying category and looking up comps…"],
      ["step", "Searched the web: levis 501 sold"],
      ["posted", "m2"],
      ["status", "thinking"],
    ]);
    expect(trace).toEqual([
      { kind: "phase", text: "Analyzing photos…" },
      { kind: "thought", text: "**Reading the tag**\n\nThe tag says Levi's." },
      { kind: "posted", id: "m1" },
      { kind: "phase", text: "Identifying category and looking up comps…" },
      { kind: "step", text: "Searched the web: levis 501 sold" },
      { kind: "posted", id: "m2" },
      { kind: "phase", text: "Writing the listing…" },
    ]);
  });

  it("ignores keepalive repeats of the current status, even after other entries", () => {
    const trace = fold([
      ["status", "Choosing marketplace categories…"],
      ["step", "Searched Brave: levis"],
      ["status", "Choosing marketplace categories…"],
    ]);
    expect(trace.filter((entry) => entry.kind === "phase")).toHaveLength(1);
  });

  it("starts a new thought after anything else lands", () => {
    const trace = fold([
      ["thinking", "first"],
      ["status", "Next…"],
      ["thinking", "second"],
    ]);
    expect(trace.filter((entry) => entry.kind === "thought")).toHaveLength(2);
  });

  it("keeps multi-line status text in one phase", () => {
    let trace = appendLiveTrace([], "status", "line one");
    trace = appendLiveTrace(trace, "status", "\nline two", true);
    expect(trace).toEqual([{ kind: "phase", text: "line one\nline two" }]);
  });

  it("returns the same array for events it does not track", () => {
    const trace: LiveTraceEntry[] = [];
    expect(appendLiveTrace(trace, "message", "hello")).toBe(trace);
    expect(appendLiveTrace(trace, "listing_updated", "1")).toBe(trace);
    expect(appendLiveTrace(trace, "thinking", "")).toBe(trace);
  });

  it("records each posted message once, since resumes replay the run", () => {
    expect(fold([["posted", "m1"], ["posted", "m1"]])).toEqual([{ kind: "posted", id: "m1" }]);
  });
});

describe("currentPhaseIndex", () => {
  it("is the newest phase while live, and none once finished", () => {
    const trace = fold([["status", "A…"], ["status", "B…"], ["step", "Searched"]]);
    expect(currentPhaseIndex(trace, true)).toBe(1);
    expect(currentPhaseIndex(trace, false)).toBe(-1);
  });
});

describe("settledPhaseText", () => {
  it("drops the trailing ellipsis", () => {
    expect(settledPhaseText("Analyzing photos…")).toBe("Analyzing photos");
    expect(settledPhaseText("Saving listing...")).toBe("Saving listing");
  });
});

describe("thoughtPreview", () => {
  it("shows the newest line without markdown", () => {
    expect(thoughtPreview("**Reading the tag**\n\n- [x] Checking the **size** tag\n")).toBe("Checking the size tag");
  });
});
