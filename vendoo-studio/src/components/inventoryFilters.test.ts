import { describe, expect, it } from "vitest";
import {
  DEFAULT_LISTING_FILTERS,
  activeFilterCount,
  filterListings,
  labelOptions,
  marketplaceOptions,
  matchesSearch,
  sortListings,
  statusCounts,
  toggleValue,
  type FilterableListing,
} from "./inventoryFilters";

const tee: FilterableListing = {
  title: "Nike Tee Black M",
  status: "active",
  sku: "NIKE-TEE-M",
  price: 24,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-18T00:00:00Z",
  vendoo_labels: ["A19", "To List"],
  vendoo_marketplaces: ["ebay", "poshmark"],
};
const boots: FilterableListing = {
  title: "Doc Martens 1460",
  status: "sold",
  sku: "DOC-1460-9",
  price: 120,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-09-19T00:00:00Z",
  vendoo_labels: ["Vintage"],
  vendoo_marketplaces: ["depop"],
};
const draft: FilterableListing = {
  title: "Untitled",
  status: "draft",
  created_at: "2026-09-10T00:00:00Z",
  updated_at: "2026-09-10T00:00:00Z",
  vendoo_labels: [],
  vendoo_marketplaces: [],
};
const inventory = [tee, boots, draft];

const withFilters = (overrides: Partial<typeof DEFAULT_LISTING_FILTERS>) => ({
  ...DEFAULT_LISTING_FILTERS,
  ...overrides,
});

describe("matchesSearch", () => {
  it("matches title and SKU, case-insensitively", () => {
    expect(matchesSearch(tee, "nike tee")).toBe(true);
    expect(matchesSearch(tee, "nike-tee-m")).toBe(true);
    expect(matchesSearch(tee, "martens")).toBe(false);
  });

  it("keeps everything for an empty query", () => {
    expect(matchesSearch(draft, "")).toBe(true);
  });
});

describe("filterListings", () => {
  it("keeps the whole inventory by default", () => {
    expect(filterListings(inventory, "", DEFAULT_LISTING_FILTERS)).toEqual(inventory);
  });

  it("filters by status tab", () => {
    expect(filterListings(inventory, "", withFilters({ status: "sold" }))).toEqual([boots]);
  });

  it("matches any selected marketplace", () => {
    expect(filterListings(inventory, "", withFilters({ marketplaces: ["depop", "ebay"] }))).toEqual([tee, boots]);
    expect(filterListings(inventory, "", withFilters({ marketplaces: ["etsy"] }))).toEqual([]);
  });

  it("matches any selected label, ignoring case", () => {
    expect(filterListings(inventory, "", withFilters({ labels: ["to list"] }))).toEqual([tee]);
  });

  it("shows only unlisted items, over any marketplace chips", () => {
    expect(filterListings(inventory, "", withFilters({ notListed: true, marketplaces: ["ebay"] }))).toEqual([draft]);
  });

  it("combines search with the filters", () => {
    expect(filterListings(inventory, "doc", withFilters({ status: "sold" }))).toEqual([boots]);
    expect(filterListings(inventory, "doc", withFilters({ status: "active" }))).toEqual([]);
  });
});

describe("sortListings", () => {
  it("leaves the order alone for recent activity", () => {
    expect(sortListings(inventory, "recent")).toEqual(inventory);
  });

  it("sorts by date created and modified in both directions", () => {
    expect(sortListings(inventory, "created_desc")).toEqual([draft, tee, boots]);
    expect(sortListings(inventory, "created_asc")).toEqual([boots, tee, draft]);
    expect(sortListings(inventory, "modified_desc")).toEqual([boots, tee, draft]);
    expect(sortListings(inventory, "modified_asc")).toEqual([draft, tee, boots]);
  });

  it("sorts alphabetically and by price", () => {
    expect(sortListings(inventory, "title_asc")).toEqual([boots, tee, draft]);
    expect(sortListings(inventory, "title_desc")).toEqual([draft, tee, boots]);
    expect(sortListings(inventory, "price_desc")).toEqual([boots, tee, draft]);
    expect(sortListings(inventory, "price_asc")).toEqual([tee, boots, draft]);
  });

  it("sorts by SKU and leaves listings without one at the end", () => {
    expect(sortListings(inventory, "sku_asc")).toEqual([boots, tee, draft]);
    expect(sortListings(inventory, "sku_desc")).toEqual([tee, boots, draft]);
  });
});

describe("filter options", () => {
  it("counts each status tab", () => {
    expect(statusCounts(inventory)).toEqual({ all: 3, active: 1, sold: 1, draft: 1 });
  });

  it("lists every label once, sorted", () => {
    expect(labelOptions([tee, boots, { vendoo_labels: ["a19"] }])).toEqual(["A19", "To List", "Vintage"]);
  });

  it("keeps Settings' marketplace order and appends the rest", () => {
    expect(marketplaceOptions(inventory, ["poshmark", "ebay", "mercari"])).toEqual(["poshmark", "ebay", "depop"]);
  });

  it("counts what is filtering the list", () => {
    expect(activeFilterCount(DEFAULT_LISTING_FILTERS)).toBe(0);
    expect(activeFilterCount(withFilters({ status: "sold", labels: ["A19"], notListed: true }))).toBe(3);
  });

  it("toggles a value in and out", () => {
    expect(toggleValue(["ebay"], "etsy")).toEqual(["ebay", "etsy"]);
    expect(toggleValue(["ebay", "etsy"], "ebay")).toEqual(["etsy"]);
  });
});
