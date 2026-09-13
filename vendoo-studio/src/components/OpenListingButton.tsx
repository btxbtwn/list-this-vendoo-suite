import type { MouseEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { addToast } from "../ui/toast";

function stopWindowDrag(event: MouseEvent) {
  event.stopPropagation();
}

export function OpenListingButton({
  jobId,
  vendooItemId,
  vendooUrl,
  className,
}: {
  jobId: string;
  vendooItemId?: string | null;
  vendooUrl?: string | null;
  className?: string;
}) {
  const open = useMutation({
    mutationFn: () => api.jobs.open(jobId),
    onError: (err: Error) => {
      addToast({
        type: "error",
        title: "Could not open listing",
        description: err.message || "Could not open the listing in Vendoo.",
      });
    },
  });

  if (!vendooItemId && !vendooUrl) return null;

  return (
    <button
      type="button"
      className={className || "btn btn-secondary btn-sm"}
      disabled={open.isPending}
      title="Open this listing in Vendoo"
      aria-label="Open listing in Vendoo"
      onMouseDown={stopWindowDrag}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        open.mutate();
      }}
    >
      {open.isPending ? "Opening…" : "Open listing"}
    </button>
  );
}
