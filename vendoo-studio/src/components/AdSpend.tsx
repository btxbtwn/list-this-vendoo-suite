import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AdMarketplace, AdMarketplaceTotals, AdSpendEntry, AdSpendInput, AnalyticsAds } from "../api/adSpend";
import { confirmDialog } from "../ui/confirmDialog";
import { formatMoney } from "./analyticsFormat";
import { Stat } from "./AnalyticsStat";
import { marketplaceName } from "./marketplaceNames";
import "../styles/ad-spend.css";

const MARKETS: AdMarketplace[] = ["poshmark", "etsy"];
const PROGRAMS: Record<AdMarketplace, string> = { poshmark: "Promoted Closet", etsy: "Etsy Ads" };
const ADS_QUERY_KEY = ["ad-spend"];

/**
 * Poshmark Promoted Closet and Etsy Ads, set against what sold. Neither shares
 * its figures with Vendoo, so the seller copies each dashboard for the dates
 * it covers; the totals here follow the page's sales period.
 */
export function AdSpend({ ads, heading }: { ads: AnalyticsAds; heading: string }) {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ADS_QUERY_KEY, queryFn: api.adSpend.list });
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ADS_QUERY_KEY }),
    queryClient.invalidateQueries({ queryKey: ["analytics"] }),
  ]);
  const remove = useMutation({ mutationFn: api.adSpend.remove, onSuccess: refresh });
  const [editing, setEditing] = useState<AdSpendEntry | "new" | null>(null);

  const onRemove = async (entry: AdSpendEntry) => {
    const ok = await confirmDialog(
      `Remove ${formatMoney(entry.spend)} of ${PROGRAMS[entry.marketplace]} spend from ${formatRange(entry)}?`,
      { variant: "destructive", confirmLabel: "Remove" },
    );
    if (ok) remove.mutate(entry.id);
  };

  return (
    <section className="analytics-section ad-spend" aria-label="Ads">
      <div className="analytics-title-row">
        <h2 className="analytics-section-title">Ads</h2>
        {editing == null ? <button type="button" className="pr-pill" onClick={() => setEditing("new")}>Add ad spend</button> : null}
      </div>
      <p className="analytics-note">
        Poshmark Promoted Closet and Etsy Ads don't share their numbers with Vendoo. Copy what each dashboard shows
        for a week or a month: the spend, and if you like the clicks, orders, and sales it credits to the ads.
      </p>
      {editing != null ? (
        <AdSpendForm
          key={editing === "new" ? "new" : editing.id}
          entry={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => { await refresh(); setEditing(null); }}
        />
      ) : null}

      {ads.marketplaces.length > 0 ? (
        <>
          <h3 className="ad-spend-heading">{heading}</h3>
          <div className="analytics-stats">
            <Stat label="Ad spend" value={formatMoney(ads.spend)} hint="Spread evenly over the days each entry covers" />
            <Stat
              label="Profit after ads"
              value={ads.profit_after_ads == null ? "—" : formatMoney(ads.profit_after_ads)}
              negative={ads.profit_after_ads != null && ads.profit_after_ads < 0}
              hint={ads.profit_after_ads == null ? "Record sale prices and costs to see profit" : "Profit on sales with recorded cost, less all ad spend"}
            />
            {ads.marketplaces.map((market) => <MarketStat key={market.id} market={market} />)}
          </div>
        </>
      ) : null}

      {query.isError ? <p className="analytics-note">{(query.error as Error).message}</p> : null}
      {remove.isError ? <p className="ad-spend-error" role="alert">{remove.error.message}</p> : null}
      {query.data?.length === 0 && editing == null ? <p className="analytics-note">No ad spend recorded yet.</p> : null}
      {query.data?.length ? (
        <ul className="analytics-recent ad-spend-entries">
          {query.data.map((entry) => (
            <li key={entry.id} className="ad-spend-entry">
              <span className="analytics-recent-title">
                {PROGRAMS[entry.marketplace]}
                <small>{formatRange(entry)}{entry.notes ? ` · ${entry.notes}` : ""}</small>
              </span>
              <span className="analytics-recent-meta">{entryFigures(entry)}</span>
              <span className="analytics-recent-price">{formatMoney(entry.spend)}</span>
              <span className="ad-spend-actions">
                <button type="button" className="pr-pill" onClick={() => setEditing(entry)}>Edit</button>
                <button type="button" className="pr-pill" disabled={remove.isPending} onClick={() => void onRemove(entry)}>Remove</button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function MarketStat({ market }: { market: AdMarketplaceTotals }) {
  const parts = [
    market.roas != null ? `${market.roas}× return on ad spend` : null,
    market.cost_per_click != null ? `${formatMoney(market.cost_per_click)} a click` : null,
    market.spend_percent != null
      ? `${market.spend_percent}% of ${formatMoney(market.sales_revenue)} ${marketplaceName(market.id)} sales`
      : `No ${marketplaceName(market.id)} sales recorded`,
  ];
  return (
    <Stat
      label={PROGRAMS[market.id as AdMarketplace] ?? marketplaceName(market.id)}
      value={formatMoney(market.spend)}
      hint={parts.filter(Boolean).join(" · ")}
    />
  );
}

function AdSpendForm({
  entry,
  onClose,
  onSaved,
}: {
  entry: AdSpendEntry | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [market, setMarket] = useState<AdMarketplace>(entry?.marketplace ?? "poshmark");
  const [start, setStart] = useState(entry?.start_date ?? "");
  const [end, setEnd] = useState(entry?.end_date ?? "");
  const [spend, setSpend] = useState(entry ? String(entry.spend) : "");
  const [clicks, setClicks] = useState(optional(entry?.clicks));
  const [orders, setOrders] = useState(optional(entry?.orders));
  const [revenue, setRevenue] = useState(optional(entry?.revenue));
  const [notes, setNotes] = useState(entry?.notes ?? "");
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: (input: AdSpendInput) => entry ? api.adSpend.update(entry.id, input) : api.adSpend.create(input),
    onSuccess: onSaved,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (end < start) { setError("End date must be on or after the start date."); return; }
    save.mutate({
      marketplace: market,
      start_date: start,
      end_date: end,
      spend: Number(spend),
      clicks: clicks.trim() ? Number(clicks) : null,
      orders: orders.trim() ? Number(orders) : null,
      revenue: revenue.trim() ? Number(revenue) : null,
      notes,
    });
  }

  return (
    <form className="ad-spend-form" onSubmit={submit} aria-label={entry ? "Edit ad spend" : "Add ad spend"}>
      <div className="analytics-title-row">
        <h3>{entry ? "Edit ad spend" : "Add ad spend"}</h3>
        <button type="button" className="pr-pill" disabled={save.isPending} onClick={onClose}>Close</button>
      </div>
      <fieldset disabled={save.isPending}>
        <div className="ad-spend-fields">
          <label>Ads<select autoFocus value={market} onChange={(e) => setMarket(e.target.value as AdMarketplace)}>
            {MARKETS.map((value) => <option key={value} value={value}>{marketplaceName(value)} {PROGRAMS[value]}</option>)}
          </select></label>
          <label>Start date<input type="date" required value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label>End date (inclusive)<input type="date" required min={start} value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          <label>Spend ($)<input type="number" required min={0} step="0.01" value={spend} onChange={(e) => setSpend(e.target.value)} /></label>
          <label>Clicks<input type="number" min={0} step="1" placeholder="Optional" value={clicks} onChange={(e) => setClicks(e.target.value)} /></label>
          <label>Orders from ads<input type="number" min={0} step="1" placeholder="Optional" value={orders} onChange={(e) => setOrders(e.target.value)} /></label>
          <label>Sales from ads ($)<input type="number" min={0} step="0.01" placeholder="Optional" value={revenue} onChange={(e) => setRevenue(e.target.value)} /></label>
        </div>
        <label className="ad-spend-notes">Notes<textarea maxLength={2000} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
        {error || save.isError ? <p className="ad-spend-error" role="alert">{error || save.error?.message}</p> : null}
        <button type="submit" className="pr-pill" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</button>
      </fieldset>
    </form>
  );
}

function entryFigures(entry: AdSpendEntry): string {
  return [
    entry.clicks != null ? `${entry.clicks} ${entry.clicks === 1 ? "click" : "clicks"}` : null,
    entry.orders != null ? `${entry.orders} ${entry.orders === 1 ? "order" : "orders"}` : null,
    entry.revenue != null ? `${formatMoney(entry.revenue)} sales` : null,
    entry.roas != null ? `${entry.roas}× ROAS` : null,
  ].filter(Boolean).join(" · ");
}

function formatRange(entry: Pick<AdSpendEntry, "start_date" | "end_date">): string {
  const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  return entry.start_date === entry.end_date ? day(entry.start_date) : `${day(entry.start_date)} – ${day(entry.end_date)}`;
}

function optional(value: number | null | undefined): string {
  return value == null ? "" : String(value);
}
