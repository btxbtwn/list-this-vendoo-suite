import { describe, expect, it } from "vitest";
import { calendarDate, dateOnly, monthDays, saleProfit, shiftMonth, suggestDiscount } from "./saleCalendarDates";

describe("sale calendar dates", () => {
  it("preserves calendar dates across DST, leap days, and year boundaries", () => {
    for (const day of ["2026-03-08", "2026-11-01", "2026-12-31", "2028-02-29"]) expect(calendarDate(dateOnly(day))).toBe(day);
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });
  it("shows six Monday-first weeks with adjacent month dates", () => {
    const days = monthDays("2026-10");
    expect(days).toHaveLength(42);
    expect(days[0]).toBe("2026-09-28");
    expect(days[41]).toBe("2026-11-08");
    expect(new Set(days).size).toBe(42);
  });
});
describe("sale profit planning", () => {
  it("deducts fees, cost and shipping after discounting", () => {
    expect(saleProfit(50, 10, 10, 15, 2)).toBe(26.25);
    expect(saleProfit(50, 44, 10, 15, 2)).toBe(-7.75);
  });
  it("preserves zero cost and rounds the sale price before deducting fees", () => {
    expect(saleProfit(19.99, 0, 50, 0, 0)).toBe(10);
  });
  it("does not invent profit with missing costs or invalid inputs", () => {
    expect(saleProfit(50, null, 10, 15, 2)).toBeNull();
    expect(saleProfit(50, 10, NaN, 15, 2)).toBeNull();
  });
});
describe("suggested discount", () => {
  it("picks the deepest 5% step, up to 30%, that keeps every costed listing above the floor", () => {
    expect(suggestDiscount([{ price: 100, cost: 5 }], 10, 0, 0)).toBe(30);
    // 25% off $40 is $30 → $27 after fees, less $20 cost is $7; 30% off leaves $5.20.
    expect(suggestDiscount([{ price: 100, cost: 5 }, { price: 40, cost: 20 }], 10, 0, 6)).toBe(25);
    expect(suggestDiscount([{ price: 40, cost: 20 }, { price: 50, cost: null }], 10, 0, 0)).toBe(30);
  });
  it("suggests nothing when no listing has a cost or even 5% breaks the floor", () => {
    expect(suggestDiscount([{ price: 50, cost: null }], 10, 0, 0)).toBeNull();
    expect(suggestDiscount([{ price: 20, cost: 19 }], 10, 0, 0)).toBeNull();
  });
});
