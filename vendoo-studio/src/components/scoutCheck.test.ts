import { describe, expect, it } from "vitest";
import type { ScoutCheck } from "../api/types";
import { trackRecordLine, verdictLabel, verdictReason } from "./scoutCheck";

const check = {
  estimate: 50,
  comps_count: 6,
  net: 40,
  pay_up_to: 20,
  asking_price: 15,
  profit: 25,
} as ScoutCheck;

describe("scout check", () => {
  it("labels verdicts", () => {
    expect(verdictLabel("buy")).toBe("Buy it");
    expect(verdictLabel(null)).toBeNull();
  });

  it("explains the verdict with the asking price", () => {
    expect(verdictReason(check)).toBe("Sells for about $50 (6 sales), $40 after fees. At $15 that's about $25 profit.");
    expect(verdictReason({ ...check, asking_price: 45, profit: -5 }))
      .toBe("Sells for about $50 (6 sales), $40 after fees. At $45 that's a $5 loss.");
  });

  it("says what to pay when no price was given", () => {
    expect(verdictReason({ ...check, asking_price: null, profit: null }))
      .toBe("Sells for about $50 (6 sales), $40 after fees. Worth paying up to $20.");
  });

  it("is honest when there are too few comps", () => {
    expect(verdictReason({ ...check, estimate: null })).toMatch(/^Too few sold listings/);
  });

  it("summarizes the track record", () => {
    expect(trackRecordLine({ checks: 0, bought: 0, sold: 0, median_ratio: null, close: 0 })).toBeNull();
    expect(trackRecordLine({ checks: 12, bought: 5, sold: 3, median_ratio: 0.9, close: 2 }))
      .toBe("12 checks · 5 bought · 3 sold, 2 within 25% of the estimate");
  });
});
