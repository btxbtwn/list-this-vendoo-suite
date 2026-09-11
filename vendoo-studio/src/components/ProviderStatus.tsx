import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function ProviderStatus() {
  const { data } = useQuery({
    queryKey: ["settings-provider"],
    queryFn: api.settings.provider,
    refetchInterval: 10000,
  });

  const modelName = data?.listing_model || "mimo-v2.5-pro";

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span className={`status-dot ${data?.configured ? "connected" : ""}`} />
      <span>{modelName}</span>
    </span>
  );
}
