import { describe, expect, it } from "vitest";
import type { SourcingCart, SourcingLot, SourcingSnapshot, SourcingState } from "../api/types";
import {
  cartTotal,
  clockTime,
  freeShippingGap,
  gradeLabel,
  isZip,
  lotReason,
  nextUpdate,
  otherLots,
  planMetrics,
  planNeedsUpdate,
  piecesLabel,
  whyNotPicked,
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
    resale_factor: 1,
    sell_through: 0.75,
    expected_revenue: 520,
    expected_profit: 388,
    roi: 2.94,
    score: 3.9,
    evidence: [],
    comps: [],
    research_at: null,
    research_source: null,
    active_comps: [],
    active_median: null,
    resale_low: 12,
    operating_cost: 124.2,
    break_even_pcs: 23,
    downside_profit: 25,
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

  it("says how much more unlocks free shipping", () => {
    expect(freeShippingGap(cart())).toBe(35);
    expect(freeShippingGap(cart({ free_shipping: true }))).toBeNull();
    expect(freeShippingGap(cart({ free_shipping_over: null }))).toBeNull();
  });
});

function state(): SourcingState {
  const prefs = {
    budget: 300, min_roi: 1, raghouse_vip: false, zip: "70115", recent_zips: ["70115"],
    sell_through: 0.5, fees: 0.2, cost_per_piece: 2, ready_in_weeks: 4, selling_window_weeks: 4,
  };
  const plan = { budget: 300, total: 132, expected_profit: 388, carts: [cart({ lots: [lot()] })], exclusions: {} };
  return {
    refreshing: false, research_available: true, prefs,
    trend: { terms: [], updated_at: null, source: null },
    snapshot: {
      updated_at: "2026-10-05T12:00:00Z", destination_zip: "70115",
      preferences: {
        budget: 300, min_roi: 1, raghouse_vip: false, zip: "70115", sell_through: 0.5,
        fees: 0.2, cost_per_piece: 2, ready_in_weeks: 4, selling_window_weeks: 4,
      },
      seasonality: {
        window: { buy_on: "2026-10-07", start_date: "2026-11-04", end_date: "2026-12-01", ready_in_weeks: 4, selling_window_weeks: 4, market: "US online resale", timezone: "UTC" },
        seller_history: { periods: [], dated_recorded_sales: 0, matching_window_sales: 0, excluded_incomplete_or_invalid: 0, minimum_group_sales: 5, coverage: "recorded sales", groups: [] },
      },
      calibration: {}, stores: {}, research: true, priced_themes: 1,
      shipping: { residential_surcharge: 6, fuel_surcharge_pct: 0.2, fuel_surcharge_as_of: "2026-10-01" },
      assumptions: { sell_through: 0.5, fees: 0.2, cost_per_piece: 2, grade_yield: { good: 0.9 } },
      buy_list: plan, store_buy_lists: { raghouse: plan, tvf: plan }, lots: [lot()],
    },
  };
}

describe("planning settings", () => {
  it("keeps cart links unavailable until every saved planning input is reflected", () => {
    const original = state();
    expect(planNeedsUpdate(original)).toBe(false);
    expect(planNeedsUpdate({ ...original, snapshot: null })).toBe(true);
    for (const [key, value] of Object.entries({
      budget: 200, min_roi: 1.5, raghouse_vip: true, zip: "10001", sell_through: 0.75,
      fees: 0.25, cost_per_piece: 5, ready_in_weeks: 8, selling_window_weeks: 6,
    })) {
      expect(planNeedsUpdate({ ...original, prefs: { ...original.prefs, [key]: value } }), key).toBe(true);
    }
    expect(planNeedsUpdate({ ...original, prefs: { ...original.prefs, recent_zips: ["10001", "70115"] } })).toBe(false);
  });

  it("shows operating cash separately from the purchase budget", () => {
    const plan = state().snapshot!.buy_list;
    expect(planMetrics(plan)).toEqual({ usable: 62.1, sold: 62.1 * 0.75, operating: 124.2, downside: 25 });
  });

  it("uses the selected plan’s exclusion reason rather than guessing from individual shipping", () => {
    const plan = { ...state().snapshot!.buy_list, exclusions: { "raghouse:1": "downside" as const } };
    expect(whyNotPicked(lot({ roi: 4 }), plan)).toBe("Loses money in the lower-sales test");
    expect(whyNotPicked(lot(), { ...plan, exclusions: { "raghouse:1": "return_target" } })).toBe("Below your return target");
  });

  it("preserves other-store comparisons of a selected theme", () => {
    const snapshot = state().snapshot!;
    snapshot.lots.push(lot({ store: "tvf", variant_id: 2 }));
    expect(otherLots(snapshot).map((row) => row.store)).toEqual(["tvf"]);

  });
});

describe("box wording", () => {
  it("counts pieces the way each store does, with ~ when estimated", () => {
    expect(piecesLabel(lot())).toBe("69 pcs");
    expect(piecesLabel(lot({ store: "tvf", pcs: 10 }))).toBe("10 Pieces");
    expect(piecesLabel(lot({ store: "tvf", pcs: 150, pcs_estimated: true }))).toBe("~150 Pieces");
  });

  it("names grades in each store's words", () => {
    expect(gradeLabel(lot())).toBe("Good");
    expect(gradeLabel(lot({ store: "tvf", grade: "bc" }))).toBe("B/C Grade");
    expect(gradeLabel(lot({ store: "tvf", grade: "good" }))).toBeNull();
  });

  it("explains a box in one line", () => {
    expect(lotReason(lot())).toBe("69 pcs · Good · estimated resale $14 each");
    expect(lotReason(lot({ resale_per_pc: null, vip: true }), true)).toBe(
      "Raghouse · 69 pcs · Good · VIP only",
    );
    expect(lotReason(lot({ store: "tvf", pcs: 10, resale_per_pc: null }), true)).toBe(
      "Thrift Vintage Fashion · 10 Pieces",
    );
  });
});

describe("otherLots", () => {
  it("shows all 80 checked boxes when none are recommended, including repeated themes", () => {
    const snapshot = state().snapshot!;
    snapshot.buy_list.carts = [];
    snapshot.lots = Array.from({ length: 80 }, (_, index) => lot({ variant_id: index + 1 }));
    expect(otherLots(snapshot)).toHaveLength(80);
  });
  it("keeps alternative variants of the same theme visible and excludes only selected boxes", () => {
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
    expect(otherLots(snapshot).map((item) => item.variant_id)).toEqual([2, 3, 4, 5]);
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
