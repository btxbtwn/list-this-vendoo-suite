import type { BackupsStatus } from "../api/types";

export function formatBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** How long ago a snapshot was taken, in the roughest useful unit. */
export function formatWhen(iso: string, now: number = Date.now()): string {
  const taken = new Date(iso);
  if (Number.isNaN(taken.getTime())) return "unknown";
  const minutes = Math.floor((now - taken.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** The one line that says whether the backups are in a state worth trusting. */
export function backupSummary(data: BackupsStatus | undefined, now: number = Date.now()): string {
  if (!data) return "Checking…";
  if (!data.latest) return "No backups yet";
  const kept = data.snapshots.length;
  return `Last backup ${formatWhen(data.latest.taken_at, now)} · ${formatBytes(
    data.latest.size_bytes,
  )} · ${kept} kept`;
}
