import { useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";
import { queueChatGenerate, resetChatLive, useChatBusy } from "./ChatPanel";
import { RegeneratePriceDialog } from "./RegeneratePriceDialog";

const CLEAR_WARNING = [
  "Clear this listing and start over?",
  "Photos, chat, generated fields, and item details will be removed. This listing stays in the sidebar as a blank draft. If it was imported from Vendoo, that connection is kept. Anything already saved on Vendoo is not deleted.",
].join("\n");

const REGENERATE_WARNING = [
  "Rewrite this listing from scratch?",
  "Chat and every generated field are discarded, then the listing is written again from your photos and item details. Measurements, flaws, COG, labels and notes are kept. Vendoo is unchanged until you send again.",
].join("\n");

async function refreshAfterReset(queryClient: QueryClient, convId: string) {
  queryClient.invalidateQueries({ queryKey: ["conversations"] });
  queryClient.invalidateQueries({ queryKey: ["jobs"] });
  queryClient.invalidateQueries({ queryKey: ["fill-log"] });
  queryClient.invalidateQueries({ queryKey: ["vendoo-item"] });
  queryClient.invalidateQueries({ queryKey: ["vendoo-item-peek"] });
  queryClient.invalidateQueries({ queryKey: ["settings-hidden-fields"] });
  queryClient.invalidateQueries({ queryKey: ["listing-fields", convId] });
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["listing", convId] }),
    queryClient.invalidateQueries({ queryKey: ["conversation", convId] }),
    queryClient.invalidateQueries({ queryKey: ["photos", convId] }),
    queryClient.invalidateQueries({ queryKey: ["messages", convId] }),
  ]);
}

/** Clear lives in the titlebar's overflow menu, so the confirm dialog and the
    mutation must outlive the menu popup the click came from. */
export function useClearListing(convId: string, onCleared?: () => void) {
  const queryClient = useQueryClient();
  const reset = useMutation({
    mutationFn: () => api.conversations.reset(convId),
    onSuccess: () => {
      resetChatLive(convId);
      void refreshAfterReset(queryClient, convId);
      onCleared?.();
      addToast({ type: "success", title: "Listing cleared", description: "Upload photos to start again." });
    },
    onError: (err: Error) => {
      addToast({
        type: "error",
        title: "Could not clear listing",
        description: err.message || "The listing could not be cleared.",
      });
    },
  });

  return {
    isPending: reset.isPending,
    async clear() {
      const confirmed = await confirmDialog(CLEAR_WARNING, {
        variant: "destructive",
        confirmLabel: "Clear listing",
      });
      if (!confirmed) return;
      reset.mutate();
    },
  };
}

function listingHasPrice(listing: Record<string, unknown> | undefined): boolean {
  if (!listing) return false;
  const raw = listing.price;
  const amount = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(amount) && amount > 0;
}

/** When the listing has a price, opens the comps/percent drop chooser, which
 *  offers the rewrite itself. Otherwise a single confirm precedes the rewrite. */
export function RegenerateListingButton({
  convId,
  className,
  onRegenerated,
}: {
  convId: string;
  className?: string;
  onRegenerated?: () => void;
}) {
  const queryClient = useQueryClient();
  const busy = useChatBusy(convId);
  const [priceDialogOpen, setPriceDialogOpen] = useState(false);
  const { data: photos } = useQuery({
    queryKey: ["photos", convId],
    queryFn: () => api.conversations.photos(convId),
  });
  const { data: listingData } = useQuery({
    queryKey: ["listing", convId],
    queryFn: () => api.listings.get(convId),
  });
  const hasPhotos = Boolean(photos?.length);
  const hasPrice = listingHasPrice(listingData?.listing);

  const regenerate = useMutation({
    mutationFn: async () => {
      resetChatLive(convId);
      await api.conversations.reset(convId, { keepInputs: true });
      // Chat must see the empty listing before it starts, or it reads the old
      // listing JSON as "generation already finished".
      await refreshAfterReset(queryClient, convId);
    },
    onSuccess: () => {
      queueChatGenerate(convId);
      onRegenerated?.();
    },
    onError: (err: Error) => {
      addToast({
        type: "error",
        title: "Could not regenerate listing",
        description: err.message || "The listing could not be reset.",
      });
    },
  });

  async function confirmFullRegenerate() {
    const confirmed = await confirmDialog(REGENERATE_WARNING, {
      variant: "destructive",
      confirmLabel: "Rewrite",
    });
    if (!confirmed) return;
    regenerate.mutate();
  }

  return (
    <>
      <button
        type="button"
        className={className || "btn btn-ghost btn-sm"}
        disabled={regenerate.isPending || busy || !hasPhotos}
        title={!hasPhotos
          ? "Add photos to generate a listing"
          : busy
            ? "Wait for the current generation to finish"
            : hasPrice
              ? "Drop the price, or rewrite the listing from scratch"
              : "Discard chat and generated fields, then write the listing again"}
        onClick={() => {
          if (hasPrice) {
            setPriceDialogOpen(true);
            return;
          }
          void confirmFullRegenerate();
        }}
      >
        {regenerate.isPending ? "Resetting..." : "Regenerate"}
      </button>

      <RegeneratePriceDialog
        convId={convId}
        open={priceDialogOpen}
        onClose={() => setPriceDialogOpen(false)}
        onFullRegenerate={() => {
          regenerate.mutate();
        }}
      />
    </>
  );
}
