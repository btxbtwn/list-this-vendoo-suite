import { describe, expect, it } from "vitest";
import type { SourcingCart, SourcingLot, SourcingSnapshot } from "../api/types";
import {
  cartTotal,
  clockTime,
  freeShippingGap,
  gradeLabel,
  isZip,
  lotReason,
  moneyBack,
  nextUpdate,
  otherLots,
  piecesLabel,
} from "./boxScout";

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

describe("money", () => {
  it("adds shipping to a store's total", () => {
    expect(cartTotal(cart())).toBe(205);
  });

  it("says what each dollar spent should bring back", () => {
    expect(moneyBack(418, 1210)).toBe("$3.89");
    expect(moneyBack(0, 0)).toBe("$0");
  });

  it("says how much more unlocks free shipping", () => {
    expect(freeShippingGap(cart())).toBe(35);
    expect(freeShippingGap(cart({ free_shipping: true }))).toBeNull();
    expect(freeShippingGap(cart({ free_shipping_over: null }))).toBeNull();
  });
});

describe("box wording", () => {
  it("counts pieces the way each store does, with ~ when estimated", () => {
    expect(piecesLabel(lot())).toBe("69 pcs");
    expect(piecesLabel(lot({ store: "tvf", pcs: 10 }))).toBe("10 Pieces");
    expect(piecesLabel(lot({ store: "tvf", pcs: 150, pcs_estimated: true }))).toBe("~150 Pieces");
  });

  it("names grades in each store's words", () => {
    expect(gradeLabel(lot({ grade: "recycle" }))).toBe("Recycle");
    expect(gradeLabel(lot({ grade: "mixed" }))).toBe("Recycle & Good");
    expect(gradeLabel(lot({ store: "tvf", grade: "bc" }))).toBe("B/C Grade");
    expect(gradeLabel(lot({ store: "tvf", grade: "good" }))).toBeNull();
  });

  it("explains a box in one line", () => {
    expect(lotReason(lot())).toBe("69 pcs · Good · sells for about $14 each");
    expect(lotReason(lot({ grade: "recycle", resale_per_pc: null, vip: true }), true)).toBe(
      "Raghouse · 69 pcs · Recycle · VIP only",
    );
    expect(lotReason(lot({ store: "tvf", pcs: 10, resale_per_pc: null }), true)).toBe(
      "Thrift Vintage Fashion · 10 Pieces",
    );
  });
});

describe("otherLots", () => {
  it("shows the best box of each kind the buy list did not take", () => {
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

describe("times", () => {
  it("shows only the time for today and adds the day otherwise", () => {
    const now = new Date(2026, 8, 27, 18, 0);
    expect(clockTime(new Date(2026, 8, 27, 14, 5).toISOString(), now)).not.toMatch(/[A-Za-z]{3} /);
    expect(clockTime(new Date(2026, 8, 25, 14, 5).toISOString(), now)).toMatch(/^[A-Za-z]{3} /);
    expect(clockTime("not a date", now)).toBe("");
  });

  it("puts the next update six hours after the last", () => {
    expect(nextUpdate("2026-09-27T12:00:00.000Z")).toBe("2026-09-27T18:00:00.000Z");
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
