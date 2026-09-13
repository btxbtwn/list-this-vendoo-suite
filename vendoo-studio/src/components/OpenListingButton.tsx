import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";

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
      window.alert(err.message || "Could not open the listing in Vendoo.");
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
      onClick={() => open.mutate()}
    >
      {open.isPending ? "Opening…" : "Open listing"}
    </button>
  );
}
