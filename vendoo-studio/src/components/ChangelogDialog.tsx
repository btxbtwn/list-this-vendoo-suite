import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import MarkdownRenderer from "./MarkdownRenderer";

/** "2026-09-22" → "Sep 22, 2026"; anything else is shown as it came. */
export function formatEntryDate(date: string | null | undefined): string {
  if (!date) return "";
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** What's new: every released version, newest first, with the running one marked. */
export function ChangelogDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["changelog"],
    queryFn: api.changelog,
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [open, onClose]);

  if (!open) return null;

  const entries = data?.entries || [];

  return createPortal(
    <div className="confirm-dialog changelog-dialog" role="presentation">
      <button type="button" className="confirm-dialog-backdrop" aria-label="Close" onClick={onClose} />
      <div
        className="confirm-dialog-popup changelog-popup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="changelog-title"
      >
        <div className="confirm-dialog-header">
          <h2 id="changelog-title" className="confirm-dialog-title">
            What's new
          </h2>
          <p className="confirm-dialog-description">
            Every change to List This Studio, newest first.
          </p>
        </div>
        <div className="changelog-body">
          {isLoading ? (
            <p className="changelog-status">Loading changelog…</p>
          ) : error ? (
            <p className="changelog-status is-error">
              {(error as Error).message || "Could not read the changelog."}
            </p>
          ) : entries.length === 0 ? (
            <p className="changelog-status">No changelog entries yet.</p>
          ) : (
            entries.map((entry) => (
              <section key={entry.version} className="changelog-entry">
                <header className="changelog-entry-head">
                  <span className="changelog-entry-version">{entry.version}</span>
                  {entry.version === data?.version ? (
                    <span className="changelog-entry-current">Installed</span>
                  ) : null}
                  <span className="changelog-entry-date">{formatEntryDate(entry.date)}</span>
                </header>
                <MarkdownRenderer text={entry.body} />
              </section>
            ))
          )}
        </div>
        <div className="confirm-dialog-footer">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
