import { describe, expect, it } from "vitest";
import type { SourceBox, SourcingLot } from "../api/types";
import { boxFromLot, boxProgress, boxStoreKey, boxStoreName, formatPercent, recentlyBought } from "./boughtBoxes";

const lot = {
  store: "raghouse",
  title: "Carhartt 25 pcs",
  url: "https://raghouse.com/products/carhartt?variant=1",
  price: 180,
  ship_est: 33.951,
  pcs: 25,
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
    });
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
