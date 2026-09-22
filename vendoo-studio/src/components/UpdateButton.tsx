import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";

const POLL_MS = 60 * 1000;

type UpdateStatus = Awaited<ReturnType<typeof api.updates.status>>;

async function waitForReload() {
  // Give the restart thread a moment to begin shutting down.
  await new Promise((resolve) => setTimeout(resolve, 500));
  let sawDown = false;
  for (let i = 0; i < 60; i++) {
    try {
      await api.health();
      if (sawDown) {
        window.location.reload();
        return;
      }
    } catch {
      sawDown = true;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  window.location.reload();
}

export function updateHeadline(data: { summary?: string | null } | null | undefined): string {
  return (data?.summary || "")
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean) || "";
}

export function installConfirmationMessage(data: UpdateStatus) {
  const version = data.short_sha || (data.remote_sha ? data.remote_sha.slice(0, 7) : "");
  const headline = updateHeadline(data);
  const lines = data.commits || [];
  if (data.packaged) {
    const title = headline
      ? `Install “${headline}” and restart List This Studio?`
      : `Install update${version ? ` ${version}` : ""} and restart List This Studio?`;
    const details = [
      version ? `Build ${version}` : "",
      headline ? "" : "A new Mac build is on GitHub.",
      ...lines.filter((line) => line.trim() && line.trim() !== headline),
    ].filter(Boolean);
    return [
      title,
      "",
      ...details,
      "",
      "The app will quit and reopen. Make sure you're ready before continuing.",
    ].join("\n");
  }
  const n = data.behind || 0;
  const title = headline
    ? `Install “${headline}” and restart List This Studio?`
    : `Install update${version ? ` ${version}` : ""} and restart List This Studio?`;
  const details = [
    headline ? "" : `Update available on main (${n} commit${n === 1 ? "" : "s"}).`,
    ...lines.filter((line) => line.trim() && line.trim() !== headline),
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

  const { data: progress } = useQuery({
    queryKey: ["update-progress"],
    queryFn: api.updates.progress,
    refetchInterval: (query) =>
      query.state.data?.status === "downloading" || query.state.data?.status === "installing" ? 300 : false,
  });

  const download = useMutation({
    mutationKey: ["studio-update-download"],
    mutationFn: api.updates.download,
    onMutate: () => {
      queryClient.setQueryData(["update-progress"], {
        status: "downloading",
        download_percent: 0,
        sha: null,
        error: null,
      });
    },
    onSuccess: (result) => {
      if (!result.updated) {
        void queryClient.invalidateQueries({ queryKey: ["updates"] });
        void queryClient.invalidateQueries({ queryKey: ["update-progress"] });
        return;
      }
      queryClient.setQueryData(["update-progress"], {
        status: "downloaded",
        download_percent: 100,
        sha: result.sha || null,
        error: null,
      });
      addToast({
        type: "success",
        title: "Update downloaded",
        description: "Restart the app from the update button to install it.",
      });
    },
    onError: (err: Error) => {
      void queryClient.invalidateQueries({ queryKey: ["update-progress"] });
      addToast({
        type: "error",
        title: "Could not download update",
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  const restart = useMutation({
    mutationKey: ["studio-update-restart"],
    mutationFn: api.updates.restart,
    onSuccess: async (result) => {
      if (!result.updated) return;
      setWaiting(true);
      await waitForReload();
    },
    onError: (err: Error) => {
      setWaiting(false);
      void queryClient.invalidateQueries({ queryKey: ["update-progress"] });
      addToast({
        type: "error",
        title: "Could not install update",
        description: err.message || "An unexpected error occurred.",
      });
    },
  });

  const downloading = download.isPending || progress?.status === "downloading";
  const downloaded = progress?.status === "downloaded";
  const restarting = restart.isPending || waiting || progress?.status === "installing";
  const busy = downloading || restarting;
  const available = Boolean(data?.available);
  const checking = isFetching && !busy && !downloaded && !available;
  const upToDate = isFetched && !available && !busy && !downloaded;
  const downloadPercent = downloading ? progress?.download_percent ?? 0 : null;

  const settingsLabel = restarting
    ? "Restarting…"
    : downloading
      ? `Downloading ${Math.round(downloadPercent || 0)}%`
      : downloaded
        ? "Restart to Update"
        : checking && !isFetched
          ? "Checking…"
          : available
            ? "Download Update"
            : upToDate
              ? "Up to Date"
              : "Check for Updates";

  const description = downloaded
    ? "Update downloaded and ready to install."
    : available
      ? updateHeadline(data) || "Update available."
      : "Current version of the application.";

  const iconTooltip = restarting
    ? "Restarting to install update…"
    : downloading
      ? `Downloading update (${Math.round(downloadPercent || 0)}%)`
      : downloaded
        ? "Restart to update"
        : checking
          ? "Checking for updates…"
          : available
            ? updateHeadline(data) || "Update available"
            : data?.error || "Check for updates";

  const onClick = async () => {
    if (busy) return;
    if (downloaded) {
      const latest = data || (await refetch()).data;
      if (!latest) return;
      const confirmed = await confirmDialog(installConfirmationMessage(latest), { variant: "destructive" });
      if (confirmed) restart.mutate();
      return;
    }
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
    download.mutate();
  };

  return {
    available,
    busy,
    checking,
    downloaded,
    downloading,
    downloadPercent,
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

function DownloadIcon({ showDot = true }: { showDot?: boolean }) {
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
      {showDot ? <span className="sidebar-update-dot" /> : null}
    </span>
  );
}

const DOWNLOAD_PROGRESS_RADIUS = 14;
const DOWNLOAD_PROGRESS_CIRCUMFERENCE = 2 * Math.PI * DOWNLOAD_PROGRESS_RADIUS;

/** Clamp a download percent for the sidebar progress ring. */
export function normalizeDownloadPercent(percent: number | null | undefined): number {
  return Math.min(
    100,
    Math.max(0, typeof percent === "number" && Number.isFinite(percent) ? percent : 0),
  );
}

function DownloadProgressIcon({ percent }: { percent: number | null }) {
  const normalized = normalizeDownloadPercent(percent);
  const offset = DOWNLOAD_PROGRESS_CIRCUMFERENCE * (1 - normalized / 100);
  // Before the first byte lands the arc is empty — spin a short segment so the
  // control still reads as active. Spin the outer wrapper so it never fights
  // the ring's -90° start angle (same continuous spin as T3's animate-spin).
  const indeterminate = normalized <= 0;
  return (
    <span className="sidebar-update-progress-icon">
      <span
        className={
          indeterminate
            ? "sidebar-update-progress-spin is-indeterminate"
            : "sidebar-update-progress-spin"
        }
        aria-hidden="true"
      >
        <svg className="sidebar-update-progress-ring" viewBox="0 0 32 32">
          <circle className="sidebar-update-progress-track" cx="16" cy="16" r={DOWNLOAD_PROGRESS_RADIUS} />
          <circle
            className="sidebar-update-progress-value"
            cx="16"
            cy="16"
            r={DOWNLOAD_PROGRESS_RADIUS}
            strokeDasharray={DOWNLOAD_PROGRESS_CIRCUMFERENCE}
            strokeDashoffset={indeterminate ? DOWNLOAD_PROGRESS_CIRCUMFERENCE * 0.75 : offset}
          />
        </svg>
      </span>
      {indeterminate ? (
        <DownloadIcon showDot={false} />
      ) : (
        <span className="sidebar-update-progress-pct">{Math.round(normalized)}</span>
      )}
    </span>
  );
}

function RestartIcon() {
  return (
    <span className="sidebar-update-restart-icon">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M20 11a8 8 0 10-2.34 5.66" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
        <path d="M20 5v6h-6" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="sidebar-update-ready-check" aria-hidden="true">✓</span>
    </span>
  );
}

export function UpdateButton() {
  const { available, busy, checking, downloaded, downloading, downloadPercent, iconTooltip, onClick } = useStudioUpdate();
  const showAvailable = available && !busy && !checking && !downloaded;

  return (
    <button
      type="button"
      // Keep the control enabled while busy so the webview does not wash it out —
      // onClick already no-ops when busy, and aria-disabled carries the state.
      className={`sidebar-update-btn${showAvailable || busy || downloaded ? " is-active" : ""}${busy ? " is-busy" : ""}`}
      onClick={onClick}
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      aria-label={iconTooltip}
      title={iconTooltip}
    >
      {downloading ? (
        <DownloadProgressIcon percent={downloadPercent} />
      ) : downloaded ? (
        <RestartIcon />
      ) : showAvailable ? (
        <DownloadIcon />
      ) : (
        <RefreshIcon spinning={checking || busy} />
      )}
    </button>
  );
}
