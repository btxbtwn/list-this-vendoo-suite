import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { InventoryAnalytics, VendooBulkImport } from "../api/types";
import { AnalyticsPage } from "./AnalyticsPage";

const { useQuery, useMutation } = vi.hoisted(() => ({ useQuery: vi.fn(), useMutation: vi.fn() }));
vi.mock("@tanstack/react-query", () => ({
  useQuery,
  keepPreviousData: vi.fn(),
  useMutation,
  useQueryClient: () => ({ setQueryData: vi.fn(), invalidateQueries: vi.fn() }),
}));

const sales = {
  count: 2, revenue: 80, revenue_known: 2, profit: 50,
  profit_known: 2, fees_known: 2, average_price: 40, median_days: 10, days_known: 2, margin: 62.5,
};
const data: InventoryAnalytics = {
  range: "30d", undated_sales: 1, periods_truncated: false,
  last_updated_at: "2026-10-05T12:30:00Z", incomplete_sales: [],
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
  ads: { spend: 0, profit_after_ads: 50, marketplaces: [] },
};

function render(
  payload: InventoryAnalytics,
  run: Partial<VendooBulkImport> = { running: false },
  starting = false,
) {
  useMutation.mockReturnValue({ mutate: vi.fn(), isPending: starting });
  useQuery.mockImplementation(({ queryKey }: { queryKey: readonly string[] }) =>
    queryKey[0] === "vendoo-bulk-import" ? { data: run }
      : { data: payload, isLoading: false, isError: false, isFetching: false },
  );
  return renderToStaticMarkup(<AnalyticsPage onOpenListing={vi.fn()} />);
}

describe("AnalyticsPage", () => {
  it("shows the last completed Vendoo sync and offers a real resync", () => {
    const html = render(data);
    expect(html).toContain("Last updated on");
    expect(html).toContain('dateTime="2026-10-05T12:30:00Z"');
    expect(html).toContain("Resync Vendoo data");
    expect(html).not.toContain("Refresh</button>");
    expect(render({ ...data, last_updated_at: null })).toContain("Last updated on: not recorded yet.");
  });

  it("shows sync progress and a stop control instead of starting a second sync", () => {
    const html = render(data, { running: true, total: 20, processed: 5, photos: 2 });
    expect(html).toContain("Syncing 5 of 20 · 2 photos");
    expect(html).toContain('role="status"');
    expect(html).toContain("Stop</button>");
    expect(html).not.toContain("Resync Vendoo data</button>");
    const pending = render(data, { running: false }, true);
    expect(pending).toContain('aria-busy="true" disabled=""');
    expect(pending).toContain("Starting sync…");
  });

  it("reminds the seller to complete missing sales details across all time", () => {
    const html = render({ ...data, incomplete_sales: [
      { conversation_id: "undated", title: "Undated jacket", missing: ["sale date", "sale price", "fees"] },
      { conversation_id: "old", title: "Old boots", missing: ["cost"] },
    ] });
    expect(html).toContain("2 sales need sales data");
    expect(html).toContain("Across all time");
    expect(html).toContain("Add the missing details in Vendoo, then resync");
    expect(html).toContain("Undated jacket");
    expect(html).toContain("Missing sale date, sale price, fees");
    expect(html).toContain("Old boots");
    expect(html).not.toContain("undefined");
    expect(render(data)).not.toContain('aria-label="Missing sales data"');
    expect(render({ ...data, incomplete_sales: [
      { conversation_id: "one", title: "Single sale", missing: ["marketplace"] },
    ] })).toContain("1 sale needs sales data");
  });

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
    expect(html).toContain("Depop fall sale");
    expect(html).not.toContain("Sale calendar");
    expect(html).not.toContain("Add ad spend");
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
