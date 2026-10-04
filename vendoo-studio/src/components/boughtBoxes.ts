import type { SourceBox, SourceBoxInput, SourcingLot } from "../api/types";

export const BOXES_QUERY_KEY = ["boxes"];

const STORE_NAMES: Record<string, string> = { raghouse: "Raghouse", tvf: "Thrift Vintage Fashion" };

/** A recently recorded box with the same link counts as already bought. */
const RECENT_DAYS = 14;

export function boxStoreName(store: string): string {
  return STORE_NAMES[store] ?? store;
}

/** A typed store name, with the two stores Studio scouts saved under their own keys. */
export function boxStoreKey(name: string): string {
  const text = name.trim();
  const match = Object.entries(STORE_NAMES).find(([, label]) => label.toLowerCase() === text.toLowerCase());
  return match ? match[0] : text;
}

/** A buy-list box as the seller would record it once paid for. */
export function boxFromLot(lot: SourcingLot): SourceBoxInput {
  return {
    store: lot.store,
    title: lot.title,
    url: lot.url,
    price: lot.price,
    shipping: Math.round(lot.ship_est * 100) / 100,
    pieces: lot.pcs || null,
  };
}

export function recentlyBought(lot: SourcingLot, boxes: SourceBox[], now = Date.now()): boolean {
  return boxes.some((box) => (
    box.url === lot.url
    && box.bought_at != null
    && now - Date.parse(box.bought_at) < RECENT_DAYS * 86_400_000
  ));
}

export function formatPercent(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

/** "Sold 4 of 20 · 9 listed" — what has happened to a box's pieces so far. */
export function boxProgress(box: { sold: number; listed: number; listings: number; pieces?: number | null }): string {
  const of = box.pieces || box.listings;
  const parts = [of ? `Sold ${box.sold} of ${of}` : `Sold ${box.sold}`];
  if (box.listed > box.sold) parts.push(`${box.listed - box.sold} listed`);
  const drafts = box.listings - box.listed;
  if (drafts > 0) parts.push(drafts === 1 ? "1 draft" : `${drafts} drafts`);
  return parts.join(" · ");
}
