import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function ProviderStatus() {
  const { data } = useQuery({
    queryKey: ["settings-provider"],
    queryFn: api.settings.provider,
    refetchInterval: 10000,
  });

  const connected = Boolean(data?.configured);
  const modelName = connected ? (data?.listing_model || "listing model") : "Not configured";

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span className={`status-dot ${connected ? "connected" : ""}`} />
      <span>{modelName}</span>
    </span>
  );
}
