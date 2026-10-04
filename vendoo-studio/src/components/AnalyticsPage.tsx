import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AnalyticsGroup, AnalyticsRange, AnalyticsSales, AnalyticsStaleListing, InventoryAnalytics } from "../api/types";
import { formatChange, formatDays, formatMoney } from "./analyticsFormat";
import { marketplaceName } from "./marketplaceNames";
import { SaleEvents } from "./SaleEvents";

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
          <div className="analytics-title-row">
            <h1>Analytics</h1>
            <button type="button" className="pr-pill" disabled={query.isFetching} onClick={() => void query.refetch()}>
              Refresh
            </button>
          </div>
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
              <PerformanceList title="Marketplaces" rows={data.marketplaces} marketplace />
              <PerformanceList title="Categories" rows={data.categories} />
              <PerformanceList title="Brands" rows={data.brands} />
            </div>

            <section className="analytics-section" aria-label="Inventory today">
              <h2 className="analytics-section-title">Inventory today</h2>
              <p className="analytics-note">Current active listings, across all sales periods.</p>
              <div className="analytics-stats">
                <Stat label="Active listings" value={String(data.inventory.active)} />
                <Stat label="Asking value" value={formatMoney(data.inventory.asking_value)} hint="Total asking prices; potential revenue" />
                <Stat label="Recorded inventory cost" value={data.inventory.cost_known ? formatMoney(data.inventory.cost_value) : "—"} hint={`Cost recorded on ${data.inventory.cost_known} of ${data.inventory.active} active listings`} />
                <Stat label="Listed 90+ days" value={String(data.inventory.stale_count)} hint={`${formatMoney(data.inventory.stale_value)} at asking prices`} />
              </div>
              {data.inventory.undated_count > 0 ? <p className="analytics-note">{data.inventory.undated_count} active {data.inventory.undated_count === 1 ? "listing has" : "listings have"} no list date and cannot be aged.</p> : null}
            </section>

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

            <DiscountDeeper listings={data.stale} onOpenListing={onOpenListing} />

            <SaleEvents onOpenListing={onOpenListing} />

            <section className="analytics-section" aria-label="Oldest active listings">
              <h2 className="analytics-section-title">Review your oldest listings</h2>
              <p className="analytics-note">Up to 8 listings that have been active for 90+ days. Open one to review its price, photos, or details.</p>
              {data.oldest.length === 0 ? <p className="analytics-note">No active listings with a recorded list date are 90+ days old.</p> : (
                <ul className="analytics-recent">
                  {data.oldest.map((item) => (
                    <li key={item.conversation_id}>
                      <button type="button" className="analytics-recent-row" onClick={() => onOpenListing(item.conversation_id)}>
                        <span className="analytics-recent-title">{item.title}</span>
                        <span className="analytics-recent-meta">{formatDays(item.days_listed)} listed</span>
                        <span className="analytics-recent-price">{formatMoney(item.price)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
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
                          {sale.event ? ` · ${sale.event}` : ""}
                        </span>
                        <span className="analytics-recent-price">
                          {sale.price == null ? "Price unknown" : formatMoney(sale.price)}
                          <small>{sale.profit == null ? "Profit unavailable" : `${formatMoney(sale.profit)} profit`}</small>
                        </span>
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

/**
 * Listings 60+ days old with no sale: the ones to cut past the everyday 25% in
 * the next sale event, as deep as their cost after fees allows.
 */
function DiscountDeeper({
  listings,
  onOpenListing,
}: {
  listings: AnalyticsStaleListing[];
  onOpenListing: (id: string) => void;
}) {
  return (
    <section className="analytics-section" aria-label="Discount deeper">
      <h2 className="analytics-section-title">Discount deeper</h2>
      <p className="analytics-note">
        Active listings up 60 days or more, oldest first. Give these 35–40% off in the next sale instead of 25%, as deep
        as still covers what the item cost after 20% fees. Items with no cost recorded get 35%.
      </p>
      {listings.length === 0 ? (
        <p className="analytics-note">Nothing has been listed 60 days without selling.</p>
      ) : (
        <ul className="analytics-recent analytics-stale">
          {listings.map((listing) => (
            <li key={listing.conversation_id}>
              <button type="button" className="analytics-recent-row" onClick={() => onOpenListing(listing.conversation_id)}>
                <span className="analytics-recent-title">{listing.title}</span>
                <span className="analytics-recent-meta">
                  {formatDays(listing.days_listed)} · {formatMoney(listing.price)}
                  {listing.lowest_price != null ? ` · lowest ${formatMoney(listing.lowest_price)}` : ""}
                </span>
                <span className="analytics-recent-price">
                  {listing.discount_percent == null || listing.sale_price == null
                    ? "Keep full price"
                    : `${listing.discount_percent}% off → ${formatMoney(listing.sale_price)}`}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
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
      <Stat label="Profit margin" value={sales.margin == null ? "—" : `${sales.margin}%`} hint="Profit ÷ revenue on sales with recorded cost" negative={sales.margin != null && sales.margin < 0} />
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
  const [metric, setMetric] = useState<"revenue" | "count" | "profit">("revenue");
  const peak = Math.max(...periods.map((period) => Math.abs(period[metric] ?? 0)), 0);
  const hasLoss = periods.some((period) => (period[metric] ?? 0) < 0);
  const baseline = hasLoss ? 60 : 0;
  const available = hasLoss ? 60 : 120;
  const metricName = metric === "count" ? "Sales" : metric === "profit" ? "Profit" : "Revenue";
  const peakCount = Math.max(...periods.map((period) => period.count), 0);
  if (periods.length === 0 || peakCount === 0) {
    return <p className="analytics-note">No dated sales in this period.</p>;
  }
  return (
    <>
      <div className="pr-pills analytics-chart-controls" role="group" aria-label="Chart metric">
        {(["revenue", "count", "profit"] as const).map((value) => (
          <button
            key={value}
            type="button"
            className={`pr-pill${metric === value ? " is-active" : ""}`}
            aria-pressed={metric === value}
            onClick={() => setMetric(value)}
          >
            {value === "revenue" ? "Revenue" : value === "profit" ? "Profit" : "Sales"}
          </button>
        ))}
      </div>
      {metric === "profit" ? <p className="analytics-note">Profit uses sales with recorded cost and deducts recorded fees and shipping. Missing costs appear as —; loss bars extend below zero.</p> : null}
      <div className="analytics-chart" role="list" aria-label={`${metricName} over time`}>
        {periods.map((period, index) => {
          const value = period[metric];
          const share = peak > 0 ? Math.abs(value ?? 0) / peak : 0;
          const height = share > 0 ? Math.max(Math.round(share * available), 2) : 0;
          const detail = `${period.label}: ${formatMoney(period.revenue)}, ${saleCount(period.count)}, ${period.profit == null ? "profit unavailable" : `${formatMoney(period.profit)} profit`}. Cost on ${period.profit_known} of ${period.count}; fees on ${period.fees_known} of ${period.profit_known}.`;
          return (
            <div
              key={`${period.label}-${index}`}
              className="analytics-bar-col"
              role="listitem"
              tabIndex={0}
              aria-label={detail}
              title={detail}
            >
              <span className="analytics-bar-value" aria-hidden="true">
                {value == null ? "—" : metric === "count" ? value : formatMoney(value)}
              </span>
              <div className="analytics-plot" aria-hidden="true">
                <div className="analytics-zero" style={{ bottom: `${baseline}px` }} />
                <div className={`analytics-bar${(value ?? 0) < 0 ? " is-negative" : ""}`} style={{ height: `${height}px`, bottom: `${(value ?? 0) < 0 ? baseline - height : baseline}px` }} />
              </div>
              <span className="analytics-bar-label">{period.label}</span>
            </div>
          );
        })}
      </div>
    </>
  );
}

function PerformanceList({ title, rows, marketplace = false }: {
  title: string;
  rows: AnalyticsGroup[];
  marketplace?: boolean;
}) {
  const [metric, setMetric] = useState<"revenue" | "profit" | "count">("revenue");
  const ranked = [...rows].sort((a, b) => {
    const first = a[metric];
    const second = b[metric];
    if (first == null) return second == null ? a.label.localeCompare(b.label) : 1;
    if (second == null) return -1;
    return second - first || a.label.localeCompare(b.label);
  }).slice(0, 6);
  return (
    <section className="analytics-section" aria-label={title}>
      <div className="analytics-title-row">
        <h2 className="analytics-section-title">{title}</h2>
        <select aria-label={`Rank ${title.toLowerCase()} by`} value={metric} onChange={(event) => setMetric(event.target.value as typeof metric)}>
          <option value="revenue">Revenue</option>
          <option value="profit">Profit</option>
          <option value="count">Sales</option>
        </select>
      </div>
      {ranked.length === 0 ? <p className="analytics-note">No {title.toLowerCase()} recorded on sales in this period.</p> : (
        <ol className="analytics-ranks">
          {ranked.map((row) => (
            <li key={row.id} className="analytics-rank">
              <span className="analytics-rank-label">
                {marketplace ? marketplaceName(row.id) : row.label}
                <small>{saleCount(row.count)}{row.median_days != null ? ` · ${formatDays(row.median_days)} median` : ""}</small>
              </span>
              <span className="analytics-rank-value">
                {metric === "count" ? row.count : row[metric] == null ? "—" : formatMoney(row[metric])}
                {metric === "profit" ? <small>{row.profit_known === 0 ? "Cost missing" : `Cost on ${row.profit_known}/${row.count} · fees on ${row.fees_known}/${row.profit_known}`}</small> : null}
              </span>
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
