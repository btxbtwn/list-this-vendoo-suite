/** How often inventory-wide queries re-read while a Vendoo send is moving rows. */
export const INVENTORY_BUSY_POLL_MS = 2000;
/** The fallback pass when nothing is running: it only catches Vendoo's background syncs. */
export const INVENTORY_IDLE_POLL_MS = 10000;

const OPEN_JOB_STATUSES = new Set(["queued", "awaiting_extension", "dispatched"]);

export function hasOpenJob(jobs: { status?: string | null }[] | undefined): boolean {
  return Boolean(jobs?.some((job) => OPEN_JOB_STATUSES.has(String(job.status || ""))));
}
