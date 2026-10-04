import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { EXTENSION_STATUS_POLL_MS, pollMs } from "../api/polling";
import { ConnectChromeButton } from "./ConnectChromeButton";

export function ExtensionStatus() {
  const { data } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    // Connect Chrome polls on its own while it waits for the pairing.
    refetchInterval: () => pollMs(EXTENSION_STATUS_POLL_MS),
  });

  const connected = Boolean(data?.connected);
  const outdated = connected && data?.up_to_date === false;
  const expected = data?.expected_version || null;
  const running = data?.version || null;
  const loadPath = data?.load_path || null;

  let label = "Extension offline";
  if (outdated) label = "Extension outdated";
  else if (connected) label = "Extension connected";

  const title = outdated
    ? [
        expected ? `This Studio build expects extension ${expected}.` : "This Studio build has a newer extension.",
        running ? `Chrome is running ${running}.` : "Chrome is not on Studio's copy yet.",
        loadPath ? `Load unpacked from ${loadPath}.` : "Load the unpacked folder shown in Settings → Connections.",
        "Connect Chrome reloads that folder so it stays in lockstep.",
      ].join(" ")
    : undefined;

  const dotClass = outdated ? "outdated" : connected ? "connected" : "";

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span className={`status-dot ${dotClass}`} />
      <span className={outdated ? "status-outdated" : undefined} title={title}>
        {label}
      </span>
      {(!connected || outdated) && <ConnectChromeButton compact />}
    </span>
  );
}
