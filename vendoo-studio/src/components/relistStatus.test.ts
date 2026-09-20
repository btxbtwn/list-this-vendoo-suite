import { describe, expect, it } from "vitest";
import {
  describeMarketplaces,
  joinMarketplaces,
  marketplacesNeedingRelist,
  needsRelist,
  relistCallout,
  type RelistableListing,
} from "./relistStatus";

const live: RelistableListing = {
  status: "active",
  vendoo_marketplaces: ["ebay", "poshmark"],
  vendoo_listed_at: "2026-09-01T00:00:00Z",
  vendoo_listed_dates: { ebay: "2026-09-01T00:00:00Z", poshmark: "2026-09-01T00:00:00Z" },
  vendoo_form_updated_at: "2026-09-18T00:00:00Z",
};

describe("marketplacesNeedingRelist", () => {
  it("names every live marketplace listed before the last Studio write", () => {
    expect(marketplacesNeedingRelist(live)).toEqual(["ebay", "poshmark"]);
  });

  it("clears a marketplace that was relisted after the write", () => {
    expect(marketplacesNeedingRelist({
      ...live,
      vendoo_listed_dates: { ebay: "2026-09-19T00:00:00Z", poshmark: "2026-09-01T00:00:00Z" },
    })).toEqual(["poshmark"]);
  });

  it("stays quiet until Studio has written to Vendoo", () => {
    expect(needsRelist({ ...live, vendoo_form_updated_at: null })).toBe(false);
  });

  it("stays quiet for a listing that never went live", () => {
    expect(needsRelist({ status: "draft", vendoo_form_updated_at: "2026-09-18T00:00:00Z" })).toBe(false);
  });

  it("leaves a sold marketplace alone", () => {
    expect(marketplacesNeedingRelist({
      ...live,
      vendoo_sold_dates: { poshmark: "2026-09-10T00:00:00Z" },
    })).toEqual(["ebay"]);
  });

  it("drops the whole item once it is sold", () => {
    expect(needsRelist({ ...live, status: "sold" })).toBe(false);
  });

  it("warns on a live marketplace with no listing date to compare", () => {
    expect(marketplacesNeedingRelist({
      ...live,
      vendoo_listed_at: null,
      vendoo_listed_dates: {},
    })).toEqual(["ebay", "poshmark"]);
  });

  it("falls back to the item's listing date when the marketplace has none", () => {
    expect(marketplacesNeedingRelist({
      ...live,
      vendoo_listed_at: "2026-09-19T00:00:00Z",
      vendoo_listed_dates: {},
    })).toEqual([]);
  });
});

describe("copy", () => {
  it("joins names the way a sentence reads", () => {
    expect(joinMarketplaces(["eBay"])).toBe("eBay");
    expect(joinMarketplaces(["eBay", "Poshmark"])).toBe("eBay and Poshmark");
    expect(joinMarketplaces(["eBay", "Poshmark", "Depop"])).toBe("eBay, Poshmark and Depop");
  });

  it("counts the marketplaces once the list gets long", () => {
    expect(describeMarketplaces(["eBay"])).toBe("eBay");
    expect(describeMarketplaces(["eBay", "Poshmark"])).toBe("eBay and Poshmark");
    expect(describeMarketplaces(["eBay", "Poshmark", "Depop"])).toBe("all 3 marketplaces");
  });

  it("says the same of a long list without naming every one", () => {
    expect(relistCallout(["eBay", "Poshmark", "Depop", "Mercari"])).toBe(
      "The Vendoo form is updated, but the live listings on all 4 marketplaces"
      + " still show the old version.",
    );
  });

  it("says what is stale, agreeing with one marketplace or several", () => {
    expect(relistCallout(["eBay"])).toBe(
      "The Vendoo form is updated, but the live eBay listing shows the old version.",
    );
    expect(relistCallout(["eBay", "Poshmark"])).toBe(
      "The Vendoo form is updated, but the live eBay and Poshmark listings show the old version.",
    );
  });
});
