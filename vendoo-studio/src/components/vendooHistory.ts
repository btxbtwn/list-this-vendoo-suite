/** Vendoo's time tracking for one item, as the details panel reads it. */

import { marketplaceLabel } from "./fillLogForms";

export type VendooTimeline = {
  vendoo_created_at?: string | null;
  vendoo_modified_at?: string | null;
  vendoo_listed_at?: string | null;
  vendoo_sold_at?: string | null;
  vendoo_listed_dates?: Record<string, string>;
  vendoo_sold_dates?: Record<string, string>;
};

export type HistoryRow = {
  key: string;
  label: string;
  /** The stamp itself, for the row's title attribute. */
  iso: string;
  when: string;
  age: string;
  /** A per-marketplace date sits under the item-wide one it belongs to. */
  nested?: boolean;
};

const DAY_MS = 86_400_000;

function ms(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** The date on its own, in the reader's locale. */
export function formatWhen(iso: string): string {
  const stamp = ms(iso);
  if (!stamp) return "";
  return new Date(stamp).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** How long ago that was, in the coarsest unit that still says something. */
export function formatAge(iso: string, now: number = Date.now()): string {
  const stamp = ms(iso);
  if (!stamp) return "";
  const days = Math.floor((now - stamp) / DAY_MS);
  if (days < 0) return "just now";
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 61) return `${days} days ago`;
  const months = Math.round(days / 30.44);
  if (months < 24) return `${months} months ago`;
  return `${(days / 365.25).toFixed(1)} years ago`;
}

/**
 * Every Vendoo date the item carries, newest story first: when it went live,
 * when it sold, then the bookkeeping. Dates Vendoo never stamped are left out
 * rather than shown as blanks.
 */
export function historyRows(item: VendooTimeline, now: number = Date.now()): HistoryRow[] {
  const rows: HistoryRow[] = [];
  const push = (key: string, label: string, iso: string | null | undefined, nested = false) => {
    if (!iso || !ms(iso)) return;
    rows.push({ key, label, iso, when: formatWhen(iso), age: formatAge(iso, now), ...(nested ? { nested } : {}) });
  };
  const byMarketplace = (dates: Record<string, string> | undefined, prefix: string) =>
    Object.entries(dates || {})
      .sort(([, left], [, right]) => ms(right) - ms(left))
      .forEach(([market, iso]) => push(`${prefix}:${market}`, marketplaceLabel(market), iso, true));

  push("listed", "Listed", item.vendoo_listed_at);
  byMarketplace(item.vendoo_listed_dates, "listed");
  push("sold", "Sold", item.vendoo_sold_at);
  byMarketplace(item.vendoo_sold_dates, "sold");
  push("modified", "Last modified", item.vendoo_modified_at);
  push("created", "Created", item.vendoo_created_at);
  return rows;
}
