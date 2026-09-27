/** Whole dollars stay whole; a cent keeps two places. */
export function formatMoney(value: number): string {
  if (!Number.isFinite(value)) return "$0";
  const cents = Math.round(Math.abs(value) * 100);
  const hasCents = cents % 100 !== 0;
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: hasCents ? 2 : 0,
    maximumFractionDigits: 2,
  });
}

export function formatDays(days: number): string {
  const rounded = Math.round(days);
  return rounded === 1 ? "1 day" : `${rounded} days`;
}
