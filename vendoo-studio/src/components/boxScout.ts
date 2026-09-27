import type { SourcingCart, SourcingLot, SourcingSnapshot } from "../api/types";

/**
 * Each store's own name for a box's grade. Raghouse sells "Recycle", "Recycle & Good"
 * and plain lots; TVF grades A to C and says nothing on a plain lot.
 */
export const GRADE_LABELS: Record<string, Record<string, string>> = {
  raghouse: { good: "Good", mixed: "Recycle & Good", recycle: "Recycle" },
  tvf: { a: "A Grade", ab: "A/B Grade", b: "B Grade", bc: "B/C Grade", c: "C Grade" },
};

export function gradeLabel(lot: SourcingLot): string | null {
  return GRADE_LABELS[lot.store]?.[lot.grade] ?? null;
}

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

/** The count the way each store writes it: Raghouse "69 pcs", TVF "10 Pieces"; ~ when estimated. */
export function piecesLabel(lot: SourcingLot): string {
  const unit = lot.store === "tvf" ? "Pieces" : "pcs";
  return `${lot.pcs_estimated ? "~" : ""}${lot.pcs} ${unit}`;
}

/** The one line under a box's name that says why it is worth having. */
export function lotReason(lot: SourcingLot, withStore = false): string {
  const parts = [
    withStore ? storeName(lot.store) : null,
    piecesLabel(lot),
    gradeLabel(lot),
    lot.resale_per_pc != null ? `sells for about $${Math.round(lot.resale_per_pc)} each` : null,
    lot.vip ? "VIP only" : null,
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
