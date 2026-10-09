/** One figure on the Analytics page, with what it covers and how it moved. */
export function Stat({
  label,
  value,
  hint,
  change,
  negative = false,
}: {
  label: string;
  value: string;
  hint?: string;
  change?: string;
  negative?: boolean;
}) {
  return (
    <div className="analytics-stat">
      <div className="analytics-stat-label">{label}</div>
      <div className={`analytics-stat-value${negative ? " is-negative" : ""}`}>{value}</div>
      {hint ? <div className="analytics-stat-hint">{hint}</div> : null}
      {change ? <div className="analytics-stat-change">{change}</div> : null}
    </div>
  );
}
