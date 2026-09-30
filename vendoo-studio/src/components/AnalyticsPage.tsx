import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AnalyticsRange, AnalyticsSales, InventoryAnalytics } from "../api/types";
import { formatChange, formatDays, formatMoney } from "./analyticsFormat";
import { marketplaceName } from "./marketplaceNames";

const RANGES: { id: AnalyticsRange; label: string; heading: string }[] = [
  { id: "30d", label: "30 days", heading: "Last 30 days" },
  { id: "90d", label: "90 days", heading: "Last 90 days" },
  { id: "12m", label: "12 months", heading: "Last 12 months" },
  { id: "all", label: "All", heading: "All time" },
];

interface Props {
  onOpenListing: (id: string) => void;
}

export function AnalyticsPage({ onOpenListing }: Props) {
  const [range, setRange] = useState<AnalyticsRange>("12m");
  const query = useQuery({
    queryKey: ["analytics", range],
    queryFn: () => api.analytics.get(range),
    placeholderData: keepPreviousData,
  });
  const data = query.data;
  const heading = RANGES.find((item) => item.id === (data?.range ?? range))?.heading ?? "Sales";

  return (
    <div className="analytics-page">
      <div className="analytics-inner">
        <header className="analytics-header">
          <p className="analytics-lead">
            Sales and inventory from the listings imported from Vendoo.
          </p>
          {data ? <InventoryStrip inventory={data.inventory} /> : null}
          <div className="pr-pills" role="tablist" aria-label="Sales period">
            {RANGES.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={range === item.id}
                className={`pr-pill${range === item.id ? " is-active" : ""}`}
                onClick={() => setRange(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </header>

        {query.isLoading && !data ? <p className="analytics-status">Loading analytics…</p> : null}
        {query.isFetching && data ? <p className="analytics-status" role="status">Updating analytics…</p> : null}
        {query.isError ? (
          <p className="analytics-status">
            {(query.error as Error).message || "Could not load analytics."}
          </p>
        ) : null}

        {data ? (
          <>
            <section className="analytics-section" aria-label={heading}>
              <h2 className="analytics-section-title">{heading}</h2>
              <SalesStats data={data} />
              {data.previous ? (
                <p className="analytics-note analytics-comparison-period">
                  Compared with {formatSold(data.previous.start)} – {formatSold(data.previous.end)}
                  {" (previous period, same length)."}
                </p>
              ) : null}
              {data.sales.revenue_known < data.sales.count ? (
                <p className="analytics-note">
                  {data.sales.count - data.sales.revenue_known} {data.sales.count - data.sales.revenue_known === 1 ? "sale has" : "sales have"} no recorded price.
                  Revenue, averages, and breakdowns include recorded amounts only.
                </p>
              ) : null}
              {data.undated_sales > 0 ? (
                <p className="analytics-note">
                  {data.undated_sales} {data.undated_sales === 1 ? "sale has" : "sales have"} no date.
                  {data.range === "all"
                    ? " Included in totals, but excluded from the chart."
                    : " Excluded from this period; included in All time."}
                </p>
              ) : null}
              {data.periods_truncated ? (
                <p className="analytics-note">The chart shows the latest 18 months.</p>
              ) : null}
              <SalesChart periods={data.periods} />
            </section>

            <div className="analytics-split">
              <RankList
                title="Marketplaces"
                empty="No sales in this period."
                rows={data.marketplaces.map((row) => ({
                  key: row.id,
                  label: marketplaceName(row.id),
                  detail: saleCount(row.count),
                  value: formatMoney(row.revenue),
                }))}
              />
              <RankList
                title="Categories"
                empty="No sales in this period."
                rows={data.categories.map((row) => ({
                  key: row.id || row.label,
                  label: row.label,
                  detail: saleCount(row.count),
                  value: formatMoney(row.revenue),
                }))}
              />
            </div>

            <RankList
              title="Brands"
              empty="No brand on the sales in this period."
              rows={data.brands.map((row) => ({
                key: row.id || row.label,
                label: row.label,
                detail: saleCount(row.count),
                value: formatMoney(row.revenue),
              }))}
            />

            <section className="analytics-section" aria-label="Active listings">
              <h2 className="analytics-section-title">Current inventory by age</h2>
              <p className="analytics-note">All active listings, regardless of the sales period. Open an age group to review its listings.</p>
              {data.aging.length === 0 ? (
                <p className="analytics-note">No active listings.</p>
              ) : (
                <div className="analytics-aging">
                  {data.aging.map((row) => (
                    <details key={row.label} className="analytics-age-group">
                      <summary className="analytics-rank">
                        <span className="analytics-rank-label">{row.label}</span>
                        <span className="analytics-age-count">{row.count} listings</span>
                        <span className="analytics-rank-value">{formatMoney(row.asking_value)} asking</span>
                      </summary>
                      <ul className="analytics-recent analytics-age-listings">
                        {row.listings.map((listing) => (
                          <li key={listing.conversation_id}>
                            <button type="button" className="analytics-recent-row" onClick={() => onOpenListing(listing.conversation_id)}>
                              <span className="analytics-recent-title">{listing.title}</span>
                              <span className="analytics-recent-meta">
                                {listing.days_listed == null ? "No list date" : formatDays(listing.days_listed)}
                              </span>
                              <span className="analytics-recent-price">{formatMoney(listing.price)}</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    </details>
                  ))}
                </div>
              )}
            </section>

            <section className="analytics-section" aria-label="Recent sales">
              <h2 className="analytics-section-title">Recent sales</h2>
              {data.recent.length === 0 ? (
                <p className="analytics-note">No sales in this period.</p>
              ) : (
                <ul className="analytics-recent">
                  {data.recent.map((sale) => (
                    <li key={sale.conversation_id}>
                      <button
                        type="button"
                        className="analytics-recent-row"
                        onClick={() => onOpenListing(sale.conversation_id)}
                      >
                        <span className="analytics-recent-title">{sale.title}</span>
                        <span className="analytics-recent-meta">
                          {marketplaceName(sale.marketplace)}
                          {sale.sold_at ? ` · ${formatSold(sale.sold_at)}` : ""}
                          {sale.days_listed != null ? ` · ${formatDays(sale.days_listed)}` : ""}
                        </span>
                        <span className="analytics-recent-price">{sale.price == null ? "Price unknown" : formatMoney(sale.price)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}

function InventoryStrip({ inventory }: { inventory: InventoryAnalytics["inventory"] }) {
  const parts = [
    `${inventory.active} active`,
    `${formatMoney(inventory.asking_value)} asking`,
  ];
  if (inventory.draft) parts.push(`${inventory.draft} draft${inventory.draft === 1 ? "" : "s"}`);
  if (inventory.sold) parts.push(`${inventory.sold} sold`);
  if (inventory.failed) parts.push(`${inventory.failed} failed`);
  if (inventory.working) parts.push(`${inventory.working} in progress`);
  return <p className="analytics-inventory">Current inventory: {parts.join(" · ")}</p>;
}

function profitHint(sales: AnalyticsSales): string {
  if (sales.profit_known === 0) return "Record sale prices and costs to see profit";
  const scope =
    sales.profit_known === sales.count ? "" : ` on ${sales.profit_known} of ${sales.count} sales`;
  if (sales.fees_known === 0) return `After recorded costs and shipping${scope}. Fees missing`;
  if (sales.fees_known === sales.profit_known) return `After recorded cost, fees and shipping${scope}`;
  return `After recorded cost, fees and shipping${scope}. Fees recorded on ${sales.fees_known} of ${sales.profit_known}`;
}

function SalesStats({ data }: { data: InventoryAnalytics }) {
  const sales = data.sales;
  const profit = sales.profit;
  const previous = data.previous?.sales;
  const revenueComplete = previous && sales.revenue_known === sales.count && previous.revenue_known === previous.count;
  const profitComplete = previous && sales.profit_known === sales.count && previous.profit_known === previous.count
    && sales.fees_known === sales.count && previous.fees_known === previous.count;
  return (
    <div className="analytics-stats">
      <Stat label="Revenue" value={formatMoney(sales.revenue)}
        hint={`${sales.revenue_known} of ${sales.count} sales with recorded prices`}
        change={previous ? (revenueComplete ? formatChange(sales.revenue, previous.revenue, formatMoney) : "Comparison unavailable: missing prices") : undefined}
      />
      <Stat
        label="Sold"
        change={previous ? formatChange(sales.count, previous.count, String) : undefined}
        value={String(sales.count)}
        hint={sales.average_price == null ? undefined : `${formatMoney(sales.average_price)} average`}
      />
      <Stat
        label="Profit"
        value={profit == null ? "—" : formatMoney(profit)}
        negative={profit != null && profit < 0}
        hint={profitHint(sales)}
        change={previous ? (profitComplete ? formatChange(profit, previous.profit, formatMoney) : "Comparison unavailable: missing costs or fees") : undefined}
      />
      <Stat
        label="Median time to sell"
        value={sales.median_days == null ? "—" : formatDays(sales.median_days)}
        hint={`Based on ${sales.days_known} of ${sales.count} sales`}
        change={previous ? formatChange(sales.median_days, previous.median_days, formatDays) : undefined}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  change,
  negative = false,
}: {
  label: string;
  value: string;
  hint?: string;
  change?: string;
  negative?: boolean;
}) {
  return (
    <div className="analytics-stat">
      <div className="analytics-stat-label">{label}</div>
      <div className={`analytics-stat-value${negative ? " is-negative" : ""}`}>{value}</div>
      {hint ? <div className="analytics-stat-hint">{hint}</div> : null}
      {change ? <div className="analytics-stat-change">{change}</div> : null}
    </div>
  );
}

function SalesChart({ periods }: { periods: InventoryAnalytics["periods"] }) {
  const peakRevenue = Math.max(...periods.map((period) => period.revenue), 0);
  const peakCount = Math.max(...periods.map((period) => period.count), 0);
  if (periods.length === 0 || peakCount === 0) {
    return <p className="analytics-note">No dated sales in this period.</p>;
  }
  return (
    <div className="analytics-chart" role="img" aria-label="Recorded revenue over time">
      {periods.map((period, index) => {
        const share = peakRevenue > 0 ? period.revenue / peakRevenue : 0;
        const height = share > 0 ? Math.max(Math.round(share * 120), 4) : 0;
        return (
          <div key={`${period.label}-${index}`} className="analytics-bar-col">
            <div
              className="analytics-bar"
              style={{ height: `${height}px` }}
              title={`${period.label}: ${formatMoney(period.revenue)}, ${saleCount(period.count)}`}
            />
            <span className="analytics-bar-label">{period.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function RankList({
  title,
  empty,
  rows,
}: {
  title: string;
  empty: string;
  rows: { key: string; label: string; detail: string; value: string }[];
}) {
  return (
    <section className="analytics-section" aria-label={title}>
      <h2 className="analytics-section-title">{title}</h2>
      {rows.length === 0 ? (
        <p className="analytics-note">{empty}</p>
      ) : (
        <ol className="analytics-ranks">
          {rows.map((row) => (
            <li key={row.key} className="analytics-rank">
              <span className="analytics-rank-label">{row.label}</span>
              <span className="analytics-rank-meta">{row.detail}</span>
              <span className="analytics-rank-value">{row.value}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function saleCount(count: number): string {
  return count === 1 ? "1 sale" : `${count} sales`;
}

function formatSold(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
