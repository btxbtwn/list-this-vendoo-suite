/** Vendoo Inventory's filters and sorts, over Studio's own listing rows. */

export type ListingSortId =
  | "recent"
  | "created_desc"
  | "created_asc"
  | "modified_desc"
  | "modified_asc"
  | "title_asc"
  | "title_desc"
  | "price_desc"
  | "price_asc"
  | "sku_asc"
  | "sku_desc";

export const LISTING_SORTS: { id: ListingSortId; label: string }[] = [
  { id: "recent", label: "Recent activity" },
  { id: "created_desc", label: "Date Created (Newest)" },
  { id: "created_asc", label: "Date Created (Oldest)" },
  { id: "modified_desc", label: "Date Modified (Newest)" },
  { id: "modified_asc", label: "Date Modified (Oldest)" },
  { id: "title_asc", label: "Alphabetical (A-Z)" },
  { id: "title_desc", label: "Alphabetical (Z-A)" },
  { id: "price_desc", label: "Price (Highest)" },
  { id: "price_asc", label: "Price (Lowest)" },
  { id: "sku_asc", label: "SKU (A-Z)" },
  { id: "sku_desc", label: "SKU (Z-A)" },
];

/** Vendoo's Inventory tabs, plus the one state Vendoo has no name for. */
export const LISTING_STATUS_TABS = ["draft", "active", "sold", "failed"] as const;

export type ListingStatusFilter = "all" | (typeof LISTING_STATUS_TABS)[number];

export type FilterableListing = {
  title?: string | null;
  status?: string | null;
  sku?: string | null;
  price?: number | null;
  created_at?: string;
  updated_at?: string;
  vendoo_labels?: string[];
  vendoo_marketplaces?: string[];
};

export interface ListingFilters {
  status: ListingStatusFilter;
  marketplaces: string[];
  labels: string[];
  notListed: boolean;
  sort: ListingSortId;
}

export const DEFAULT_LISTING_FILTERS: ListingFilters = {
  status: "all",
  marketplaces: [],
  labels: [],
  notListed: false,
  sort: "recent",
};

function lower(value: string | null | undefined): string {
  return String(value || "").toLowerCase();
}

function listedOn(listing: FilterableListing): string[] {
  return listing.vendoo_marketplaces || [];
}

/** Vendoo searches Title and SKU; a listing with neither only matches an empty query. */
export function matchesSearch(listing: FilterableListing, needle: string): boolean {
  if (!needle) return true;
  return lower(listing.title || "Untitled").includes(needle) || lower(listing.sku).includes(needle);
}

export function matchesFilters(listing: FilterableListing, filters: ListingFilters): boolean {
  if (filters.status !== "all" && String(listing.status || "draft") !== filters.status) return false;
  const listed = listedOn(listing);
  // Vendoo's "View Not Listed" asks for the items no marketplace carries, which
  // is the opposite of picking marketplaces, so it wins over the chips.
  if (filters.notListed) return listed.length === 0;
  if (filters.marketplaces.length && !filters.marketplaces.some((id) => listed.includes(id))) return false;
  if (filters.labels.length) {
    const own = new Set((listing.vendoo_labels || []).map(lower));
    if (!filters.labels.some((label) => own.has(lower(label)))) return false;
  }
  return true;
}

export function filterListings<T extends FilterableListing>(
  listings: T[],
  needle: string,
  filters: ListingFilters,
): T[] {
  return listings.filter((listing) => matchesSearch(listing, needle) && matchesFilters(listing, filters));
}

function timeMs(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function byText(left: string | null | undefined, right: string | null | undefined, direction: 1 | -1): number {
  const a = String(left || "");
  const b = String(right || "");
  // A listing without a SKU sorts last in either direction, the way Vendoo's
  // own SKU sorts leave unsku'd items at the end.
  if (!a !== !b) return a ? -1 : 1;
  return a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }) * direction;
}

function byNumber(left: number | null | undefined, right: number | null | undefined, direction: 1 | -1): number {
  const a = typeof left === "number" ? left : null;
  const b = typeof right === "number" ? right : null;
  // A listing without a price sorts last in either direction, as an unpriced
  // draft is never what a price sort is looking for.
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
  return (a - b) * direction;
}

/** Order for every sort but `recent`, which keeps each shelf's own anchor. */
export function compareListings(sort: ListingSortId): ((left: FilterableListing, right: FilterableListing) => number) | null {
  switch (sort) {
    case "created_desc":
      return (l, r) => timeMs(r.created_at) - timeMs(l.created_at);
    case "created_asc":
      return (l, r) => timeMs(l.created_at) - timeMs(r.created_at);
    case "modified_desc":
      return (l, r) => timeMs(r.updated_at) - timeMs(l.updated_at);
    case "modified_asc":
      return (l, r) => timeMs(l.updated_at) - timeMs(r.updated_at);
    case "title_asc":
      return (l, r) => byText(l.title || "Untitled", r.title || "Untitled", 1);
    case "title_desc":
      return (l, r) => byText(l.title || "Untitled", r.title || "Untitled", -1);
    case "price_desc":
      return (l, r) => byNumber(l.price, r.price, -1);
    case "price_asc":
      return (l, r) => byNumber(l.price, r.price, 1);
    case "sku_asc":
      return (l, r) => byText(l.sku, r.sku, 1);
    case "sku_desc":
      return (l, r) => byText(l.sku, r.sku, -1);
    default:
      return null;
  }
}

export function sortListings<T extends FilterableListing>(listings: T[], sort: ListingSortId): T[] {
  const compare = compareListings(sort);
  return compare ? [...listings].sort(compare) : listings;
}

export function statusCounts(listings: FilterableListing[]): Record<string, number> {
  const counts: Record<string, number> = { all: listings.length };
  for (const listing of listings) {
    const status = String(listing.status || "draft");
    counts[status] = (counts[status] || 0) + 1;
  }
  return counts;
}

/** Every Vendoo label in the inventory, deduped case-insensitively. */
export function labelOptions(listings: FilterableListing[]): string[] {
  const seen = new Map<string, string>();
  for (const listing of listings) {
    for (const label of listing.vendoo_labels || []) {
      const key = lower(label);
      if (key && !seen.has(key)) seen.set(key, label);
    }
  }
  return [...seen.values()].sort((left, right) => left.localeCompare(right, undefined, { sensitivity: "base" }));
}

/** Marketplace chips: the ones Settings shows, kept in that order, plus any other the inventory uses. */
export function marketplaceOptions(listings: FilterableListing[], preferred: string[]): string[] {
  const used = new Set<string>();
  for (const listing of listings) {
    for (const id of listedOn(listing)) used.add(id);
  }
  const ordered = preferred.filter((id) => used.has(id));
  const extra = [...used].filter((id) => !preferred.includes(id)).sort();
  return [...ordered, ...extra];
}

export function activeFilterCount(filters: ListingFilters): number {
  return (
    (filters.status === "all" ? 0 : 1) +
    filters.marketplaces.length +
    filters.labels.length +
    (filters.notListed ? 1 : 0)
  );
}

export function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((entry) => entry !== value) : [...values, value];
}
