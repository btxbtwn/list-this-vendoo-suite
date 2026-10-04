import type { ScoutCheck, ScoutState, ScoutVerdict } from "../api/types";
import { formatMoney } from "./analyticsFormat";

export const SCOUT_QUERY_KEY = ["scout"];

const VERDICT_LABELS: Record<ScoutVerdict, string> = {
  buy: "Buy it",
  maybe: "Maybe",
  pass: "Pass",
  unsure: "Not sure",
};

export function verdictLabel(verdict: ScoutVerdict | null): string | null {
  return verdict ? VERDICT_LABELS[verdict] : null;
}

/** The one line under the verdict that says why. */
export function verdictReason(check: ScoutCheck): string {
  if (check.estimate == null) {
    return "Too few sold listings to price it. Check the comps yourself, or pass.";
  }
  const sold = check.comps_count === 1 ? "1 sale" : `${check.comps_count ?? 0} sales`;
  const base = `Sells for about ${formatMoney(Math.round(check.estimate))} (${sold}), ${formatMoney(Math.round(check.net ?? 0))} after fees.`;
  if (check.profit == null) return `${base} Worth paying up to ${formatMoney(check.pay_up_to ?? 0)}.`;
  const profit = check.profit >= 0
    ? `about ${formatMoney(Math.round(check.profit))} profit`
    : `a ${formatMoney(Math.abs(Math.round(check.profit)))} loss`;
  return `${base} At ${formatMoney(check.asking_price ?? 0)} that's ${profit}.`;
}

/** "12 checks · 5 bought · 3 sold, 2 within 25% of the estimate". */
export function trackRecordLine(record: ScoutState["track_record"]): string | null {
  if (!record.checks) return null;
  const parts = [
    record.checks === 1 ? "1 check" : `${record.checks} checks`,
    `${record.bought} bought`,
  ];
  if (record.sold) {
    parts.push(`${record.sold} sold, ${record.close} within 25% of the estimate`);
  }
  return parts.join(" · ");
}

export function isChecking(state: ScoutState | undefined): boolean {
  return Boolean(state?.checks.some((check) => check.status === "checking"));
}
