import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { addToast } from "../ui/toast";

/**
 * Push Studio's edits onto the Vendoo draft, and bring Vendoo's back.
 *
 * Both are explicit: a save writes only the fields that differ, and a pull
 * lands as a new revision rather than overwriting what is on screen. Neither
 * lists anything — publishing is its own action.
 */
export function VendooSyncButtons({ convId, bound, className }: {
  convId: string;
  bound: boolean;
  className?: string;
}) {
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: () => api.vendooApi.save(convId),
    onSuccess: (res) => {
      addToast({
        type: "success",
        title: res.updated.length ? "Saved to Vendoo" : "Nothing to save",
        description: res.updated.length
          ? `${res.updated.length} field${res.updated.length === 1 ? "" : "s"} written.`
          : "Vendoo already matches this listing.",
      });
    },
    onError: (err: Error) =>
      addToast({ type: "error", title: "Could not save to Vendoo", description: err.message }),
  });

  const pull = useMutation({
    mutationFn: () => api.vendooApi.pull(convId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      queryClient.invalidateQueries({ queryKey: ["listing-fields", convId] });
      addToast({
        type: "success",
        title: "Pulled from Vendoo",
        description: "Saved as a new revision.",
      });
    },
    onError: (err: Error) =>
      addToast({ type: "error", title: "Could not read from Vendoo", description: err.message }),
  });

  if (!bound) return null;
  const busy = save.isPending || pull.isPending;
  return (
    <>
      <button
        type="button"
        className={className}
        disabled={busy}
        title="Write this listing's changed fields onto the Vendoo draft"
        onMouseDown={(event) => event.stopPropagation()}
        onClick={() => save.mutate()}
      >
        {save.isPending ? "Saving…" : "Save to Vendoo"}
      </button>
      <button
        type="button"
        className={className}
        disabled={busy}
        title="Bring changes made in Vendoo back into Studio"
        onMouseDown={(event) => event.stopPropagation()}
        onClick={() => pull.mutate()}
      >
        {pull.isPending ? "Pulling…" : "Pull from Vendoo"}
      </button>
    </>
  );
}
