import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Job } from "../api/types";
import type { BulkRegenerate } from "./useBulkRegenerate";
import { addToast } from "../ui/toast";

export type QueueData = Awaited<ReturnType<typeof api.jobs.queue>>;
const ACTIVE = new Set(["queued", "awaiting_extension", "dispatched"]);

export function QueuePage({ data, loading, error, bulk, titles, onOpenListing }: {
  data?: QueueData;
  loading: boolean;
  error: Error | null;
  bulk: BulkRegenerate;
  titles: ReadonlyMap<string, string>;
  onOpenListing: (id: string) => void;
}) {
  const client = useQueryClient();
  const cancel = useMutation({
    mutationFn: (job: Job) => api.jobs.cancel(job.id),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["queue"] });
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err: Error) => addToast({ type: "error", title: "Could not cancel send", description: err.message }),
  });
  const active = (data?.jobs ?? []).filter((j) => ACTIVE.has(j.status)).sort((a, b) => a.created_at.localeCompare(b.created_at));
  const recent = (data?.jobs ?? []).filter((j) => !ACTIVE.has(j.status));
  const bulkIds = new Set(bulk.pendingIds);
  const work = (data?.work ?? []).filter((w) => !bulkIds.has(w.conversation_id));
  const count = active.length + work.length + bulk.pendingIds.length;
  const renderJob = (job: Job, index: number) => (
    <li className="queue-row" key={job.id}>
      <div className="queue-row-copy">
        <button className="queue-listing" onClick={() => onOpenListing(job.conversation_id)}>
          {job.listing_title || titles.get(job.conversation_id) || "Untitled listing"}
        </button>
        <p>{job.mode === "schema_probe" ? "Discover fields" : job.vendoo_item_id && job.current_step !== "vendoo_api_created" ? "Update Vendoo draft" : "Send to Vendoo"}</p>
        {job.last_error && <p className="queue-error">{job.last_error}</p>}
      </div>
      <span className="queue-status">
        {job.status === "queued" ? `Waiting · #${index + 1}`
          : job.status === "awaiting_extension" ? "Waiting for Chrome"
          : job.status === "dispatched" ? (job.current_step || "Running").replace(/^vendoo_api_/, "").replace(/_/g, " ")
          : job.status === "completed" ? "Saved draft" : job.status}
      </span>
      {ACTIVE.has(job.status) && <button className="btn btn-secondary btn-sm" disabled={cancel.isPending} onClick={() => cancel.mutate(job)}>Cancel</button>}
    </li>
  );
  return (
    <div className="queue-page">
      <div className="queue-inner">
        <header>
          <h1>Queue <span className="queue-count">{count}</span></h1>
          <p className="queue-lead">Keep working while drafts are generated and approved sends are saved. Vendoo sends run one at a time. Nothing is published.</p>
        </header>
        {error && <p role="alert" className="queue-error">{error.message}</p>}
        {loading && <p role="status">Loading queue…</p>}
        <section aria-label="In progress and waiting">
          <h2>In progress &amp; waiting</h2>
          {!loading && !error && count === 0 && <p className="queue-lead">No work waiting. Generate a listing or click Send to Vendoo to add work here.</p>}
          <ul className="queue-list">
            {bulk.pendingIds.map((id, index) => (
              <li className="queue-row" key={`bulk-${id}`}>
                <div className="queue-row-copy">
                  <button className="queue-listing" onClick={() => onOpenListing(id)}>{titles.get(id) || "Untitled listing"}</button>
                  <p>{bulk.run?.mode === "rewrite" ? "Regenerate listing" : "Generate draft"}</p>
                </div>
                <span className="queue-status">{index === 0 ? bulk.run?.phase : "Waiting"}</span>
              </li>
            ))}
            {work.map((w) => (
              <li className="queue-row" key={w.conversation_id}>
                <div className="queue-row-copy">
                  <button className="queue-listing" onClick={() => onOpenListing(w.conversation_id)}>{w.title || "Untitled listing"}</button>
                  <p>{w.detail}</p>
                </div>
                <span className="queue-status">Running</span>
              </li>
            ))}
            {active.map(renderJob)}
          </ul>
          {bulk.running && <button className="btn btn-secondary btn-sm" onClick={bulk.cancel} disabled={bulk.run?.cancelRequested}>Stop batch after current listing</button>}
        </section>
        {recent.length > 0 && <section aria-label="Recent sends">
          <h2>Recent sends</h2>
          <ul className="queue-list">{recent.map(renderJob)}</ul>
        </section>}
      </div>
    </div>
  );
}
