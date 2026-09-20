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
    ? `Importing ${Math.min(run.processed, run.total)} of ${run.total}`
    : `Importing ${run.processed}…`;
  return run.photos ? `${items} · ${run.photos} photos` : items;
}

/** Pull the whole Vendoo inventory in, photos included. */
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
        title: "Could not start the Vendoo import",
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
      addToast({ type: "error", title: "Vendoo import stopped", description: run.error });
    } else {
      addToast({
        type: run.failed ? "error" : "success",
        title: run.cancelled ? "Vendoo import cancelled" : "Vendoo import finished",
        description: importSummary(run),
      });
    }
  }, [running, run, queryClient]);

  const onClick = async () => {
    if (start.isPending) return;
    const ok = await confirmDialog(
      [
        "Import every listing from Vendoo?",
        "",
        "Studio reads your whole Vendoo inventory and creates a listing for each item,",
        "photos and all. Expect it to run for a while and to use real disk space.",
        "Items already imported are only refreshed when they changed in Vendoo,",
        "and a listing whose Vendoo item you deleted is deleted here too.",
      ].join("\n"),
      { confirmLabel: "Import" },
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
      className="sidebar-icon-btn"
      title="Import every listing from Vendoo"
      aria-label="Import every listing from Vendoo"
      disabled={start.isPending}
      onClick={onClick}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 3v12" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
        <path d="M7.5 10.5L12 15l4.5-4.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      </svg>
    </button>
  );
}
