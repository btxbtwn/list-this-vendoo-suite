import { describe, expect, it } from "vitest";
import { formatDays, formatMoney } from "./analyticsFormat";

describe("formatMoney", () => {
  it("drops cents on a whole dollar", () => {
    expect(formatMoney(1234)).toBe("$1,234");
    expect(formatMoney(0)).toBe("$0");
  });

  it("keeps cents when the amount is not whole", () => {
    expect(formatMoney(1234.5)).toBe("$1,234.50");
  });

  it("keeps the sign on a loss", () => {
    expect(formatMoney(-15)).toBe("-$15");
  });

  it("falls back when the amount is not a number", () => {
    expect(formatMoney(Number.NaN)).toBe("$0");
  });
});

describe("formatDays", () => {
  it("pluralizes", () => {
    expect(formatDays(1)).toBe("1 day");
    expect(formatDays(18)).toBe("18 days");
  });
});
