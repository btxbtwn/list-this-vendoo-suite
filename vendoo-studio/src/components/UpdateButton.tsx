import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

const POLL_MS = 10 * 60 * 1000;

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

function promptForUpdate(data: {
  behind?: number;
  summary?: string;
  commits?: string[];
  packaged?: boolean;
  short_sha?: string;
  remote_sha?: string;
}) {
  if (data.packaged) {
    const sha = data.short_sha || (data.remote_sha ? data.remote_sha.slice(0, 7) : "new");
    return window.confirm(
      `A new List This Studio Mac build is on GitHub (${sha}).\n\n${data.summary || ""}\n\nDownload and install it now? The app will quit and reopen.`,
    );
  }
  const n = data.behind || 0;
  const lines = (data.commits || []).slice(0, 5);
  const body = [
    `Update available on main (${n} commit${n === 1 ? "" : "s"}).`,
    data.summary ? `\n${data.summary}` : "",
    lines.length ? `\n${lines.join("\n")}` : "",
    "\n\nUpdate now and reload List This Studio from main?",
  ].join("");
  return window.confirm(body);
}

export function UpdateButton() {
  const queryClient = useQueryClient();
  const askedRef = useRef<string | null>(null);
  const [waiting, setWaiting] = useState(false);

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["updates"],
    queryFn: api.updates.status,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });

  const apply = useMutation({
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
      window.alert(err.message || "Update failed.");
    },
  });

  useEffect(() => {
    if (!data?.available || !data.remote_sha || waiting || apply.isPending) return;
    const key = `vendoo-studio-update-${data.remote_sha}`;
    if (askedRef.current === key || sessionStorage.getItem(key)) return;
    askedRef.current = key;
    sessionStorage.setItem(key, "1");
    if (promptForUpdate(data)) apply.mutate();
  }, [data, waiting, apply.isPending]);

  const busy = apply.isPending || waiting;
  const checking = isFetching && !data?.available && !busy;
  const available = Boolean(data?.available) && !busy;
  const label = busy
    ? "Updating…"
    : available
      ? "Update available"
      : checking
        ? "Checking for updates…"
        : "Check for updates";

  const onClick = async () => {
    if (busy) return;
    const latest = data?.available ? data : (await refetch()).data;
    if (!latest) return;
    if (latest.error && !latest.available) {
      window.alert(latest.error);
      return;
    }
    if (!latest.available) {
      window.alert("Already up to date with main.");
      return;
    }
    if (promptForUpdate(latest)) apply.mutate();
  };

  return (
    <button
      type="button"
      className={`sidebar-update-btn${available ? " update-available" : ""}${busy || checking ? " is-busy" : ""}`}
      onClick={onClick}
      disabled={busy}
      aria-label={label}
      title={data?.error || data?.summary || label}
    >
      {available ? <UpdateAvailableIcon /> : <RefreshIcon />}
    </button>
  );
}

function RefreshIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M21 3v5h-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 16H3v5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function UpdateAvailableIcon() {
  return (
    <span className="sidebar-update-icon">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 15V3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="m7 10 5 5 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="sidebar-update-dot" aria-hidden="true" />
    </span>
  );
}
