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

/** Use an absolute change when a zero or negative baseline makes percentages misleading. */
export function formatChange(
  current: number | null,
  previous: number | null,
  format: (value: number) => string,
): string {
  if (current == null || previous == null) return "No comparison data";
  if (current === previous) return "No change";
  const difference = current - previous;
  const direction = difference > 0 ? "Up" : "Down";
  const percent = previous > 0 && current >= 0
    ? ` (${Math.abs(difference / previous * 100).toFixed(0)}%)`
    : "";
  return `${direction} ${format(Math.abs(difference))}${percent}`;
}
