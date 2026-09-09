import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

interface FillLogEntry {
  id: string;
  step: string;
  marketplace: string;
  field: string;
  status: string;
  reason: string;
  selector: string;
  value_preview: string;
}

interface FillLogReport {
  job_id: string;
  summary: Record<string, number>;
  by_marketplace: Record<string, { summary: Record<string, number>; entries: FillLogEntry[] }>;
  log_path: string | null;
}

const STATUS_LABELS: Record<string, string> = {
  filled: "Filled",
  skipped: "Not filled",
  not_found: "Missing",
  failed: "Didn't work",
  uncertain: "Uncertain",
  new: "New fields",
};

const STATUS_ORDER = ["failed", "not_found", "uncertain", "new", "skipped", "filled"];

export function FillLogSummary({ jobId }: { jobId: string }) {
  const report = useFillLog(jobId);
  if (!report) return null;
  const total = Object.values(report.summary).reduce((sum, n) => sum + n, 0);
  if (total === 0) return <div className="fill-log-empty">Waiting for fill results…</div>;
  return (
    <div className="fill-log-chips" aria-label="Fill log summary">
      {STATUS_ORDER.map((status) => {
        const count = report.summary[status] || 0;
        if (!count) return null;
        return (
          <span key={status} className={`fill-log-chip fill-log-chip-${status}`}>
            {count} {STATUS_LABELS[status]}
          </span>
        );
      })}
    </div>
  );
}

export function FillLogPanel({ jobId }: { jobId: string }) {
  const report = useFillLog(jobId);
  if (!report) return <p className="text-xs text-muted">No fill log yet. Send the listing to Vendoo to record what gets filled.</p>;
  const total = Object.values(report.summary).reduce((sum, n) => sum + n, 0);
  if (total === 0) {
    return <p className="text-xs text-muted">No fill results recorded yet.</p>;
  }

  const marketplaces = Object.keys(report.by_marketplace);
  return (
    <div className="fill-log">
      <div className="fill-log-chips">
        {STATUS_ORDER.map((status) => {
          const count = report.summary[status] || 0;
          if (!count) return null;
          return (
            <span key={status} className={`fill-log-chip fill-log-chip-${status}`}>
              {count} {STATUS_LABELS[status]}
            </span>
          );
        })}
      </div>
      {marketplaces.map((marketplace) => {
        const group = report.by_marketplace[marketplace];
        return (
          <section key={marketplace} className="fill-log-market">
            <h3>{marketplace}</h3>
            {STATUS_ORDER.map((status) => {
              const entries = group.entries.filter((entry) => entry.status === status);
              if (entries.length === 0) return null;
              return (
                <div key={status} className="fill-log-group">
                  <div className={`fill-log-group-label fill-log-chip-${status}`}>
                    {STATUS_LABELS[status]}
                  </div>
                  <ul>
                    {entries.map((entry) => (
                      <li key={entry.id}>
                        <span className="fill-log-field">{entry.field}</span>
                        {entry.value_preview && <span className="fill-log-value">{entry.value_preview}</span>}
                        {entry.reason && <span className="fill-log-reason">{entry.reason}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}

function useFillLog(jobId: string): FillLogReport | undefined {
  const { data } = useQuery({
    queryKey: ["fill-log", jobId],
    queryFn: () => api.jobs.fillLog(jobId),
    enabled: Boolean(jobId),
    refetchInterval: 2000,
  });
  return data;
}
