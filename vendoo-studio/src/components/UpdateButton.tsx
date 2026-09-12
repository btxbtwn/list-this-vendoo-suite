import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";

const POLL_MS = 10 * 60 * 1000;

type UpdateStatus = Awaited<ReturnType<typeof api.updates.status>>;

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

function installConfirmationMessage(data: UpdateStatus) {
  const version = data.short_sha || (data.remote_sha ? data.remote_sha.slice(0, 7) : "");
  const title = `Install update${version ? ` ${version}` : ""} and restart List This Studio?`;
  if (data.packaged) {
    return [
      title,
      "",
      data.summary || "A new Mac build is on GitHub.",
      "",
      "The app will quit and reopen. Make sure you're ready before continuing.",
    ].join("\n");
  }
  const n = data.behind || 0;
  const lines = (data.commits || []).slice(0, 5);
  const details = [
    data.summary || `Update available on main (${n} commit${n === 1 ? "" : "s"}).`,
    ...lines,
  ].filter(Boolean);
  return [
    title,
    "",
    ...details,
    "",
    "Any running tasks will be interrupted. Make sure you're ready before continuing.",
  ].join("\n");
}

export function useStudioUpdate() {
  const queryClient = useQueryClient();
  const [waiting, setWaiting] = useState(false);

  const { data, isFetching, isFetched, refetch } = useQuery({
    queryKey: ["updates"],
    queryFn: api.updates.status,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });

  const apply = useMutation({
    mutationKey: ["studio-update-apply"],
    mutationFn: api.updates.apply,
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
      queryClient.invalidateQueries({ queryKey: ["updates"] });
      addToast({
        type: "error",
        title: "Could not install update",
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  const busy = apply.isPending || waiting;
  const available = Boolean(data?.available);
  const checking = isFetching && !busy && !available;
  const upToDate = isFetched && !available && !busy;

  const settingsLabel = busy
    ? "Updating…"
    : checking && !isFetched
      ? "Checking…"
      : available
        ? "Update"
        : upToDate
          ? "Up to Date"
          : "Check for Updates";

  const description = available
    ? "Update available."
    : "Current version of the application.";

  const iconTooltip = busy
    ? "Updating…"
    : checking
      ? "Checking for updates…"
      : available
        ? data?.summary || "Update available"
        : data?.error || "Check for updates";

  const onClick = async () => {
    if (busy) return;
    const latest = data?.available ? data : (await refetch()).data;
    if (!latest) return;
    if (latest.error && !latest.available) {
      addToast({
        type: "error",
        title: "Could not check for updates",
        description: latest.error,
      });
      return;
    }
    if (!latest.available) return;
    const confirmed = await confirmDialog(installConfirmationMessage(latest), { variant: "destructive" });
    if (confirmed) apply.mutate();
  };

  return {
    available,
    busy,
    checking,
    description,
    iconTooltip,
    settingsLabel,
    onClick,
  };
}

function RefreshIcon({ spinning }: { spinning?: boolean }) {
  return (
    <svg
      className={spinning ? "sidebar-update-glyph is-spinning" : "sidebar-update-glyph"}
      width="16"
      height="16"
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

function DownloadIcon() {
  return (
    <span className="sidebar-update-available-icon">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M7 10l5 5 5-5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M12 15V3" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      </svg>
      <span className="sidebar-update-dot" />
    </span>
  );
}

export function UpdateButton() {
  const { available, busy, checking, iconTooltip, onClick } = useStudioUpdate();
  const showAvailable = available && !busy && !checking;

  return (
    <button
      type="button"
      className={`sidebar-update-btn${showAvailable || busy ? " is-active" : ""}`}
      onClick={onClick}
      disabled={busy}
      aria-label={iconTooltip}
      title={iconTooltip}
    >
      {showAvailable ? <DownloadIcon /> : <RefreshIcon spinning={busy || checking} />}
    </button>
  );
}
