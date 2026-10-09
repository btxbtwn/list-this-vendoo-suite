import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AdSpendEntry } from "../api/adSpend";
import type { InventoryAnalytics } from "../api/types";
import { MarketingPage } from "./MarketingPage";

const { useQuery, useMutation } = vi.hoisted(() => ({ useQuery: vi.fn(), useMutation: vi.fn() }));
vi.mock("@tanstack/react-query", () => ({
  useQuery,
  keepPreviousData: vi.fn(),
  useMutation,
  useQueryClient: () => ({ setQueryData: vi.fn(), invalidateQueries: vi.fn() }),
}));

/** The page reads only stale stock and ad totals from the analytics payload. */
type MarketingData = Pick<InventoryAnalytics, "stale" | "ads">;

const data: MarketingData = {
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
  ads: { spend: 0, profit_after_ads: 50, marketplaces: [] },
};

const adEntry: AdSpendEntry = {
  id: "posh-week", marketplace: "poshmark", start_date: "2026-09-01", end_date: "2026-09-07",
  spend: 15, clicks: 60, orders: 1, revenue: 45, notes: "", roas: 3, cost_per_click: 0.25,
};

function render(payload: MarketingData, adEntries: AdSpendEntry[] = []) {
  useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false });
  useQuery.mockImplementation(({ queryKey }: { queryKey: readonly string[] }) =>
    queryKey[0] === "sale-calendar"
      ? { data: { events: [], patterns: [], items: [], timezone: "UTC" }, isError: false }
      : queryKey[0] === "ad-spend" ? { data: adEntries, isError: false }
      : { data: payload, isLoading: false, isError: false, isFetching: false },
  );
  return renderToStaticMarkup(<MarketingPage onOpenListing={vi.fn()} />);
}

describe("MarketingPage", () => {
  it("holds the sale calendar and lists stale stock with how deep to cut", () => {
    const html = render(data);
    expect(html).toContain("<h1>Marketing</h1>");
    expect(html).toContain("Sale calendar");
    expect(html).toContain("No events here yet. Select a day and plan a sale.");
    expect(html).toContain("Discount deeper");
    expect(html).toContain("40% off → $36");
    expect(html).toContain("lowest $10");
    expect(html).toContain("Keep full price");
  });

  it("invites ad spend before any is recorded and hides empty ad totals", () => {
    const html = render(data);
    expect(html).toContain("Add ad spend");
    expect(html).toContain("No ad spend recorded yet.");
    expect(html).not.toContain("Profit after ads");
    expect(html).not.toContain('aria-label="Ad spend period"');
  });

  it("keeps the period picker when the chosen period has no ad spend", () => {
    const html = render(data, [adEntry]);
    expect(html).toContain('aria-label="Ad spend period"');
    expect(html).toContain("No ad spend in this period.");
    expect(html).not.toContain("No ad spend recorded yet.");
  });

  it("sets Promoted Closet and Etsy Ads spend against the period's sales", () => {
    const html = render({
      ...data,
      ads: {
        spend: 40,
        profit_after_ads: 10,
        marketplaces: [
          { id: "poshmark", entries: 1, spend: 15, clicks: 60, orders: 1, revenue: 45, roas: 3,
            cost_per_click: 0.25, sales_revenue: 80, spend_percent: 18.8 },
          { id: "etsy", entries: 1, spend: 25, clicks: null, orders: null, revenue: null, roas: null,
            cost_per_click: null, sales_revenue: 0, spend_percent: null },
        ],
      },
    }, [adEntry]);
    expect(html).toContain('aria-label="Ad spend period"');
    expect(html).toContain("Profit after ads");
    expect(html).toContain("$10");
    expect(html).toContain("3× return on ad spend · $0.25 a click · 18.8% of $80 Poshmark sales");
    expect(html).toContain("No Etsy sales recorded");
    expect(html).toContain("60 clicks · 1 order · $45 sales · 3× ROAS");
    expect(html).not.toContain("No ad spend recorded yet.");
    expect(html).not.toContain("No ad spend in this period.");
  });
});
