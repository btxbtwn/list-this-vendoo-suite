import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { addToast } from "../ui/toast";

/**
 * Bring Vendoo's edits back into Studio.
 *
 * Pushing Studio → Vendoo is the single footer Send button (create or save).
 * Pull is the opposite direction and does not list anything.
 */
export function VendooSyncButtons({ convId, bound, className }: {
  convId: string;
  bound: boolean;
  className?: string;
}) {
  const queryClient = useQueryClient();

  // Sync when the listing is opened and whenever the app comes back to the
  // front, so the request pattern follows the seller rather than a clock. A
  // timer would be a steady, obviously automated heartbeat against Vendoo.
  React.useEffect(() => {
    if (!bound) return undefined;
    let cancelled = false;
    const run = () => {
      api.vendooApi
        .sync(convId)
        .then((res) => {
          if (cancelled || res.action === "none") return;
          if (res.action === "pull") {
            queryClient.invalidateQueries({ queryKey: ["listing", convId] });
            queryClient.invalidateQueries({ queryKey: ["listing-fields", convId] });
            queryClient.invalidateQueries({ queryKey: ["vendoo-item"] });
            addToast({
              type: "success",
              title: "Updated from Vendoo",
              description: "Changes made in Vendoo are now in Studio.",
            });
          } else if (res.action === "conflict") {
            addToast({
              type: "error",
              title: "Changed in both places",
              description: "Vendoo and Studio both changed. Send or Pull to choose which wins.",
            });
          }
        })
        .catch(() => {
          // A sync that cannot run is not worth interrupting anyone over.
        });
    };
    run();
    const onFocus = () => run();
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", onFocus);
    };
  }, [convId, bound, queryClient]);

  const pull = useMutation({
    mutationFn: () => api.vendooApi.pull(convId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      queryClient.invalidateQueries({ queryKey: ["listing-fields", convId] });
      queryClient.invalidateQueries({ queryKey: ["vendoo-item"] });
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
  return (
    <button
      type="button"
      className={className}
      disabled={pull.isPending}
      title="Bring changes made in Vendoo back into Studio"
      aria-label="Pull from Vendoo"
      onMouseDown={(event) => event.stopPropagation()}
      onClick={() => pull.mutate()}
    >
      {pull.isPending ? "Pulling…" : "Pull"}
    </button>
  );
}
