import { describe, expect, it, vi } from "vitest";
import { coalesceSseEvents, type SseParts } from "./sseCoalesce";

const parts = (content: string): SseParts => ({ content, thinking: "", status: "" });

describe("coalesceSseEvents", () => {
  it("paints the first event immediately", () => {
    const onEvent = vi.fn();
    const batch = coalesceSseEvents(onEvent, 50);
    batch.push("message", parts("H"));
    expect(onEvent).toHaveBeenCalledTimes(1);
  });

  it("collapses a burst into one call per type", async () => {
    vi.useFakeTimers();
    const onEvent = vi.fn();
    const batch = coalesceSseEvents(onEvent, 50);
    const live = parts("");
    batch.push("message", live); // leading edge
    onEvent.mockClear();
    for (const ch of "ello world") {
      live.content += ch;
      batch.push("message", live);
    }
    expect(onEvent).not.toHaveBeenCalled();
    vi.advanceTimersByTime(50);
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith("message", expect.objectContaining({ content: "ello world" }));
    vi.useRealTimers();
  });

  it("keeps one call per distinct event type, in arrival order", () => {
    vi.useFakeTimers();
    const onEvent = vi.fn();
    const batch = coalesceSseEvents(onEvent, 50);
    const live: SseParts = { content: "", thinking: "", status: "" };
    batch.push("thinking", live); // leading edge
    onEvent.mockClear();
    live.thinking = "hmm";
    batch.push("thinking", live);
    live.status = "Saving…";
    batch.push("status", live);
    live.content = "done";
    batch.push("message", live);
    vi.advanceTimersByTime(50);
    expect(onEvent.mock.calls.map((c) => c[0])).toEqual(["thinking", "status", "message"]);
    vi.useRealTimers();
  });

  it("flush() emits the pending batch synchronously", () => {
    vi.useFakeTimers();
    const onEvent = vi.fn();
    const batch = coalesceSseEvents(onEvent, 50);
    const live = parts("a");
    batch.push("message", live);
    onEvent.mockClear();
    live.content = "ab";
    batch.push("message", live);
    batch.flush();
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith("message", expect.objectContaining({ content: "ab" }));
    // Nothing is left to fire afterwards.
    vi.advanceTimersByTime(100);
    expect(onEvent).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("flush() with nothing pending is a no-op", () => {
    const onEvent = vi.fn();
    coalesceSseEvents(onEvent, 50).flush();
    expect(onEvent).not.toHaveBeenCalled();
  });
});
