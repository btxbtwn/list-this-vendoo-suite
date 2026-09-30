import { describe, expect, it } from "vitest";
import { formatChange, formatDays, formatMoney } from "./analyticsFormat";

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

describe("formatChange", () => {
  it("compares positive baselines", () => {
    expect(formatChange(150, 100, formatMoney)).toBe("Up $50 (50%)");
    expect(formatChange(5, 10, String)).toBe("Down 5 (50%)");
  });

  it("avoids misleading percentages for zero baselines or losses", () => {
    expect(formatChange(40, 0, formatMoney)).toBe("Up $40");
    expect(formatChange(-20, -40, formatMoney)).toBe("Up $20");
    expect(formatChange(-20, 40, formatMoney)).toBe("Down $60");
  });

  it("handles missing and unchanged values", () => {
    expect(formatChange(null, 10, formatDays)).toBe("No comparison data");
    expect(formatChange(10, null, formatDays)).toBe("No comparison data");
    expect(formatChange(0, 0, String)).toBe("No change");
  });
});
