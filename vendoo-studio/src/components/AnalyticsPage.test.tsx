import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { InventoryAnalytics } from "../api/types";
import { AnalyticsPage } from "./AnalyticsPage";

const { useQuery } = vi.hoisted(() => ({ useQuery: vi.fn() }));
vi.mock("@tanstack/react-query", () => ({ useQuery, keepPreviousData: vi.fn() }));

const sales = {
  count: 2, revenue: 80, revenue_known: 2, profit: 50,
  profit_known: 2, fees_known: 2, average_price: 40, median_days: 10, days_known: 2,
};
const data: InventoryAnalytics = {
  range: "30d", undated_sales: 1, periods_truncated: false,
  inventory: { active: 1, draft: 0, sold: 2, failed: 0, working: 0, asking_value: 60 },
  sales,
  previous: {
    start: "2026-08-01T00:00:00Z", end: "2026-08-31T00:00:00Z",
    sales: { ...sales, revenue: 40, profit: 25, count: 1, revenue_known: 1, profit_known: 1, fees_known: 1 },
  },
  periods: [], marketplaces: [], categories: [], brands: [], recent: [],
  aging: [{
    label: "Over 3 months", count: 1, asking_value: 60,
    listings: [{ conversation_id: "old-stock", title: "Older jacket", price: 60, days_listed: 110 }],
  }],
};

function render(payload: InventoryAnalytics) {
  useQuery.mockReturnValue({ data: payload, isLoading: false, isError: false, isFetching: false });
  return renderToStaticMarkup(<AnalyticsPage onOpenListing={vi.fn()} />);
}

describe("AnalyticsPage", () => {
  it("renders period comparisons, coverage, and expandable active listings", () => {
    const html = render(data);
    expect(html).toContain("Last 30 days");
    expect(html).toContain("Up $40 (100%)");
    expect(html).toContain("previous period, same length");
    expect(html).toContain("2 of 2 sales with recorded prices");
    expect(html).toContain("Excluded from this period");
    expect(html).toContain("<details");
    expect(html).toContain("<summary");
    expect(html).toContain("Older jacket");
    expect(html).toContain("110 days");
  });

  it("withholds comparisons when prices or costs are missing", () => {
    const html = render({ ...data, sales: { ...sales, revenue_known: 1, profit_known: 1, fees_known: 0 } });
    expect(html).toContain("Comparison unavailable: missing prices");
    expect(html).toContain("Comparison unavailable: missing costs or fees");
    expect(html).toContain("1 sale has no recorded price");
    expect(html).not.toContain("Up $40");
    expect(html).not.toContain("undefined");
  });

  it("does not show previous-period comparisons for all time", () => {
    const html = render({ ...data, range: "all", previous: null });
    expect(html).not.toContain("Compared with");
    expect(html).not.toContain("Up $40");
    expect(html).toContain("Included in totals, but excluded from the chart");
  });
});
