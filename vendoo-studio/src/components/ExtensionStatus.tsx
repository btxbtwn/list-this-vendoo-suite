import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ConnectChromeButton } from "./ConnectChromeButton";

export function ExtensionStatus() {
  const { data } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: 5000,
  });

  const connected = Boolean(data?.connected);
  const outdated = connected && data?.up_to_date === false;
  const expected = data?.expected_version || null;
  const running = data?.version || null;

  let label = "Extension offline";
  if (outdated) label = "Extension outdated";
  else if (connected) label = "Extension connected";

  const title = outdated
    ? [
        expected ? `This Studio build expects extension ${expected}.` : "This Studio build has a newer extension.",
        running ? `Chrome is running ${running}.` : "Connect Chrome again so it matches this build.",
        "Reload the unpacked extension on chrome://extensions if the version does not update.",
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
