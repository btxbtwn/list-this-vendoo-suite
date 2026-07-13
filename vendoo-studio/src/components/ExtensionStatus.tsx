import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function ExtensionStatus() {
  const { data } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: 5000,
  });

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span className={`status-dot ${data?.connected ? "connected" : ""}`} />
      <span>{data?.connected ? "Extension connected" : "Extension offline"}</span>
    </span>
  );
}
