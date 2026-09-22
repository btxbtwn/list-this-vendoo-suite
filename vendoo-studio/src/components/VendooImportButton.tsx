import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";
import type { VendooBulkImport } from "../api/types";

const RUNNING_POLL_MS = 1500;

export function importSummary(run: VendooBulkImport): string {
  const parts = [
    run.imported ? `${run.imported} new` : "",
    run.updated ? `${run.updated} updated` : "",
    run.skipped ? `${run.skipped} unchanged` : "",
    run.deleted ? `${run.deleted} removed` : "",
    run.failed ? `${run.failed} failed` : "",
  ].filter(Boolean);
  if (!parts.length) return "Nothing to import";
  return run.photos ? `${parts.join(", ")} · ${run.photos} photos` : parts.join(", ");
}

export function progressLabel(run: VendooBulkImport): string {
  const items = run.total
    ? `Syncing ${Math.min(run.processed, run.total)} of ${run.total}`
    : `Syncing ${run.processed}…`;
  return run.photos ? `${items} · ${run.photos} photos` : items;
}

/** Sync the whole Vendoo inventory, photos included. */
export function VendooImportButton() {
  const queryClient = useQueryClient();
  const wasRunning = useRef(false);

  const { data: run } = useQuery({
    queryKey: ["vendoo-bulk-import"],
    queryFn: api.imports.bulkStatus,
    refetchInterval: (query) => (query.state.data?.running ? RUNNING_POLL_MS : false),
  });

  const start = useMutation({
    mutationFn: api.imports.startBulk,
    onSuccess: (data) => queryClient.setQueryData(["vendoo-bulk-import"], data),
    onError: (err: Error) =>
      addToast({
        type: "error",
        title: "Could not start the Vendoo sync",
        description: err.message || "An unexpected error occurred.",
      }),
  });

  const cancel = useMutation({
    mutationFn: api.imports.cancelBulk,
    onSuccess: (data) => queryClient.setQueryData(["vendoo-bulk-import"], data),
  });

  const running = Boolean(run?.running);

  // Listings arrive throughout the run, so keep the sidebar in step while it works.
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    }, 4000);
    return () => window.clearInterval(timer);
  }, [running, queryClient]);

  useEffect(() => {
    if (running) {
      wasRunning.current = true;
      return;
    }
    if (!wasRunning.current || !run) return;
    wasRunning.current = false;
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
    if (run.error) {
      addToast({ type: "error", title: "Vendoo sync stopped", description: run.error });
    } else {
      addToast({
        type: run.failed ? "error" : "success",
        title: run.cancelled ? "Vendoo sync cancelled" : "Vendoo sync finished",
        description: importSummary(run),
      });
    }
  }, [running, run, queryClient]);

  const onClick = async () => {
    if (start.isPending) return;
    const ok = await confirmDialog(
      [
        "Sync every listing from Vendoo?",
        "",
        "Studio reads your whole Vendoo inventory and syncs a listing for each item,",
        "photos and all. Expect it to run for a while and to use real disk space.",
        "Items already imported are only refreshed when they changed in Vendoo,",
        "and a listing whose Vendoo item you deleted is deleted here too.",
      ].join("\n"),
      { confirmLabel: "Sync" },
    );
    if (ok) start.mutate();
  };

  if (running && run) {
    const pct = run.total ? Math.min(100, Math.round((run.processed / run.total) * 100)) : 0;
    return (
      <div className="vendoo-import is-running" title={run.current_title || undefined}>
        <div className="vendoo-import-copy">
          <span className="vendoo-import-label">{progressLabel(run)}</span>
          <span className="vendoo-import-bar" aria-hidden="true">
            <span className="vendoo-import-bar-fill" style={{ width: `${pct}%` }} />
          </span>
        </div>
        <button
          type="button"
          className="vendoo-import-cancel"
          disabled={cancel.isPending}
          onClick={() => cancel.mutate()}
        >
          Stop
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      className={`sidebar-icon-btn sidebar-vendoo-sync-btn${start.isPending ? " is-busy" : ""}`}
      title="Sync Vendoo data"
      aria-label="Sync Vendoo data"
      aria-busy={start.isPending || undefined}
      disabled={start.isPending}
      onClick={onClick}
    >
      {/* Cloud + down arrow: inventory pull, not the circular refresh used by Check for Updates. */}
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M7.5 18H17a4 4 0 00.4-8 5.5 5.5 0 00-10.7-1.6A3.5 3.5 0 007.5 18z"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinejoin="round"
        />
        <path d="M12 10v6" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
        <path d="M9.5 14L12 16.5 14.5 14" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}
