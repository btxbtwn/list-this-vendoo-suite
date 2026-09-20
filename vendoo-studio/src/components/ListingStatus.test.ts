import { describe, expect, it } from "vitest";
import { listedFromImport, statusHint } from "./ListingSidebar";

describe("statusHint", () => {
  it("says where each Vendoo label comes from", () => {
    expect(statusHint("draft")).toBe("Draft in Vendoo");
    expect(statusHint("active")).toBe("Listed on a marketplace, per Vendoo");
    expect(statusHint("sold")).toBe("Sold, per Vendoo");
  });

  it("explains the states Studio itself causes", () => {
    expect(statusHint("failed")).toBe("The last send to Vendoo failed");
    expect(statusHint("listing")).toBe("Studio is sending this listing to Vendoo");
    expect(statusHint("in_progress")).toBe("Studio is working on this listing");
  });

  it("still names Vendoo for a status it does not know", () => {
    expect(statusHint("some_new_state")).toBe("some new state · follows Vendoo");
  });
});

describe("listedFromImport", () => {
  it("badges the marketplaces the import recorded", () => {
    expect(listedFromImport({ vendoo_marketplaces: ["poshmark", "ebay"] })).toEqual([
      { id: "ebay", label: "eBay", status: "LISTED" },
      { id: "poshmark", label: "Poshmark", status: "LISTED" },
    ]);
  });

  it("marks the marketplace an item sold on", () => {
    const rows = listedFromImport({
      vendoo_marketplaces: ["ebay", "mercari"],
      vendoo_sold_dates: { mercari: "2026-09-01T00:00:00Z" },
    });
    expect(rows.map((row) => row.status)).toEqual(["LISTED", "SOLD"]);
  });

  it("keeps only the marketplaces Settings shows, and folds Vestiaire's two ids", () => {
    expect(
      listedFromImport({ vendoo_marketplaces: ["vestiaireApi", "depop"] }, new Set(["vestiaire"])),
    ).toEqual([{ id: "vestiaire", label: "Vestiaire Collective", status: "LISTED" }]);
  });

  it("has nothing to say for a listing that was never imported", () => {
    expect(listedFromImport({})).toEqual([]);
  });
});
