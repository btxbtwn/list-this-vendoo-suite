import { describe, expect, it } from "vitest";
import { formatDuration, formatWorkingTimer } from "./workingTimerFormat";

describe("formatDuration", () => {
  it("formats sub-second as ms", () => {
    expect(formatDuration(1)).toBe("1ms");
    expect(formatDuration(450)).toBe("450ms");
  });

  it("formats under 10s with one tenth", () => {
    expect(formatDuration(2_100)).toBe("2.1s");
    expect(formatDuration(9_950)).toBe("10s");
  });

  it("formats whole seconds under a minute", () => {
    expect(formatDuration(12_400)).toBe("12s");
  });

  it("formats minutes and hours", () => {
    expect(formatDuration(65_000)).toBe("1m 5s");
    expect(formatDuration(3_600_000)).toBe("1h");
  });
});

describe("formatWorkingTimer", () => {
  it("floors to whole seconds while under a minute", () => {
    expect(formatWorkingTimer(0)).toBe("0s");
    expect(formatWorkingTimer(999)).toBe("0s");
    expect(formatWorkingTimer(1_000)).toBe("1s");
    expect(formatWorkingTimer(12_900)).toBe("12s");
  });

  it("uses formatDuration once past a minute", () => {
    expect(formatWorkingTimer(65_000)).toBe("1m 5s");
  });
});
