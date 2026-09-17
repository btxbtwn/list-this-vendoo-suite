import { describe, expect, it } from "vitest";
import { cloneListing, getNestedValue, setNestedValue } from "./listingPaths";

describe("getNestedValue", () => {
  it("reads dotted paths through nested objects", () => {
    const listing = { ebay_specifics: { category_specifics: { neckline: "Crew Neck" } } };
    expect(getNestedValue(listing, "ebay_specifics.category_specifics.neckline")).toBe("Crew Neck");
  });

  it("returns undefined when a segment is missing or not an object", () => {
    expect(getNestedValue({ price: 45 }, "price.amount")).toBeUndefined();
    expect(getNestedValue({}, "ebay_specifics.size")).toBeUndefined();
    expect(getNestedValue(null, "title")).toBeUndefined();
  });
});

describe("setNestedValue", () => {
  it("creates intermediate objects and replaces non-object segments", () => {
    const listing: Record<string, unknown> = { depop_specifics: "corrupt" };
    setNestedValue(listing, "depop_specifics.parcelSize", "Small");
    setNestedValue(listing, "etsy_specifics.category_specifics.occasion", "Birthday");
    expect(listing).toEqual({
      depop_specifics: { parcelSize: "Small" },
      etsy_specifics: { category_specifics: { occasion: "Birthday" } },
    });
  });
});

describe("cloneListing", () => {
  it("returns a deep copy", () => {
    const original = { poshmark_specifics: { originalPrice: 80 } };
    const copy = cloneListing(original);
    setNestedValue(copy, "poshmark_specifics.originalPrice", 90);
    expect(original.poshmark_specifics.originalPrice).toBe(80);
  });

  it("treats a missing listing as empty", () => {
    expect(cloneListing(undefined)).toEqual({});
  });
});
