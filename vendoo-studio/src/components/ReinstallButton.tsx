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

function ReinstallSpinner() {
  return (
    <svg
      className="status-reinstall-glyph is-spinning"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M3 3v5h5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      <path
        d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M21 21v-5h-5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

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
    <span className={`status-reinstall${busy ? " is-busy" : ""}`}>
      {busy ? (
        <span
          className="status-bar-loading"
          role="progressbar"
          aria-label="Reinstalling from GitHub"
          aria-busy="true"
        />
      ) : null}
      <button
        type="button"
        className="status-reinstall-btn"
        disabled={busy}
        title={busy ? "Downloading and replacing List This Studio…" : "Download the latest Mac build and replace this app"}
        aria-label={label}
        aria-busy={busy}
        onClick={async () => {
          if (busy) return;
          const confirmed = await confirmDialog(CONFIRM_MESSAGE, { variant: "destructive" });
          if (confirmed) reinstall.mutate();
        }}
      >
        {busy ? <ReinstallSpinner /> : null}
        <span>{label}</span>
      </button>
    </span>
  );
}
