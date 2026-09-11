import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function ConnectChromeButton({ compact = false }: { compact?: boolean }) {
  const queryClient = useQueryClient();
  const connect = useMutation({
    mutationFn: api.desktop.connectChrome,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["extension-status"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (err: Error) => {
      window.alert(err.message || "Could not open Chrome.");
    },
  });

  return (
    <button
      type="button"
      className={compact ? "status-connect" : "btn btn-secondary btn-sm"}
      disabled={connect.isPending}
      onClick={() => connect.mutate()}
    >
      {connect.isPending ? "Opening Chrome…" : "Connect Chrome"}
    </button>
  );
}
