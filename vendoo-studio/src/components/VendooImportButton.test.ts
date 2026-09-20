import { describe, expect, it } from "vitest";
import { importSummary, progressLabel } from "./VendooImportButton";
import type { VendooBulkImport } from "../api/types";

function run(overrides: Partial<VendooBulkImport> = {}): VendooBulkImport {
  return {
    running: false,
    total: 0,
    processed: 0,
    imported: 0,
    updated: 0,
    skipped: 0,
    failed: 0,
    photos: 0,
    current_title: "",
    started_at: "",
    finished_at: "",
    cancelled: false,
    error: "",
    failures: [],
    ...overrides,
  };
}

describe("importSummary", () => {
  it("reports only the outcomes that happened", () => {
    expect(importSummary(run({ imported: 12, skipped: 3 }))).toBe("12 new, 3 unchanged");
  });

  it("names failures alongside the rest", () => {
    expect(importSummary(run({ imported: 1, updated: 2, skipped: 3, failed: 4 }))).toBe(
      "1 new, 2 updated, 3 unchanged, 4 failed",
    );
  });

  it("counts the photos that came down with them", () => {
    expect(importSummary(run({ imported: 12, photos: 96 }))).toBe("12 new · 96 photos");
  });

  it("says so when a run found nothing to do", () => {
    expect(importSummary(run())).toBe("Nothing to import");
  });
});

describe("progressLabel", () => {
  it("counts against the inventory total", () => {
    expect(progressLabel(run({ running: true, total: 1119, processed: 40 }))).toBe(
      "Importing 40 of 1119",
    );
  });

  it("never reports more done than the total", () => {
    expect(progressLabel(run({ running: true, total: 10, processed: 12 }))).toBe(
      "Importing 10 of 10",
    );
  });

  it("falls back to a plain count before the total is known", () => {
    expect(progressLabel(run({ running: true, processed: 7 }))).toBe("Importing 7…");
  });

  it("shows photos as they arrive", () => {
    expect(progressLabel(run({ running: true, total: 100, processed: 8, photos: 64 }))).toBe(
      "Importing 8 of 100 · 64 photos",
    );
  });
});
