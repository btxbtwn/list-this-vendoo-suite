import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { addToast } from "../ui/toast";

/**
 * Bring Vendoo's edits back into Studio.
 *
 * Pushing Studio → Vendoo is the single footer Send button (create or save).
 * Pull is the opposite direction and does not list anything.
 *
 * Opening the listing / window focus only *detects* drift and records a pull
 * offer; {@link VendooPullOfferHost} asks before applying. The extension also
 * records an offer when the seller hits Save on web.vendoo.co.
 */
export function VendooSyncButtons({ convId, bound, className }: {
  convId: string;
  bound: boolean;
  className?: string;
}) {
  const queryClient = useQueryClient();

  React.useEffect(() => {
    if (!bound) return undefined;
    let cancelled = false;
    const run = () => {
      api.vendooApi
        .sync(convId)
        .then((res) => {
          if (cancelled || res.action === "none") return;
          if (res.action === "offer") {
            queryClient.invalidateQueries({ queryKey: ["vendoo-pull-offers"] });
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
      queryClient.invalidateQueries({ queryKey: ["vendoo-item-peek"] });
      queryClient.invalidateQueries({ queryKey: ["vendoo-pull-offers"] });
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
