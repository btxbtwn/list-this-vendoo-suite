import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { confirmDialog, isConfirmDialogOpen } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";

type PullOffer = {
  conversation_id: string;
  item_id: string;
  conflict: boolean;
  offered_at: string;
};

function offerMessage(offer: PullOffer, title: string | null): string {
  const listing = title?.trim() || "this listing";
  if (offer.conflict) {
    return (
      `Pull changes from Vendoo for ${listing}?\n` +
      "Vendoo and Studio both changed. Pulling replaces Studio's current draft with Vendoo's."
    );
  }
  return (
    `Pull changes from Vendoo for ${listing}?\n` +
    "Vendoo was saved. Pull to bring those edits into Studio."
  );
}

/**
 * When the extension notices a seller Save on Vendoo (or focus-sync finds a
 * drift), Studio records a pull offer. This host asks once, then pulls or
 * dismisses — no Vendoo polling.
 */
export function VendooPullOfferHost({
  conversationTitles,
}: {
  conversationTitles: Record<string, string>;
}) {
  const queryClient = useQueryClient();
  const promptingRef = React.useRef(false);

  const { data } = useQuery({
    queryKey: ["vendoo-pull-offers"],
    queryFn: api.vendooApi.pullOffers,
    refetchInterval: 2000,
  });

  React.useEffect(() => {
    const offers = data?.offers || [];
    if (!offers.length || promptingRef.current || isConfirmDialogOpen()) return;

    const offer = offers[0]!;
    promptingRef.current = true;
    const title = conversationTitles[offer.conversation_id] || null;

    // Drop this offer from the cache immediately so a refetch cannot re-open
    // the same dialog while the seller is answering.
    queryClient.setQueryData<{ offers: PullOffer[] }>(["vendoo-pull-offers"], (prev) => ({
      offers: (prev?.offers || []).filter((row) => row.conversation_id !== offer.conversation_id),
    }));

    void (async () => {
      try {
        const confirmed = await confirmDialog(offerMessage(offer, title), {
          confirmLabel: "Pull",
        });
        if (confirmed) {
          await api.vendooApi.pull(offer.conversation_id);
          queryClient.invalidateQueries({ queryKey: ["listing", offer.conversation_id] });
          queryClient.invalidateQueries({ queryKey: ["listing-fields", offer.conversation_id] });
          queryClient.invalidateQueries({ queryKey: ["vendoo-item"] });
          addToast({
            type: "success",
            title: "Pulled from Vendoo",
            description: "Saved as a new revision.",
          });
        } else {
          await api.vendooApi.dismissPullOffer(offer.conversation_id);
        }
      } catch (err) {
        addToast({
          type: "error",
          title: "Could not read from Vendoo",
          description: err instanceof Error ? err.message : String(err),
        });
      } finally {
        queryClient.invalidateQueries({ queryKey: ["vendoo-pull-offers"] });
        promptingRef.current = false;
      }
    })();
  }, [data, conversationTitles, queryClient]);

  return null;
}
