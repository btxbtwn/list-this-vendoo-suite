import type { SourcingBuyList, SourcingCart, SourcingLot, SourcingSnapshot, SourcingState } from "../api/types";

/**
 * Each store's own name for a box's grade. Raghouse lots are all plain (its "Recycle"
 * lots are never scouted); TVF grades A to C and says nothing on a plain lot;
 * PaperCrane sellers grade Cream (A) or Standard (B), or leave a lot ungraded.
 */
export const GRADE_LABELS: Record<string, Record<string, string>> = {
  raghouse: { good: "Good" },
  tvf: { a: "A Grade", ab: "A/B Grade", b: "B Grade", bc: "B/C Grade", c: "C Grade" },
  papercrane: { a: "Cream (A)", standard: "Standard (B)" },
};

export const STORE_NAMES: Record<string, string> = {
  raghouse: "Raghouse",
  tvf: "Thrift Vintage Fashion",
  papercrane: "PaperCrane",
};

export function gradeLabel(lot: SourcingLot): string | null {
  return GRADE_LABELS[lot.store]?.[lot.grade] ?? null;
}

export const REFRESH_HOURS = 6;

export function cartTotal(cart: SourcingCart): number {
  return cart.subtotal + cart.shipping;
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
    lot.resale_per_pc != null ? `estimated resale $${Math.round(lot.resale_per_pc)} each` : null,
    lot.compare_at != null && lot.compare_at > lot.price ? `${Math.round((1 - lot.price / lot.compare_at) * 100)}% off` : null,
    lot.vip ? "VIP only" : null,
    lot.seller ? `@${lot.seller}` : null,
    lot.origin ? `ships from ${lot.origin}${lot.free_shipping ? ", included" : ""}` : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

export function storeName(store: string): string {
  return STORE_NAMES[store] ?? store;
}

/** All available variants outside the selected buy list, in their ranked order. */
export function otherLots(snapshot: SourcingSnapshot): SourcingLot[] {
  const picked = new Set(snapshot.buy_list.carts.flatMap((cart) => cart.lots.map((lot) => `${lot.store}:${lot.variant_id}`)));
  return snapshot.lots.filter((lot) => !picked.has(`${lot.store}:${lot.variant_id}`));
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

export function planNeedsUpdate(state: SourcingState): boolean {
  const snapshot = state.snapshot;
  return !snapshot || Object.entries(snapshot.preferences).some(
    ([key, value]) => state.prefs[key as keyof typeof snapshot.preferences] !== value,
  );
}

export function planMetrics(plan: SourcingBuyList) {
  const lots = plan.carts.flatMap((cart) => cart.lots);
  return {
    usable: lots.reduce((sum, lot) => sum + lot.usable_pcs, 0),
    sold: lots.reduce((sum, lot) => sum + lot.usable_pcs * lot.sell_through, 0),
    operating: lots.reduce((sum, lot) => sum + lot.operating_cost, 0),
    downside: lots.reduce((sum, lot) => sum + (lot.downside_profit ?? 0), 0),
  };
}

const EXCLUSION_LABELS = {
  needs_research: "Needs recent sold evidence",
  same_theme: "Another box of this kind was selected",
  return_target: "Below your return target",
  downside: "Loses money in the lower-sales test",
  budget: "Doesn’t fit this cart’s budget",
  alternative: "Another combination was selected",
};

export function whyNotPicked(lot: SourcingLot, plan: SourcingBuyList): string {
  return EXCLUSION_LABELS[plan.exclusions[`${lot.store}:${lot.variant_id}`]];
}

/** "412 need recent sold evidence · 88 below your return target": what ruled the boxes out, most first. */
export function exclusionSummary(plan: SourcingBuyList): string {
  const counts = new Map<string, number>();
  for (const reason of Object.values(plan.exclusions)) counts.set(reason, (counts.get(reason) ?? 0) + 1);
  const phrases: Record<string, string> = {
    needs_research: "need recent sold evidence",
    same_theme: "are another box of a kind already picked",
    return_target: "are below your return target",
    downside: "lose money in the lower-sales test",
    budget: "don’t fit the budget",
    alternative: "lost to another combination",
  };
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([reason, count]) => `${count} ${phrases[reason]}`)
    .join(" · ");
}

export function saleDate(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
