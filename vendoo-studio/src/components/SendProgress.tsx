import React from "react";

// Where each Vendoo API step of a send sits on the bar. The server reports the
// step it is on, not how far through it is, so the bar creeps toward the
// step's ceiling and jumps when the next step starts.
const STEP_RANGES: [step: string, floor: number, ceiling: number][] = [
  ["vendoo_api_categories", 4, 20],
  ["vendoo_api_specifics", 20, 35],
  ["vendoo_api_fields", 35, 62],
  ["vendoo_api_photos", 62, 82],
  ["vendoo_api_create", 82, 93],
  ["vendoo_api_patch", 93, 98],
];

export function sendStepRange(step: string, furthestIndex: number): { index: number; floor: number; ceiling: number } {
  let index = STEP_RANGES.findIndex(([name]) => name === step);
  // The job is created on vendoo_api_create before its first real step, so
  // that step only means "creating" once an earlier one has been seen.
  if (index < 0 || (step === "vendoo_api_create" && furthestIndex < 0)) index = 0;
  index = Math.max(index, furthestIndex);
  const [, floor, ceiling] = STEP_RANGES[index];
  return { index, floor, ceiling };
}

/** Eases from ``floor`` toward ``ceiling`` and never moves backwards. */
function useCreepingPercent(floor: number, ceiling: number): number {
  const [percent, setPercent] = React.useState(floor);
  React.useEffect(() => {
    const started = Date.now();
    const start = Math.max(floor, 0);
    setPercent((prev) => Math.max(prev, start));
    const timer = window.setInterval(() => {
      const t = (Date.now() - started) / 1000;
      const next = start + (ceiling - start) * (1 - Math.exp(-t / 6));
      setPercent((prev) => Math.max(prev, next));
    }, 200);
    return () => window.clearInterval(timer);
  }, [floor, ceiling]);
  return Math.min(Math.round(percent), 99);
}

export function SendProgress({
  label,
  floor = 4,
  ceiling = 90,
}: {
  label: string;
  floor?: number;
  ceiling?: number;
}) {
  const percent = useCreepingPercent(floor, ceiling);
  return (
    <div className="send-progress">
      <div className="send-progress-row">
        <span className="send-spinner" aria-hidden="true" />
        <span className="send-progress-label">{label}</span>
        <span className="send-progress-percent">{percent}%</span>
      </div>
      <div
        className="send-progress-track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div className="send-progress-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

/** Tracks the furthest step a send has reached so the bar never rewinds. */
export function useSendStep(step: string, active: boolean) {
  const furthest = React.useRef(-1);
  if (!active) furthest.current = -1;
  const range = sendStepRange(step, furthest.current);
  if (active) furthest.current = range.index;
  return range;
}
