import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ProviderLogo, resolveProviderLogoId } from "./ProviderLogo";

export function providerStatusModelLabel(
  configured: boolean,
  listingModel: string | undefined | null,
): string {
  if (!configured) return "Not configured";
  return listingModel?.trim() || "listing model";
}

export function ProviderStatus() {
  const { data } = useQuery({
    queryKey: ["settings-provider"],
    queryFn: api.settings.provider,
    refetchInterval: 10000,
  });

  const connected = Boolean(data?.configured);
  const logoId = resolveProviderLogoId(data?.provider);
  const providerLabel =
    logoId === "chatgpt"
      ? "ChatGPT"
      : logoId === "mimo"
        ? "MiMo"
        : logoId === "cursor"
          ? "Cursor"
          : "Listing AI";
  const modelName = providerStatusModelLabel(connected, data?.listing_model);
  const title = connected && logoId ? `${providerLabel} · ${modelName}` : modelName;

  return (
    <span className="status-provider" title={title}>
      {!connected ? <span className="status-dot error" /> : null}
      {connected && logoId ? <ProviderLogo id={logoId} label={providerLabel} size={14} /> : null}
      <span>{modelName}</span>
    </span>
  );
}
