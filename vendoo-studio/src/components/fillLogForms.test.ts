import { describe, expect, it } from "vitest";
import type { FillLogEntry, FillLogReport } from "../api/types";
import {
  hiddenKeySet,
  leftoverEntries,
  liveStatusClass,
  marketplaceLabel,
  mergeDraftItem,
} from "./fillLogForms";

function entry(overrides: Partial<FillLogEntry>): FillLogEntry {
  return {
    id: "1",
    step: "fill",
    marketplace: "ebay",
    field: "Brand",
    status: "failed",
    reason: "",
    selector: "",
    value_preview: "",
    ...overrides,
  };
}

describe("leftoverEntries", () => {
  it("keeps retryable entries, drops successes and account settings, and orders by status", () => {
    const report: FillLogReport = {
      job_id: "job",
      summary: {},
      log_path: null,
      by_marketplace: {
        ebay: {
          summary: {},
          entries: [
            entry({ id: "filled", status: "filled" }),
            entry({ id: "already", status: "uncertain", reason: "Already set" }),
            entry({ id: "offer", status: "failed", field: "Allow Best Offer" }),
            entry({ id: "neckline", status: "not_found", field: "Neckline" }),
            entry({ id: "brand", status: "invalid", field: "Brand" }),
          ],
        },
        depop: { summary: {}, entries: [entry({ id: "parcel", marketplace: "depop", status: "failed", field: "Parcel size" })] },
      },
    };
    expect(leftoverEntries(report).map((row) => row.id)).toEqual(["brand", "parcel", "neckline"]);
  });
});

describe("mergeDraftItem", () => {
  it("returns undefined when Vendoo returned nothing", () => {
    expect(mergeDraftItem(undefined)).toBeUndefined();
    expect(mergeDraftItem({ item: {}, form: {} })).toBeUndefined();
  });

  it("deep-merges scraped form details under API item details", () => {
    const merged = mergeDraftItem({
      form: {
        generalDetails: { title: "Form title", categorySpecifics: { neckline: "" } },
        images: ["form.jpg"],
        statuses: { ebay: "draft" },
      },
      item: { generalDetails: { title: "API title" } },
    });
    expect(merged?.generalDetails).toEqual({ title: "API title", categorySpecifics: { neckline: "" } });
    expect(merged?.images).toEqual(["form.jpg"]);
    expect(merged?.statuses).toEqual({ ebay: "draft" });
  });
});

describe("labels", () => {
  it("names known and unknown marketplaces", () => {
    expect(marketplaceLabel("ebay")).toBe("eBay");
    expect(marketplaceLabel("grailed")).toBe("Grailed");
    expect(marketplaceLabel("vinted")).toBe("Vinted");
  });

  it("maps live Vendoo statuses to chip classes", () => {
    expect(liveStatusClass("Listed")).toBe("is-listed");
    expect(liveStatusClass("NOT LISTED")).toBe("is-not-listed");
    expect(liveStatusClass("failed")).toBe("is-failed");
    expect(liveStatusClass(undefined)).toBe("");
  });

  it("keys hidden fields by marketplace and field", () => {
    const keys = hiddenKeySet({
      always: [{ marketplace: "ebay", field: "brand", label: "Brand" }],
      listing: [{ marketplace: "depop", field: "style", label: "Style" }],
    });
    expect([...keys]).toEqual(["ebay:brand", "depop:style"]);
  });
});
