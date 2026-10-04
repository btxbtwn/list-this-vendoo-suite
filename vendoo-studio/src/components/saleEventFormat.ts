import type { SaleEvent } from "../api/types";
import { marketplaceName } from "./marketplaceNames";

export const SALE_EVENTS_QUERY_KEY = ["sale-events"] as const;

/** The marketplaces the seller joins sale events on. */
export const EVENT_MARKETPLACES = ["depop", "ebay", "etsy"] as const;

export const DEFAULT_EVENT_DISCOUNT = 25;

/** A calendar date ("2026-11-27") as a short local date, without a timezone shift. */
export function formatEventDay(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  if (!year || !month || !date) return day;
  return new Date(year, month - 1, date).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function eventDates(event: Pick<SaleEvent, "starts_on" | "ends_on">): string {
  if (event.starts_on === event.ends_on) return formatEventDay(event.starts_on);
  return `${formatEventDay(event.starts_on)} – ${formatEventDay(event.ends_on)}`;
}

export function eventMarketplaces(marketplaces: string[]): string {
  return marketplaces.length ? marketplaces.map(marketplaceName).join(", ") : "All marketplaces";
}

function rate(value: number): string {
  return `${Number.isInteger(value) ? value : value.toFixed(1)}/week`;
}

/** Sales a week during the event against the four weeks before it and the two after. */
export function eventLift(event: SaleEvent): string {
  if (event.status === "upcoming") return "Not started yet.";
  if (event.per_week == null) return "";
  const parts = [`${rate(event.per_week)} during`];
  if (event.before_per_week != null) parts.push(`${rate(event.before_per_week)} the 4 weeks before`);
  if (event.after_per_week != null) {
    const weeks = event.after_days >= 14 ? "the 2 weeks after" : `the ${event.after_days} days after`;
    parts.push(`${rate(event.after_per_week)} ${weeks}`);
  }
  return parts.join(" · ");
}
