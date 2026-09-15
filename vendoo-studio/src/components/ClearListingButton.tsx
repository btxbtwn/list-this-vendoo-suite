import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";
import { resetChatLive } from "./ChatPanel";

const CLEAR_WARNING = [
  "Clear this listing and start over?",
  "Photos, chat, generated fields, and item details will be removed. This listing stays in the sidebar as a blank draft. Anything already saved on Vendoo is not deleted.",
].join("\n");

export function ClearListingButton({
  convId,
  className,
  onCleared,
}: {
  convId: string;
  className?: string;
  onCleared?: () => void;
}) {
  const queryClient = useQueryClient();
  const reset = useMutation({
    mutationFn: () => api.conversations.reset(convId),
    onSuccess: () => {
      resetChatLive(convId);
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["photos", convId] });
      queryClient.invalidateQueries({ queryKey: ["messages", convId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["fill-log"] });
      queryClient.invalidateQueries({ queryKey: ["vendoo-item"] });
      queryClient.invalidateQueries({ queryKey: ["vendoo-item-peek"] });
      queryClient.invalidateQueries({ queryKey: ["settings-hidden-fields"] });
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

  return (
    <button
      type="button"
      className={className || "btn btn-ghost btn-sm"}
      disabled={reset.isPending}
      title="Clear this listing and start over"
      aria-label="Clear listing"
      onClick={async () => {
        const confirmed = await confirmDialog(CLEAR_WARNING, {
          variant: "destructive",
          confirmLabel: "Clear listing",
        });
        if (!confirmed) return;
        reset.mutate();
      }}
    >
      {reset.isPending ? "Clearing..." : "Clear"}
    </button>
  );
}
