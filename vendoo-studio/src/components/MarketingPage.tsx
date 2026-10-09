import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AnalyticsStaleListing } from "../api/types";
import { formatDays, formatMoney } from "./analyticsFormat";
import { AdSpend } from "./AdSpend";
import { SaleCalendar } from "./SaleCalendar";

interface Props {
  onOpenListing: (id: string) => void;
}

/** Sales events and paid ads: what the seller runs to move stock, beside what it earned. */
export function MarketingPage({ onOpenListing }: Props) {
  // Stale stock does not depend on the sales period; this shares Ads' default query.
  const query = useQuery({ queryKey: ["analytics", "12m"], queryFn: () => api.analytics.get("12m") });

  return (
    <div className="analytics-page">
      <div className="analytics-inner">
        <header className="analytics-header">
          <h1>Marketing</h1>
          <p className="analytics-lead">
            Plan marketplace sales, decide how deep to discount, and track what you spend on ads against what sold.
          </p>
        </header>
        <SaleCalendar onOpenListing={onOpenListing} />
        {query.data ? <DiscountDeeper listings={query.data.stale} onOpenListing={onOpenListing} /> : null}
        {query.isError ? <p className="analytics-status">{(query.error as Error).message || "Could not load listings."}</p> : null}
        <AdSpend />
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
