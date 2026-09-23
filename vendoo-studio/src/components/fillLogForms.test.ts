import { describe, expect, it } from "vitest";
import type { FillLogEntry, FillLogReport } from "../api/types";
import {
  askChatGapsPrompt,
  askChatTargetCount,
  emptyFieldsPrompt,
  filterForms,
  fieldsNeedingListingValues,
  hiddenKeySet,
  isAccountManagedField,
  leftoverEntries,
  listingValueForField,
  liveStatusClass,
  liveStatusForMarketplace,
  marketplaceLabel,
  mergeDraftItem,
  sourceFormsForJob,
  statusFromListingStatus,
  withoutHiddenFields,
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

  it("omits Vendoo system controls", () => {
    const forms = [{
      id: "depop",
      label: "Depop",
      fields: [
        { key: "geoLat", label: "Geo Lat", value: "", missing: true },
        { key: "priceCurrency", label: "Price Currency", value: "", missing: true },
        { key: "material", label: "Material", value: "", missing: true },
      ],
      filled: 0,
      missing: 3,
      notApplicable: 0,
    }];
    const prompt = emptyFieldsPrompt(forms, true, { title: "Shirt" });
    expect(prompt).not.toContain("Geo Lat");
    expect(prompt).not.toContain("Price Currency");
    expect(prompt).toContain("Field: Material");
  });

  it("counts empty listing fields and fill failures without double-counting", () => {
    expect(askChatTargetCount(depopForm(), { title: "Dress" }, [])).toBe(1);
    expect(askChatTargetCount(depopForm(), { title: "Dress" }, [
      entry({ marketplace: "depop", field: "Material", status: "failed" }),
      entry({ id: "2", marketplace: "ebay", field: "Brand", status: "invalid" }),
    ])).toBe(2);
    expect(askChatTargetCount(depopForm(), {
      title: "Dress",
      depop_specifics: { material: "Cotton" },
    }, [
      entry({ marketplace: "depop", field: "Material", status: "failed" }),
    ])).toBe(1);
  });

  it("after a Vendoo draft, Ask chat only targets blanks on the form that lack listing JSON", () => {
    const forms = [{
      id: "depop",
      label: "Depop",
      fields: [
        { key: "material", label: "Material", value: "", missing: true },
        { key: "brand", label: "Brand", value: "Nike", missing: false },
        { key: "style", label: "Style", value: "", missing: true },
        { key: "colour", label: "Colour", value: "", missing: true, listingOnly: true },
      ],
      filled: 1,
      missing: 2,
      notApplicable: 0,
    }];
    const listing = {
      title: "Dress",
      depop_specifics: { style: "Streetwear" },
    };
    // Material: empty on Vendoo + empty in JSON → Ask chat
    // Brand: filled on Vendoo, empty in JSON → not Ask chat (not a Vendoo blank)
    // Style: empty on Vendoo, has JSON → ready to Update, not Ask chat
    // Colour: listingOnly overlay → not a confirmed Vendoo form blank
    expect(fieldsNeedingListingValues(forms, listing, true).map((row) => row.field.label))
      .toEqual(["Material"]);
    expect(askChatTargetCount(forms, listing, [], true)).toBe(1);
    expect(askChatGapsPrompt(forms, true, listing, [])).toContain("empty on Vendoo and in listing JSON");
    expect(askChatGapsPrompt(forms, true, listing, [])).toContain("Field: Material");
    expect(askChatGapsPrompt(forms, true, listing, [])).not.toContain("Field: Brand");
    expect(askChatGapsPrompt(forms, true, listing, [])).not.toContain("Field: Colour");
  });

  it("keeps account policies and eBay shipping out of Ask chat", () => {
    const forms = [{
      id: "ebay",
      label: "eBay",
      fields: [
        { key: "shippingPolicyId", label: "Shipping Policy Id", value: "", missing: true },
        { key: "returnsPolicyId", label: "Returns Policy Id", value: "", missing: true },
        { key: "paypalEmail", label: "Paypal Email", value: "", missing: true },
        { key: "primaryStoreCategory", label: "Primary Store Category", value: "", missing: true },
        { key: "shippingService", label: "Shipping Service", value: "", missing: true },
        { key: "brand", label: "Brand", value: "", missing: true },
      ],
      filled: 0,
      missing: 6,
      notApplicable: 0,
    }];
    const needing = fieldsNeedingListingValues(forms, { title: "Tee" });
    expect(needing.map((row) => row.field.label)).toEqual(["Brand"]);
    expect(isAccountManagedField("ebay", "Shipping Policy Id")).toBe(true);
    expect(isAccountManagedField("ebay", "Shipping Service")).toBe(true);
    expect(isAccountManagedField("mercari", "Delivery Method")).toBe(false);
    expect(isAccountManagedField("depop", "Parcel Size")).toBe(false);
  });
});

describe("Fields filters", () => {
  const taxonomyId = ["628097", "90395"].join("");
  const forms = [{
    id: "ebay",
    label: "eBay",
    fields: [
      { key: "pricingFormat", label: "Pricing Format", value: "Fixed Price", missing: false },
      { key: "geoLat", label: "Geo Lat", value: "", missing: true },
      { key: `${taxonomyId}_scale`, label: `${taxonomyId} Scale`, value: "", missing: true },
    ],
    filled: 1,
    missing: 2,
    notApplicable: 0,
  }];

  it("shows listing-empty fields even when Vendoo already has a value", () => {
    const filtered = filterForms(forms, "", true, { title: "Shirt" });
    expect(filtered[0]?.fields.map((field) => field.label)).toEqual(["Pricing Format"]);
  });

  it("removes system and raw numeric-id controls from the panel", () => {
    const visible = withoutHiddenFields(forms, { always: [], listing: [] });
    expect(visible[0]?.fields.map((field) => field.label)).toEqual(["Pricing Format"]);
  });

  it("resolves taxonomy IDs through the listing category schema", () => {
    const { sourceForms } = sourceFormsForJob({
      listings: {
        etsy: {
          categorySpecifics: {
            [`449_${taxonomyId}`]: { scale: "Men's" },
          },
        },
      },
    }, undefined, {}, ["etsy"], [{
      marketplace: "etsy",
      category_id: "449",
      known: true,
      fields: [{
        key: taxonomyId,
        label: "Size",
        value: "",
        required: false,
        multi: false,
        selection_only: false,
        options: [],
      }],
    }]);
    const etsy = sourceForms.find((form) => form.id === "etsy");
    expect(etsy?.fields.some((field) => field.label === "Size")).toBe(true);
    expect(etsy?.fields.some((field) => field.label.includes(taxonomyId))).toBe(false);
  });

  it("reads separate Vendoo dimensions from the listing package default", () => {
    const listing = { package_dimensions_in: "13x10x3" };
    expect(listingValueForField(listing, "general", {
      key: "length", label: "Length", value: "", missing: true,
    })).toBe("13");
    expect(listingValueForField(listing, "general", {
      key: "width", label: "Width", value: "", missing: true,
    })).toBe("10");
    expect(listingValueForField(listing, "general", {
      key: "height", label: "Height", value: "", missing: true,
    })).toBe("3");
    expect(listingValueForField(listing, "ebay", {
      key: "length", label: "Length", value: "", missing: true,
    })).toBe("13");
  });
});
