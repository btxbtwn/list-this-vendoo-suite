import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type MouseEvent, type ReactNode } from "react";
import { api } from "../api/client";
import { RegenerateListingButton, useClearListing } from "./ClearListingButton";
import { OpenListingButton } from "./OpenListingButton";

/* T3 Code marks a browser surface with lucide's globe-2 (RightPanelTabs.tsx),
   drawn at the same 16px / stroke-2 as the titlebar's panel toggles. */
function BrowserIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M21.54 15H17a2 2 0 0 0-2 2v4.54" />
      <path d="M7 3.34V5a3 3 0 0 0 3 3a2 2 0 0 1 2 2c0 1.1.9 2 2 2a2 2 0 0 0 2-2c0-1.1.9-2 2-2h3.17" />
      <path d="M11 21.95V18a2 2 0 0 0-2-2a2 2 0 0 1-2-2v-1a2 2 0 0 0-2-2H2.05" />
    </svg>
  );
}

/* lucide `ellipsis`. T3 Code hangs a thread's rare and destructive actions off
   one of these rather than spending titlebar width on them. */
function MoreIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="1" />
      <circle cx="19" cy="12" r="1" />
      <circle cx="5" cy="12" r="1" />
    </svg>
  );
}

function notesVendooItemId(notes?: string | null): string | null {
  if (!notes) return null;
  try {
    const parsed = JSON.parse(notes);
    const itemId = String(parsed?.vendooItemId || "").trim();
    return itemId || null;
  } catch {
    return null;
  }
}

function notesVendooUrl(notes?: string | null): string | null {
  if (!notes) return null;
  try {
    const parsed = JSON.parse(notes);
    const url = String(parsed?.vendooUrl || "").trim();
    return url || null;
  } catch {
    return null;
  }
}

/** The listing's own job, plus the Vendoo ids the notes remember after a clear. */
function useListingJob(convId: string) {
  const { data: jobs } = useQuery({
    queryKey: ["jobs", convId],
    queryFn: () => api.jobs.list(convId),
    refetchInterval: 2000,
  });
  const { data: conversation } = useQuery({
    queryKey: ["conversation", convId],
    queryFn: () => api.conversations.get(convId),
  });
  const listingJob = jobs?.find((job) => job.conversation_id === convId && job.status !== "cancelled");
  return {
    listingJob,
    importedItemId: listingJob?.vendoo_item_id || notesVendooItemId(conversation?.notes),
    importedUrl: listingJob?.vendoo_url || notesVendooUrl(conversation?.notes),
  };
}

/** Icon-only, and it sits beside the inspector toggle: it opens a surface in the
    window the way T3 Code's panel toggles do, not a listing action like Clear. */
export function ListingBrowserButton({
  convId,
  browserOpen,
  onOpenBrowser,
  onMouseDown,
}: {
  convId: string;
  browserOpen?: boolean;
  onOpenBrowser?: (jobId: string) => void;
  onMouseDown?: (event: MouseEvent<HTMLElement>) => void;
}) {
  const { listingJob } = useListingJob(convId);
  if (!listingJob || !onOpenBrowser) return null;
  if (!listingJob.vendoo_item_id && !listingJob.vendoo_url) return null;

  return (
    <button
      type="button"
      className="titlebar-control"
      disabled={browserOpen}
      aria-label="Open the Vendoo draft in Studio"
      aria-pressed={browserOpen}
      title="Work in the Vendoo draft here: click, type, and point Studio at fields to fill"
      onMouseDown={onMouseDown}
      onClick={() => onOpenBrowser(listingJob.id)}
    >
      <BrowserIcon />
    </button>
  );
}

/** Everything rare enough not to earn a place in the titlebar. Clearing is the
    only item today, and it stays out of reach of the tabs next door. */
function ListingActionsMenu({ convId, onCleared }: { convId: string; onCleared?: () => void }) {
  const [open, setOpen] = useState(false);
  const { clear, isPending } = useClearListing(convId, onCleared);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: globalThis.MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest(".pr-menu-wrap")) return;
      setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="pr-menu-wrap">
      <button
        type="button"
        className="titlebar-control"
        aria-label="More listing actions"
        aria-haspopup="menu"
        aria-expanded={open}
        title="More listing actions"
        onClick={() => setOpen((value) => !value)}
      >
        <MoreIcon />
      </button>
      {open ? (
        <div className="pr-menu pr-menu-fit" role="menu">
          <button
            type="button"
            role="menuitem"
            className="pr-menu-item pr-menu-item-destructive"
            disabled={isPending}
            onClick={() => {
              setOpen(false);
              void clear();
            }}
          >
            {isPending ? "Clearing..." : "Clear listing"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Open listing / Regenerate / More — header actions for a listing. */
export function ListingReviewActions({
  convId,
  onCleared,
  className,
  onMouseDown,
  children,
}: {
  convId: string;
  onCleared?: () => void;
  className?: string;
  onMouseDown?: (event: MouseEvent<HTMLElement>) => void;
  /** Mobile keeps the browser button in this row; the titlebar does not. */
  children?: ReactNode;
}) {
  const { listingJob, importedItemId, importedUrl } = useListingJob(convId);

  return (
    <div
      className={`pr-review-actions${className ? ` ${className}` : ""}`}
      onMouseDown={onMouseDown}
    >
      {listingJob ? (
        <OpenListingButton
          jobId={listingJob.id}
          vendooItemId={listingJob.vendoo_item_id || importedItemId}
          vendooUrl={listingJob.vendoo_url || importedUrl}
          className="pr-review-open"
        />
      ) : null}
      {children}
      <RegenerateListingButton convId={convId} className="pr-review-open" onRegenerated={onCleared} />
      <ListingActionsMenu convId={convId} onCleared={onCleared} />
    </div>
  );
}
