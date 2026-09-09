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
  dirty?: string[];
}) {
  const n = data.behind || 0;
  const lines = (data.commits || []).slice(0, 5);
    const body = [
      `Update available on main (${n} commit${n === 1 ? "" : "s"}).`,
      data.summary ? `\n${data.summary}` : "",
      lines.length ? `\n${lines.join("\n")}` : "",
      data.dirty?.length ? "\n\nYou have uncommitted changes. Commit or stash first." : "",
      "\n\nUpdate now and reload Vendoo Studio?",
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
      window.alert(err.message || "Update failed.");
    },
  });

  useEffect(() => {
    if (!data?.available || !data.remote_sha || waiting || apply.isPending) return;
    if (data.dirty?.length) return;
    const key = `vendoo-studio-update-${data.remote_sha}`;
    if (askedRef.current === key || sessionStorage.getItem(key)) return;
    askedRef.current = key;
    sessionStorage.setItem(key, "1");
    if (promptForUpdate(data)) apply.mutate();
  }, [data, waiting, apply.isPending]);

  const busy = apply.isPending || waiting;
  const label = busy
    ? "Updating…"
    : data?.available
      ? "Update available"
      : isFetching
        ? "Checking…"
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
    if (latest.dirty?.length) {
      window.alert("Uncommitted changes. Commit or stash before updating.");
      return;
    }
    if (promptForUpdate(latest)) apply.mutate();
  };

  return (
    <button
      className={`btn btn-sm sidebar-update-btn${data?.available ? " update-available" : ""}`}
      onClick={onClick}
      disabled={busy}
      title={data?.error || data?.summary || "Check origin/main for updates"}
    >
      {label}
    </button>
  );
}
