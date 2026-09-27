import { describe, expect, it } from "vitest";
import type { SourcingCart, SourcingLot, SourcingSnapshot } from "../api/types";
import { formatRoi, freeShippingGap, isZip, lotMeta, otherLots, whenChecked } from "./boxScout";

function lot(overrides: Partial<SourcingLot> = {}): SourcingLot {
  return {
    store: "raghouse",
    variant_id: 1,
    title: "Cartoon T-Shirts 69 pcs",
    url: "https://raghouse.com/products/cartoon",
    price: 68,
    compare_at: null,
    pcs: 69,
    pcs_estimated: false,
    grade: "good",
    lbs: 28.2,
    lbs_estimated: false,
    vip: false,
    listed: null,
    seller_resale: null,
    theme: "cartoon t-shirts",
    ship_est: 64,
    usable_pcs: 62.1,
    demand: 1.5,
    trend_hits: [],
    landed: 132,
    cog_per_pc: 1.91,
    cog_per_usable_pc: 2.12,
    resale_per_pc: 14,
    sell_through: 0.75,
    expected_revenue: 520,
    expected_profit: 388,
    roi: 2.94,
    score: 3.9,
    evidence: [],
    ...overrides,
  };
}

function cart(overrides: Partial<SourcingCart> = {}): SourcingCart {
  return {
    store: "tvf",
    name: "Thrift Vintage Fashion",
    subtotal: 165,
    shipping: 40,
    free_shipping: false,
    free_shipping_over: 200,
    cart_url: "https://thriftvintagefashion.com/cart/1:1",
    lots: [],
    ...overrides,
  };
}

describe("freeShippingGap", () => {
  it("says how much more unlocks free shipping", () => {
    expect(freeShippingGap(cart())).toBe(35);
  });

  it("is null once shipping is free or when the store has no threshold", () => {
    expect(freeShippingGap(cart({ free_shipping: true }))).toBeNull();
    expect(freeShippingGap(cart({ free_shipping_over: null }))).toBeNull();
  });
});

describe("lotMeta", () => {
  it("marks estimated counts and weights", () => {
    expect(lotMeta(lot())).toBe("Good · 69 pcs · 28 lb");
    expect(lotMeta(lot({ grade: "b", pcs_estimated: true, lbs_estimated: true, vip: true }))).toBe(
      "B grade · ~69 pcs · ~28 lb · VIP only",
    );
  });
});

describe("otherLots", () => {
  it("shows the best lot of each theme the buy list did not take", () => {
    const picked = lot({ variant_id: 1, theme: "cartoon t-shirts" });
    const snapshot = {
      buy_list: { budget: 300, total: 132, expected_profit: 388, carts: [cart({ lots: [picked] })] },
      lots: [
        picked,
        lot({ variant_id: 2, theme: "cartoon t-shirts" }),
        lot({ variant_id: 3, theme: "abbie tees & tops" }),
        lot({ variant_id: 4, theme: "abbie tees & tops" }),
        lot({ variant_id: 5, theme: "y2k vibes" }),
      ],
    } as SourcingSnapshot;
    expect(otherLots(snapshot).map((item) => item.variant_id)).toEqual([3, 5]);
    expect(otherLots(snapshot, 1)).toHaveLength(1);
  });
});

describe("formatting", () => {
  it("rounds ROI to a whole percent", () => {
    expect(formatRoi(2.944)).toBe("294%");
  });

  it("says today for a check made today", () => {
    const now = new Date(2026, 8, 27, 18, 0);
    expect(whenChecked(new Date(2026, 8, 27, 14, 5).toISOString(), now)).toMatch(/^today /);
    expect(whenChecked(new Date(2026, 8, 25, 14, 5).toISOString(), now)).not.toMatch(/^today /);
    expect(whenChecked("not a date", now)).toBe("");
  });
});

describe("isZip", () => {
  it("takes five digits only", () => {
    expect(isZip("70115")).toBe(true);
    expect(isZip(" 70115 ")).toBe(true);
    expect(isZip("7011")).toBe(false);
    expect(isZip("70115-1234")).toBe(false);
  });
});
