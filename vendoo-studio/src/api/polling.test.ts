import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activityPollMs,
  BUSY_POLL_MS,
  fillLogPollMs,
  hasOpenJob,
  IDLE_POLL_MS,
  jobsPollMs,
  LIVE_POLL_MS,
  pollMs,
} from "./polling";

function focusWindow(focused: boolean) {
  vi.stubGlobal("document", { hasFocus: () => focused });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("hasOpenJob", () => {
  it("is true only while a send is still moving", () => {
    expect(hasOpenJob(undefined)).toBe(false);
    expect(hasOpenJob([{ status: "completed" }, { status: "failed" }, { status: "cancelled" }])).toBe(false);
    expect(hasOpenJob([{ status: "completed" }, { status: "dispatched" }])).toBe(true);
    expect(hasOpenJob([{ status: "awaiting_extension" }])).toBe(true);
  });
});

describe("pollMs", () => {
  it("keeps the asked rate while Studio has focus", () => {
    focusWindow(true);
    expect(pollMs(LIVE_POLL_MS)).toBe(LIVE_POLL_MS);
  });

  it("never polls faster than the idle pass behind another window", () => {
    focusWindow(false);
    expect(pollMs(LIVE_POLL_MS)).toBe(IDLE_POLL_MS);
    expect(pollMs(15000)).toBe(15000);
  });
});

describe("query poll rules", () => {
  it("polls fast only while something is running", () => {
    focusWindow(true);
    expect(jobsPollMs([{ status: "completed" }])).toBe(IDLE_POLL_MS);
    expect(jobsPollMs([{ status: "queued" }])).toBe(BUSY_POLL_MS);
    expect(fillLogPollMs("completed")).toBe(IDLE_POLL_MS);
    expect(fillLogPollMs("dispatched")).toBe(BUSY_POLL_MS);
    expect(activityPollMs(false)).toBe(IDLE_POLL_MS);
    expect(activityPollMs(true)).toBe(LIVE_POLL_MS);
  });
});
