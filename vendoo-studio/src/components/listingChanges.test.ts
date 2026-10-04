import { describe, expect, it } from "vitest";
import { blockerTarget, changeValue, listingChanges, matchingEditorField } from "./listingChanges";

describe("listing review", () => {
  it("compares additions, removals, arrays and nested edits while hiding preparation metadata", () => {
    expect(listingChanges({ price: 30, brand: "Old", ebay_specifics: { size: "M" }, tags: ["old"], _vendoo_preparation: { a: 1 } },
      { price: 20, ebay_specifics: { size: "L" }, tags: ["new"], _vendoo_preparation: { a: 2 } })).toEqual([
      { field: "brand", before: "Old", after: undefined },
      { field: "ebay_specifics.size", before: "M", after: "L" },
      { field: "price", before: 30, after: 20 },
      { field: "tags", before: ["old"], after: ["new"] },
    ]);
  });
  it("does not hide zero and false", () => {
    expect(changeValue(0)).toBe("0");
    expect(changeValue(false)).toBe("false");
    expect(changeValue(null)).toBe("Empty");
  });
  it("routes each blocker to its marketplace or photos", () => {
    expect(blockerTarget("ebay_specifics.category_specifics.sleeveLength").tab).toBe("ebay");
    expect(blockerTarget("photos").reviewTab).toBe("input");
    expect(blockerTarget("price").tab).toBe("general");
  });
  it("matches Vendoo labels to nested listing keys", () => {
    expect(matchingEditorField([{ key: "ebay_specifics.Sleeve Length" }], "ebay_specifics.category_specifics.sleeveLength")).toBe("ebay_specifics.Sleeve Length");
    expect(matchingEditorField([{ key: "price" }], "brand")).toBeUndefined();
  });
});
