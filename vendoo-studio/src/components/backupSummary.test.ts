import { describe, expect, it } from "vitest";

import { backupSummary, formatBytes, formatWhen } from "./backupSummary";

const NOW = Date.parse("2026-09-20T12:00:00Z");

function snapshot(takenAt: string, sizeBytes = 16_000_000) {
  return {
    path: `/data/backups/${takenAt}.db`,
    name: `${takenAt}.db`,
    taken_at: takenAt,
    reason: "timer",
    size_bytes: sizeBytes,
    compressed: true,
  };
}

describe("formatBytes", () => {
  it("uses MB for a typical database", () => {
    expect(formatBytes(16_564_224)).toBe("15.8 MB");
  });

  it("uses GB once the backups folder gets large", () => {
    expect(formatBytes(2_400_000_000)).toBe("2.2 GB");
  });

  it("never reports a real file as 0 KB", () => {
    expect(formatBytes(120)).toBe("1 KB");
  });
});

describe("formatWhen", () => {
  it("reads as just now within the minute", () => {
    expect(formatWhen("2026-09-20T11:59:30Z", NOW)).toBe("just now");
  });

  it("counts minutes, then hours, then days", () => {
    expect(formatWhen("2026-09-20T11:15:00Z", NOW)).toBe("45 minutes ago");
    expect(formatWhen("2026-09-20T06:00:00Z", NOW)).toBe("6 hours ago");
    expect(formatWhen("2026-09-17T12:00:00Z", NOW)).toBe("3 days ago");
  });

  it("keeps singular units singular", () => {
    expect(formatWhen("2026-09-20T11:59:00Z", NOW)).toBe("1 minute ago");
    expect(formatWhen("2026-09-19T12:00:00Z", NOW)).toBe("1 day ago");
  });

  it("does not pretend to know about an unparseable date", () => {
    expect(formatWhen("not a date", NOW)).toBe("unknown");
  });
});

describe("backupSummary", () => {
  it("says it is still checking before the query resolves", () => {
    expect(backupSummary(undefined, NOW)).toBe("Checking…");
  });

  it("calls out an install that has never backed up", () => {
    expect(backupSummary({ snapshots: [], folder: null, latest: null }, NOW)).toBe("No backups yet");
  });

  it("summarises the newest snapshot and how many are kept", () => {
    const latest = snapshot("2026-09-20T06:00:00Z");
    expect(
      backupSummary(
        { snapshots: [latest, snapshot("2026-09-19T06:00:00Z")], folder: "/Volumes/Backup", latest },
        NOW,
      ),
    ).toBe("Last backup 6 hours ago · 15.3 MB · 2 kept");
  });
});
