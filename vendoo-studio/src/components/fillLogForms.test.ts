import { describe, expect, it } from "vitest";
import type { FillLogEntry, FillLogReport } from "../api/types";
import {
  askChatGapsPrompt,
  emptyFieldsPrompt,
  hiddenKeySet,
  leftoverEntries,
  liveStatusClass,
  liveStatusForMarketplace,
  marketplaceLabel,
  mergeDraftItem,
  statusFromListingStatus,
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

  it("reads notListed from the Vendoo API status object", () => {
    expect(statusFromListingStatus({ notListed: true })).toBe("NOT LISTED");
    expect(statusFromListingStatus({ listed: true })).toBe("LISTED");
    expect(statusFromListingStatus({ listed: false })).toBe("NOT LISTED");
    expect(statusFromListingStatus({ sold: true })).toBe("SOLD");
    expect(liveStatusForMarketplace("ebay", {
      listings: { ebay: { status: { notListed: true } } },
    })).toBe("NOT LISTED");
    expect(liveStatusForMarketplace("depop", {
      listings: { depop: { status: { listed: true } } },
    })).toBe("LISTED");
  });

  it("keys hidden fields by marketplace and field", () => {
    const keys = hiddenKeySet({
      always: [{ marketplace: "ebay", field: "brand", label: "Brand" }],
      listing: [{ marketplace: "depop", field: "style", label: "Style" }],
    });
    expect([...keys]).toEqual(["ebay:brand", "depop:style"]);
  });
});

const DROPDOWNS = {
  depop: { material: ["Cotton", "Silk", "Viscose"] },
};

function depopForm() {
  return [{
    id: "depop",
    label: "Depop",
    fields: [{ key: "material", label: "Material", value: "", missing: true }],
    filled: 0,
    missing: 1,
    notApplicable: 0,
  }];
}

describe("ask-chat prompts", () => {
  it("lists the field's dropdown values so chat cannot invent one", () => {
    const prompt = emptyFieldsPrompt(depopForm(), false, { title: "Dress" }, DROPDOWNS);
    expect(prompt).toContain("Options (use only these, verbatim): Cotton | Silk | Viscose");
    expect(prompt).toContain("copied from that list verbatim");
  });

  it("tells chat to clear a field when nothing on the list fits", () => {
    const prompt = askChatGapsPrompt(depopForm(), false, { title: "Dress" }, [], DROPDOWNS);
    expect(prompt).toContain("Options (use only these, verbatim): Cotton | Silk | Viscose");
    expect(prompt).toContain('send that field with an empty value');
  });

  it("leaves fields with no known dropdown unannotated", () => {
    const prompt = emptyFieldsPrompt(depopForm(), false, { title: "Dress" }, { depop: {} });
    expect(prompt).not.toContain("Options (use only these");
  });
});
