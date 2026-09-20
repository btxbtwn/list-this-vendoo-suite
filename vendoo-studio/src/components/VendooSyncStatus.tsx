import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

/** "just now", "4m ago", "2h ago", then a date. */
export function checkedAgo(checkedAt: string, now: number): string {
  const at = Date.parse(checkedAt);
  if (Number.isNaN(at)) return "";
  const elapsed = Math.max(0, now - at);
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)}m ago`;
  if (elapsed < 24 * HOUR) return `${Math.floor(elapsed / HOUR)}h ago`;
  return new Date(at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Keeps a bound listing in step with its Vendoo draft, quietly.
 *
 * Vendoo's edits come in on their own: when the seller saves in Vendoo (the
 * extension tells Studio), when the listing opens, and when Studio regains
 * focus — never on a timer against Vendoo. Inventory labels (draft / active /
 * sold) always follow Vendoo, even when listing fields conflict. Nothing pops
 * up; this line says when Studio last checked. The one thing left to the
 * seller is a content conflict, where both sides changed and taking Vendoo's
 * version would drop Studio's edits.
 */
export function VendooSyncStatus({ convId, bound }: { convId: string; bound: boolean }) {
  const queryClient = useQueryClient();
  const [now, setNow] = React.useState(() => Date.now());

  // Reads SQLite only, so it can poll: a pull started by a save in Vendoo
  // lands server-side and shows up here on the next read.
  const { data: status } = useQuery({
    queryKey: ["vendoo-sync", convId],
    queryFn: () => api.vendooApi.syncStatus(convId),
    enabled: bound,
    refetchInterval: 5000,
  });

  const refreshListing = React.useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["listing", convId] });
    queryClient.invalidateQueries({ queryKey: ["listing-fields", convId] });
    queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
    queryClient.invalidateQueries({ queryKey: ["vendoo-item"] });
    queryClient.invalidateQueries({ queryKey: ["vendoo-item-peek"] });
    queryClient.invalidateQueries({ queryKey: ["vendoo-sync", convId] });
  }, [convId, queryClient]);

  // A new synced revision means Vendoo's version was pulled in.
  const seenRevision = React.useRef<string | null | undefined>(undefined);
  React.useEffect(() => {
    if (!status) return;
    if (seenRevision.current !== undefined && seenRevision.current !== status.revision_id) {
      refreshListing();
    }
    seenRevision.current = status.revision_id;
  }, [status, refreshListing]);

  const sync = useMutation({
    mutationFn: () => api.vendooApi.sync(convId),
    // Label (draft/active/sold) can move without a new revision — e.g. conflict
    // after a regenerate-then-relist — so refresh the sidebar on every check.
    onSuccess: refreshListing,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["vendoo-sync", convId] }),
  });
  const takeVendoo = useMutation({
    mutationFn: () => api.vendooApi.pull(convId),
    onSuccess: refreshListing,
  });
  const { mutate: runSync } = sync;

  React.useEffect(() => {
    if (!bound) return undefined;
    runSync();
    const onFocus = () => runSync();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [convId, bound, runSync]);

  React.useEffect(() => {
    if (!bound) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [bound]);

  if (!bound) return null;

  const busy = sync.isPending || takeVendoo.isPending;
  const checkedAt = status?.checked_at;
  const failed = sync.data?.action === "unavailable" || sync.isError || takeVendoo.isError;
  let label: string;
  if (busy) label = "Syncing…";
  else if (checkedAt) label = `Synced ${checkedAgo(checkedAt, now)}`;
  else label = failed ? "Not synced" : "Syncing…";

  const title = [
    checkedAt ? `Last checked Vendoo ${new Date(checkedAt).toLocaleString()}` : "Not checked with Vendoo yet",
    failed ? "Last check could not reach Vendoo — is Chrome connected?" : "",
    "Click to check now",
  ].filter(Boolean).join("\n");

  return (
    <span className="pr-vendoo-sync">
      <span aria-hidden="true">·</span>
      <button
        type="button"
        className={`pr-vendoo-sync-btn${failed && !busy ? " is-stale" : ""}`}
        disabled={busy}
        title={title}
        onMouseDown={(event) => event.stopPropagation()}
        onClick={() => runSync()}
      >
        {label}
      </button>
      {status?.conflict && !busy ? (
        <button
          type="button"
          className="pr-vendoo-sync-btn is-conflict"
          title="Vendoo and Studio both changed since the last sync. Studio kept its version. Click to replace it with Vendoo's."
          onMouseDown={(event) => event.stopPropagation()}
          onClick={() => takeVendoo.mutate()}
        >
          Both changed · use Vendoo's
        </button>
      ) : null}
    </span>
  );
}
