import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ConnectChromeButton } from "./ConnectChromeButton";

export function ExtensionStatus() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: 5000,
  });

  const reload = useMutation({
    mutationFn: api.extension.reload,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["extension-status"] });
    },
    onError: (err: Error) => {
      window.alert(err.message || "Could not reload the extension.");
    },
  });

  const connected = Boolean(data?.connected);
  const outdated = data?.up_to_date === false;
  const expected = data?.expected_version || null;
  const running = data?.version || null;

  let label = "Extension offline";
  if (outdated) label = "Extension outdated";
  else if (connected) label = "Extension connected";

  const title = outdated
    ? [
        expected ? `This Studio build expects extension ${expected}.` : "This Studio build has a newer extension.",
        running ? `Chrome is running ${running}.` : "Reload the extension so it matches this build.",
      ].join(" ")
    : undefined;

  const dotClass = outdated ? "outdated" : connected ? "connected" : "";

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span className={`status-dot ${dotClass}`} />
      <span className={outdated ? "status-outdated" : undefined} title={title}>
        {label}
      </span>
      {!connected && <ConnectChromeButton compact />}
      {connected && outdated && (
        <button
          type="button"
          className="status-connect"
          disabled={reload.isPending}
          title={title}
          onClick={() => reload.mutate()}
        >
          {reload.isPending ? "Reloading…" : "Reload"}
        </button>
      )}
    </span>
  );
}
