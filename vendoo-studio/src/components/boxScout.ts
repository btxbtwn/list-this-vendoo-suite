import type { SourcingCart, SourcingLot, SourcingSnapshot } from "../api/types";

export const GRADE_LABELS: Record<string, string> = {
  good: "Good",
  mixed: "Recycle & Good",
  recycle: "Recycle",
  a: "A grade",
  ab: "A/B grade",
  b: "B grade",
  bc: "B/C grade",
  c: "C grade",
};

export function formatRoi(roi: number): string {
  return `${Math.round(roi * 100)}%`;
}

/** What is left to spend at a store before its free shipping starts, or null. */
export function freeShippingGap(cart: SourcingCart): number | null {
  if (cart.free_shipping || cart.free_shipping_over == null) return null;
  return Math.max(0, Math.ceil(cart.free_shipping_over - cart.subtotal));
}

export function lotCount(count: number): string {
  return count === 1 ? "1 box" : `${count} boxes`;
}

/** The best ranked lot of each theme the buy list did not already take. */
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

/** "Good · 69 pcs · 28 lb", with ~ on counts and weights the store did not state. */
export function lotMeta(lot: SourcingLot): string {
  const parts = [
    GRADE_LABELS[lot.grade] ?? lot.grade,
    `${lot.pcs_estimated ? "~" : ""}${lot.pcs} pcs`,
    `${lot.lbs_estimated ? "~" : ""}${Math.round(lot.lbs)} lb`,
  ];
  if (lot.vip) parts.push("VIP only");
  return parts.join(" · ");
}

export function whenChecked(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return `today ${time}`;
  return `${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${time}`;
}

export function isZip(text: string): boolean {
  return /^\d{5}$/.test(text.trim());
}
