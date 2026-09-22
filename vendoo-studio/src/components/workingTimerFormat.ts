/**
 * Duration-formatting helpers for the chat working indicator.
 * Matches T3 Code's formatDuration / live WorkingTimer (pingdotgg/t3code).
 */

/** Completed or precise elapsed time (tenths under 10s). */
export function formatDuration(durationMs: number): string {
  if (!Number.isFinite(durationMs) || durationMs < 0) return "0ms";
  if (durationMs < 1_000) return `${Math.max(1, Math.round(durationMs))}ms`;
  if (durationMs < 10_000) {
    const tenths = Math.round(durationMs / 100) / 10;
    return tenths >= 10 ? "10s" : `${tenths.toFixed(1)}s`;
  }
  if (durationMs < 60_000) return `${Math.round(durationMs / 1_000)}s`;
  const totalSeconds = Math.round(durationMs / 1_000);
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (seconds > 0) parts.push(`${seconds}s`);
  return parts.join(" ") || "0s";
}

/** Live "Working for" timer: whole seconds, then formatDuration for ≥1m. */
export function formatWorkingTimer(elapsedMs: number): string {
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) return "0s";
  const elapsedSeconds = Math.floor(elapsedMs / 1_000);
  if (elapsedSeconds < 60) return `${elapsedSeconds}s`;
  return formatDuration(elapsedSeconds * 1_000);
}

export function formatWorkingTimerSince(startedAtMs: number, nowMs = Date.now()): string {
  return formatWorkingTimer(nowMs - startedAtMs);
}
