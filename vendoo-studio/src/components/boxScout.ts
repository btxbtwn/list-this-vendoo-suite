import type { SourcingCart, SourcingLot, SourcingSnapshot } from "../api/types";

/** Box grades in the words a buyer would use. */
export const CONDITION_LABELS: Record<string, string> = {
  good: "Good condition",
  mixed: "Mixed condition",
  recycle: "Needs some fixing",
  a: "Grade A",
  ab: "Grade A/B",
  b: "Grade B, some flaws",
  bc: "Grade B/C, flaws",
  c: "Grade C, needs fixing",
};

export const REFRESH_HOURS = 6;

export function cartTotal(cart: SourcingCart): number {
  return cart.subtotal + cart.shipping;
}

/** What each dollar spent should come back as: $418 for $1,210 profit is about $3.89. */
export function moneyBack(total: number, profit: number): string {
  if (total <= 0) return "$0";
  return `$${((total + profit) / total).toFixed(2)}`;
}

/** What is left to spend at a store before its free shipping starts, or null. */
export function freeShippingGap(cart: SourcingCart): number | null {
  if (cart.free_shipping || cart.free_shipping_over == null) return null;
  return Math.max(0, Math.ceil(cart.free_shipping_over - cart.subtotal));
}

export function boxCount(count: number): string {
  return count === 1 ? "1 box" : `${count} boxes`;
}

/** "69 pieces", or "about 150 pieces" when the store sold it by weight. */
export function piecesLabel(lot: SourcingLot): string {
  return `${lot.pcs_estimated ? "about " : ""}${lot.pcs} pieces`;
}

/** The one line under a box's name that says why it is worth having. */
export function lotReason(lot: SourcingLot, withStore = false): string {
  const parts = [
    withStore ? storeName(lot.store) : null,
    piecesLabel(lot),
    CONDITION_LABELS[lot.grade] ?? lot.grade,
    lot.resale_per_pc != null ? `sells for about $${Math.round(lot.resale_per_pc)} each` : null,
    lot.vip ? "VIP members only" : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

export function storeName(store: string): string {
  return store === "tvf" ? "Thrift Vintage Fashion" : "Raghouse";
}

/** The best ranked box of each kind the buy list did not already take. */
export function otherLots(snapshot: SourcingSnapshot, limit = 20): SourcingLot[] {
  const seen = new Set(snapshot.buy_list.carts.flatMap((cart) => cart.lots.map((lot) => lot.theme)));
  const lots: SourcingLot[] = [];
  for (const lot of snapshot.lots) {
    if (seen.has(lot.theme)) continue;
    seen.add(lot.theme);
    lots.push(lot);
    if (lots.length === limit) break;
  }
  return lots;
}

export function clockTime(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  return `${date.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
}

export function nextUpdate(updatedAt: string): string {
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() + REFRESH_HOURS * 3_600_000).toISOString();
}

export function isZip(text: string): boolean {
  return /^\d{5}$/.test(text.trim());
}
