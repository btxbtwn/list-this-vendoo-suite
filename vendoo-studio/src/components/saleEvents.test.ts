import { describe, expect, it } from "vitest";
import type { SaleEvent } from "../api/types";
import { eventDates, eventLift, eventMarketplaces } from "./saleEvents";

function event(overrides: Partial<SaleEvent> = {}): SaleEvent {
  return {
    id: "e1",
    name: "Depop sale",
    starts_on: "2026-11-27",
    ends_on: "2026-12-01",
    discount_percent: 25,
    marketplaces: ["depop", "ebay"],
    status: "ended",
    sold: 4,
    revenue: 90,
    per_week: 5.6,
    before_per_week: 2,
    after_per_week: 3.5,
    after_days: 14,
    sales: [],
    ...overrides,
  };
}

describe("eventLift", () => {
  it("sets the event's pace against the weeks around it", () => {
    expect(eventLift(event())).toBe("5.6/week during · 2/week the 4 weeks before · 3.5/week the 2 weeks after");
  });

  it("names the days so far when the two weeks after are not over", () => {
    expect(eventLift(event({ after_days: 3 }))).toContain("the 3 days after");
  });

  it("leaves out the after rate while the event is still on", () => {
    expect(eventLift(event({ status: "running", after_per_week: null, after_days: 0 }))).not.toContain("after");
  });

  it("has nothing to compare before it starts", () => {
    expect(eventLift(event({ status: "upcoming", per_week: null }))).toBe("Not started yet.");
  });
});

describe("event labels", () => {
  it("reads the dates as calendar days", () => {
    expect(eventDates(event({ starts_on: "2026-12-01", ends_on: "2026-12-01" }))).toMatch(/1/);
    expect(eventDates(event())).toContain("–");
  });

  it("names the marketplaces, or all of them when none were chosen", () => {
    expect(eventMarketplaces(["depop", "ebay"])).toBe("Depop, eBay");
    expect(eventMarketplaces([])).toBe("All marketplaces");
  });
});
