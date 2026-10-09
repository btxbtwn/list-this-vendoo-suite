import { describe, expect, it } from "vitest";
import type { SourceBox, SourcingLot } from "../api/types";
import { boxFromLot, boxProgress, calibrationNote, boxStoreKey, boxStoreName, formatPercent, recentlyBought, shippingNote } from "./boxPurchases";

const lot = {
  store: "raghouse",
  title: "Carhartt 25 pcs",
  url: "https://raghouse.com/products/carhartt?variant=1",
  price: 180,
  ship_est: 33.951,
  ship_list: 65.96,
  pcs: 25,
  resale_per_pc: 14,
} as SourcingLot;

describe("bought boxes", () => {
  it("names the scouted stores and keeps any other name", () => {
    expect(boxStoreName("tvf")).toBe("Thrift Vintage Fashion");
    expect(boxStoreName("Goodwill Bins")).toBe("Goodwill Bins");
    expect(boxStoreKey(" thrift vintage fashion ")).toBe("tvf");
    expect(boxStoreKey("Goodwill Bins")).toBe("Goodwill Bins");
  });

  it("records a buy-list box with its shipping estimate and piece count", () => {
    expect(boxFromLot(lot)).toEqual({
      store: "raghouse",
      title: "Carhartt 25 pcs",
      url: lot.url,
      price: 180,
      shipping: 33.95,
      pieces: 25,
      list_shipping: 65.96,
      estimate_per_piece: 14,
    });
  });

  it("stores the estimate from before the seller's sales adjusted it", () => {
    expect(boxFromLot({ ...lot, resale_per_pc: 11.2, resale_factor: 0.8 }).estimate_per_piece).toBe(14);
  });

  it("explains how real shipping charges set the estimates", () => {
    expect(shippingNote("Raghouse", undefined)).toBeNull();
    expect(shippingNote("Raghouse", { factor: null, orders: 1, needed: 2 })).toBeNull();
    expect(shippingNote("Thrift Vintage Fashion", { factor: 0.62, orders: 3, needed: 2 }))
      .toBe("Thrift Vintage Fashion shipping is set to 62% of the carrier list rate, from 3 orders you recorded.");
  });

  it("explains how real sales moved the estimates", () => {
    expect(calibrationNote("Raghouse", { factor: null, sales: 2, needed: 5 }))
      .toBe("Raghouse: 2 sales from bought boxes so far. Studio starts adjusting its estimates after 3 more.");
    expect(calibrationNote("Raghouse", { factor: 0.82, sales: 12, needed: 5 }))
      .toBe("Raghouse: your 12 sales sold for 82% of what Studio estimated, so its Raghouse prices are set to 82%.");
  });

  it("treats a box with the same link from the last two weeks as already bought", () => {
    const now = Date.parse("2026-10-04T00:00:00Z");
    const box = { url: lot.url, bought_at: "2026-09-30T00:00:00Z" } as SourceBox;
    expect(recentlyBought(lot, [box], now)).toBe(true);
    expect(recentlyBought(lot, [{ ...box, bought_at: "2026-09-01T00:00:00Z" }], now)).toBe(false);
  });

  it("describes progress and percentages", () => {
    expect(boxProgress({ sold: 4, listed: 9, listings: 12, pieces: 20 })).toBe("Sold 4 of 20 · 5 listed · 3 drafts");
    expect(boxProgress({ sold: 0, listed: 0, listings: 0, pieces: null })).toBe("Sold 0");
    expect(formatPercent(0.125)).toBe("13%");
    expect(formatPercent(null)).toBe("—");
  });
});
