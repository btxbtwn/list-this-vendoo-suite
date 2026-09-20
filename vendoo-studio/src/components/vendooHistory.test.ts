import { describe, expect, it } from "vitest";
import { formatAge, historyRows } from "./vendooHistory";

const now = Date.parse("2026-09-20T00:00:00Z");

describe("formatAge", () => {
  it("names the age in the coarsest unit that still says something", () => {
    expect(formatAge("2026-09-20T00:00:00Z", now)).toBe("today");
    expect(formatAge("2026-09-19T00:00:00Z", now)).toBe("yesterday");
    expect(formatAge("2026-08-20T00:00:00Z", now)).toBe("31 days ago");
    expect(formatAge("2026-03-20T00:00:00Z", now)).toBe("6 months ago");
    expect(formatAge("2023-09-20T00:00:00Z", now)).toBe("3.0 years ago");
    expect(formatAge("", now)).toBe("");
    expect(formatAge("not a date", now)).toBe("");
  });
});

describe("historyRows", () => {
  it("tells the listing's story, newest first, marketplaces under their own date", () => {
    const rows = historyRows(
      {
        vendoo_created_at: "2026-01-01T00:00:00Z",
        vendoo_modified_at: "2026-09-01T00:00:00Z",
        vendoo_listed_at: "2026-05-02T00:00:00Z",
        vendoo_listed_dates: { poshmark: "2026-01-15T00:00:00Z", ebay: "2026-05-02T00:00:00Z" },
      },
      now,
    );
    expect(rows.map((row) => `${row.label} ${row.age}${row.nested ? " (nested)" : ""}`)).toEqual([
      "Listed 5 months ago",
      "eBay 5 months ago (nested)",
      "Poshmark 8 months ago (nested)",
      "Last modified 19 days ago",
      "Created 9 months ago",
    ]);
  });

  it("leaves out what Vendoo never stamped", () => {
    expect(historyRows({ vendoo_sold_at: "" }, now)).toEqual([]);
    expect(historyRows({ vendoo_created_at: "nonsense" }, now)).toEqual([]);
  });
});
