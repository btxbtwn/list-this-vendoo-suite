/** How often queries re-read while something is running: a send, a generation, a sign-in. */
export const BUSY_POLL_MS = 2000;
/** Live progress while generation streams or a send fills fields. */
export const LIVE_POLL_MS = 1000;
/** The fallback pass when nothing is running: it only catches background changes. */
export const IDLE_POLL_MS = 10000;
/** Chrome's pairing; Connect Chrome polls on its own while it waits. */
export const EXTENSION_STATUS_POLL_MS = 5000;

const OPEN_JOB_STATUSES = new Set(["queued", "awaiting_extension", "dispatched"]);

export function isOpenJobStatus(status: string | null | undefined): boolean {
  return OPEN_JOB_STATUSES.has(String(status || ""));
}

export function hasOpenJob(jobs: { status?: string | null }[] | undefined): boolean {
  return Boolean(jobs?.some((job) => isOpenJobStatus(job.status)));
}

/**
 * Polls at `ms` while Studio has focus. Behind another window the desktop
 * webview still counts as visible, so React Query would keep the fast rate;
 * cap it at the idle pass instead, and refetch when the window comes back.
 */
export function pollMs(ms: number): number {
  return document.hasFocus() ? ms : Math.max(ms, IDLE_POLL_MS);
}

/** Every observer of a jobs query polls by the same rule, or each runs its own timer. */
export function jobsPollMs(jobs: { status?: string | null }[] | undefined): number {
  return pollMs(hasOpenJob(jobs) ? BUSY_POLL_MS : IDLE_POLL_MS);
}

/** Fill logs only change while the send writing them is open. */
export function fillLogPollMs(jobStatus: string | null | undefined): number {
  return pollMs(isOpenJobStatus(jobStatus) ? BUSY_POLL_MS : IDLE_POLL_MS);
}

/** A listing's background work: generation, field fills, a send's readback. */
export function activityPollMs(busy: boolean): number {
  return pollMs(busy ? LIVE_POLL_MS : IDLE_POLL_MS);
}
