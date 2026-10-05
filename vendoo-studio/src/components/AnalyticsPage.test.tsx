import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { InventoryAnalytics } from "../api/types";
import { AnalyticsPage } from "./AnalyticsPage";

const { useQuery } = vi.hoisted(() => ({ useQuery: vi.fn() }));
vi.mock("@tanstack/react-query", () => ({
  useQuery,
  keepPreviousData: vi.fn(),
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useQueryClient: () => ({ setQueryData: vi.fn(), invalidateQueries: vi.fn() }),
}));

const sales = {
  count: 2, revenue: 80, revenue_known: 2, profit: 50,
  profit_known: 2, fees_known: 2, average_price: 40, median_days: 10, days_known: 2, margin: 62.5,
};
const data: InventoryAnalytics = {
  range: "30d", undated_sales: 1, periods_truncated: false,
  inventory: { active: 1, draft: 0, sold: 2, failed: 0, working: 0, asking_value: 60, cost_value: 8, cost_known: 1, stale_count: 1, stale_value: 60, undated_count: 0 },
  sell_through_rate: 66.7,
  sales,
  previous: {
    start: "2026-08-01T00:00:00Z", end: "2026-08-31T00:00:00Z",
    sales: { ...sales, revenue: 40, profit: 25, count: 1, revenue_known: 1, profit_known: 1, fees_known: 1 },
  },
  periods: [{ ...sales, label: "Sep" }], marketplaces: [], categories: [], brands: [{ ...sales, id: "nike", label: "Nike" }],
  oldest: [{ conversation_id: "old-stock", title: "Older jacket", price: 60, days_listed: 110 }],
  recent: [{
    conversation_id: "sold-tee", title: "Band tee", price: 24, marketplace: "depop",
    sold_at: "2026-09-12T18:00:00Z", days_listed: 12, event: "Depop fall sale", profit: 12,
  }],
  stale: [
    {
      conversation_id: "old-stock", title: "Older jacket", days_listed: 110, price: 60,
      cost: 8, lowest_price: 10, discount_percent: 40, sale_price: 36,
    },
    {
      conversation_id: "thin-margin", title: "Pricey boots", days_listed: 75, price: 30,
      cost: 20, lowest_price: 25, discount_percent: null, sale_price: null,
    },
  ],
  aging: [{
    label: "Over 3 months", count: 1, asking_value: 60,
    listings: [{ conversation_id: "old-stock", title: "Older jacket", price: 60, days_listed: 110 }],
  }],
};

function render(payload: InventoryAnalytics) {
  useQuery.mockImplementation(({ queryKey }: { queryKey: readonly string[] }) =>
    queryKey[0] === "sale-events"
      ? { data: { events: [] }, isError: false }
      : { data: payload, isLoading: false, isError: false, isFetching: false },
  );
  return renderToStaticMarkup(<AnalyticsPage onOpenListing={vi.fn()} />);
}

describe("AnalyticsPage", () => {
  it("shows the weekly view and explains the sell-through percentage", () => {
    const html = render({ ...data, range: "7d" });
    expect(html).toContain("Last 7 days");
    expect(html).toContain("7 days</button>");
    expect(html).toContain("Sell-through rate");
    expect(html).toContain("66.7%");
    expect(html).toContain("Sales in this period ÷ (sales in this period + active listings today)");
    expect(render({ ...data, sell_through_rate: null })).not.toContain("null%");
  });
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

  it("lists stale stock with how deep to cut, and tags event sales", () => {
    const html = render(data);
    expect(html).toContain("Discount deeper");
    expect(html).toContain("40% off → $36");
    expect(html).toContain("lowest $10");
    expect(html).toContain("Keep full price");
    expect(html).toContain("Depop fall sale");
    expect(html).toContain("No sale events yet.");
  });

  it("withholds comparisons when prices or costs are missing", () => {
    const html = render({ ...data, sales: { ...sales, revenue_known: 1, profit_known: 1, fees_known: 0 } });
    expect(html).toContain("Comparison unavailable: missing prices");
    expect(html).toContain("Comparison unavailable: missing costs or fees");
    expect(html).toContain("1 sale has no recorded price");
    expect(html).not.toContain("Up $40");
    expect(html).not.toContain("undefined");
  });

  it("shows margins, chart choices, ranking controls, inventory cost, and oldest listings", () => {
    const html = render(data);
    expect(html).toContain("Profit margin");
    expect(html).toContain("62.5%");
    expect(html).toContain('aria-label="Chart metric"');
    expect(html).toContain('aria-label="Rank brands by"');
    expect(html).toContain("Recorded inventory cost");
    expect(html).toContain("Listed 90+ days");
    expect(html).toContain("Review your oldest listings");
    expect(html).toContain("110 days listed");
    expect(html).toContain("$12 profit");
  });

  it("keeps unknown prices and profits distinct from recorded zero amounts", () => {
    const html = render({ ...data, recent: [
      { ...data.recent[0], price: null, profit: null },
      { ...data.recent[0], conversation_id: "free", price: 0, profit: 0 },
    ] });
    expect(html).toContain("Price unknown");
    expect(html).toContain("Profit unavailable");
    expect(html).toContain("$0 profit");
    expect(html).not.toContain("undefined");
  });

  it("does not show previous-period comparisons for all time", () => {
    const html = render({ ...data, range: "all", previous: null });
    expect(html).not.toContain("Compared with");
    expect(html).not.toContain("Up $40");
    expect(html).toContain("Included in totals, but excluded from the chart");
  });
});
