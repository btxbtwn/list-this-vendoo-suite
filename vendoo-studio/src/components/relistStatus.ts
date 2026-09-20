/**
 * Which live listings are still showing copy from before Studio's last write.
 *
 * Studio edits the Vendoo *form*. Vendoo carries a form change onto a live
 * marketplace listing only when the seller delists and relists it — there is no
 * edit-in-place. So an item can be "active" in every view while the buyer still
 * sees the old title, price and photos, which is exactly the trap this module
 * exists to label: the listing date of a marketplace that was relisted moves
 * past the write, and one that was not stays behind it.
 */

export type RelistableListing = {
  status?: string | null;
  vendoo_marketplaces?: string[];
  vendoo_listed_at?: string | null;
  vendoo_listed_dates?: Record<string, string>;
  vendoo_sold_dates?: Record<string, string>;
  vendoo_form_updated_at?: string | null;
};

function timeMs(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Marketplaces to delist and relist in Vendoo before buyers see this edit.
 *
 * A sold listing is left out: its copy is history, not something to refresh.
 * A live marketplace with no listing date at all is left *in* — an unprovable
 * date is the case where a missed relist hurts, so it warns rather than hides.
 */
export function marketplacesNeedingRelist(listing: RelistableListing | null | undefined): string[] {
  if (!listing) return [];
  const updatedAt = timeMs(listing.vendoo_form_updated_at);
  if (!updatedAt) return [];
  if (String(listing.status || "draft") === "sold") return [];
  const sold = listing.vendoo_sold_dates || {};
  const listedDates = listing.vendoo_listed_dates || {};
  const fallback = timeMs(listing.vendoo_listed_at);
  return (listing.vendoo_marketplaces || [])
    .filter((id) => {
      if (sold[id]) return false;
      const listedAt = timeMs(listedDates[id]) || fallback;
      return !listedAt || listedAt < updatedAt;
    })
    .sort();
}

export function needsRelist(listing: RelistableListing | null | undefined): boolean {
  return marketplacesNeedingRelist(listing).length > 0;
}

/** "eBay", "eBay and Poshmark", "eBay, Poshmark and Depop". */
export function joinMarketplaces(names: string[]): string {
  if (names.length <= 1) return names[0] || "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** The one sentence that says what Update Vendoo did and did not do. */
export function relistCallout(names: string[]): string {
  const where = joinMarketplaces(names);
  const [listing, show] = names.length === 1 ? ["listing", "shows"] : ["listings", "show"];
  return `The Vendoo form is updated, but the live ${where} ${listing} ${show} the old version.`;
}
