/**
 * Which live listings are still showing copy from before Studio's last write.
 *
 * Studio edits the Vendoo *form*. Vendoo carries a form change onto a live
 * marketplace listing only when the seller delists and relists it — there is no
 * edit-in-place. So an item can be "active" in every view while the buyer still
 * sees the old title, price and photos, which is exactly the trap this module
 * exists to label: the listing date of a marketplace that was relisted moves
 * past the write, and one that was not stays behind it.
 *
 * The job has two halves, and the middle is the dangerous part. Delist Item in
 * Vendoo leaves the item live nowhere, so reading the live listings alone would
 * drop the warning exactly when the seller is one step from finishing. The
 * marketplaces owed a relist are therefore remembered at write time
 * (``vendoo_relist_pending``) and only let go once Vendoo reports each one
 * listed again.
 */

export type RelistableListing = {
  status?: string | null;
  vendoo_marketplaces?: string[];
  vendoo_listed_at?: string | null;
  vendoo_listed_dates?: Record<string, string>;
  vendoo_sold_dates?: Record<string, string>;
  vendoo_form_updated_at?: string | null;
  vendoo_relist_pending?: string[];
};

/**
 * Where the listing sits between a Studio edit and buyers seeing it.
 *
 * ``delist`` — still live on the old copy; the next step is Delist Item.
 * ``list`` — taken down in Vendoo, not up again; the item is live nowhere.
 * ``none`` — current, sold, or never written to.
 */
export type RelistStage = "delist" | "list" | "none";

function timeMs(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Marketplaces to delist and relist in Vendoo before buyers see this edit.
 *
 * Counts both the ones still live on the old copy and the ones already taken
 * down and not yet put back. A sold listing is left out: its copy is history,
 * not something to refresh. A marketplace with no listing date at all is left
 * *in* — an unprovable date is the case where a missed relist hurts, so it
 * warns rather than hides.
 */
export function marketplacesNeedingRelist(listing: RelistableListing | null | undefined): string[] {
  if (!listing) return [];
  const updatedAt = timeMs(listing.vendoo_form_updated_at);
  if (!updatedAt) return [];
  if (String(listing.status || "draft") === "sold") return [];
  const sold = listing.vendoo_sold_dates || {};
  const listedDates = listing.vendoo_listed_dates || {};
  const live = listing.vendoo_marketplaces || [];
  const fallback = timeMs(listing.vendoo_listed_at);
  const candidates = new Set([...live, ...(listing.vendoo_relist_pending || [])]);
  return [...candidates]
    .filter((id) => {
      if (sold[id]) return false;
      // The item-wide listing date only stands in for a marketplace that is
      // still live; for one already taken down it would date the listing that
      // no longer exists.
      const listedAt = timeMs(listedDates[id]) || (live.includes(id) ? fallback : 0);
      return !listedAt || listedAt < updatedAt;
    })
    .sort();
}

/** Which half of the job is left: taking it down, or putting it back up. */
export function relistStage(listing: RelistableListing | null | undefined): RelistStage {
  const owed = marketplacesNeedingRelist(listing);
  if (!owed.length) return "none";
  const live = new Set(listing?.vendoo_marketplaces || []);
  return owed.some((id) => live.has(id)) ? "delist" : "list";
}

export function needsRelist(listing: RelistableListing | null | undefined): boolean {
  return marketplacesNeedingRelist(listing).length > 0;
}

/** "eBay", "eBay and Poshmark", "eBay, Poshmark and Depop". */
export function joinMarketplaces(names: string[]): string {
  if (names.length <= 1) return names[0] || "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * The marketplaces as the copy names them: the short lists in full, the long
 * ones by count.
 *
 * An item can be live on a dozen marketplaces, and spelling all of them out
 * turns a one-line warning into a paragraph nobody reads. Past two, what
 * matters is that this is every marketplace the item is on — which is also what
 * Vendoo's own Delist Item covers. The full list stays in the tooltip.
 */
export function describeMarketplaces(names: string[]): string {
  if (names.length > 2) return `all ${names.length} marketplaces`;
  return joinMarketplaces(names);
}

/**
 * The one sentence that says where the listing stands.
 *
 * After the delist there is nothing live to describe, so it says the thing that
 * actually matters then: the item is off every marketplace until it goes back up.
 */
export function relistCallout(names: string[], stage: RelistStage = "delist"): string {
  if (stage === "list") {
    return "The Vendoo form holds the new version and the item is delisted,"
      + " so it is live nowhere until you list it again.";
  }
  if (names.length > 2) {
    return `The Vendoo form is updated, but the live listings on all ${names.length}`
      + " marketplaces still show the old version.";
  }
  const [listing, show] = names.length === 1 ? ["listing", "shows"] : ["listings", "show"];
  return `The Vendoo form is updated, but the live ${joinMarketplaces(names)}`
    + ` ${listing} ${show} the old version.`;
}
