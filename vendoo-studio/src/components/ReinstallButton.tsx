import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";

async function waitForReload() {
  for (let i = 0; i < 45; i++) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      await api.health();
      window.location.reload();
      return;
    } catch {
      /* server is restarting */
    }
  }
  window.location.reload();
}

const CONFIRM_MESSAGE = [
  "Download a fresh Mac build from GitHub and replace this app?",
  "",
  "Listing data and settings stay on this Mac. The app will quit and reopen.",
].join("\n");

/** Packaged Mac app only — force-download the published zip and replace the bundle. */
export function ReinstallButton() {
  const queryClient = useQueryClient();
  const [waiting, setWaiting] = useState(false);
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 4000,
  });

  const reinstall = useMutation({
    mutationKey: ["studio-reinstall"],
    mutationFn: api.updates.reinstall,
    onSuccess: async (result) => {
      if (!result.updated) {
        queryClient.invalidateQueries({ queryKey: ["updates"] });
        return;
      }
      setWaiting(true);
      await waitForReload();
    },
    onError: (err: Error) => {
      setWaiting(false);
      addToast({
        type: "error",
        title: "Could not reinstall",
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  if (!status?.packaged) return null;

  const busy = reinstall.isPending || waiting;
  const label = busy ? "Reinstalling…" : "Reinstall";

  return (
    <button
      type="button"
      className="status-reinstall-btn"
      disabled={busy}
      title="Download the latest Mac build and replace this app"
      aria-label={label}
      onClick={async () => {
        if (busy) return;
        const confirmed = await confirmDialog(CONFIRM_MESSAGE, { variant: "destructive" });
        if (confirmed) reinstall.mutate();
      }}
    >
      {label}
    </button>
  );
}
