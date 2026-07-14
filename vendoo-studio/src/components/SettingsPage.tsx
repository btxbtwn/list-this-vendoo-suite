import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  const { data: provider } = useQuery({
    queryKey: ["settings-provider"],
    queryFn: api.settings.provider,
  });

  const setKeyMutation = useMutation({
    mutationFn: (key: string) => api.settings.setProvider(key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings-provider"] });
      setApiKey("");
    },
  });

  const deleteKeyMutation = useMutation({
    mutationFn: () => api.settings.deleteKey(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings-provider"] }),
  });

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.settings.testConnection();
      setTestResult(result.ok ? "Connection successful" : "Connection failed");
    } catch (err: any) {
      setTestResult(`Error: ${err.message}`);
    }
    setTesting(false);
  };

  return (
    <div style={{ maxWidth: 480, margin: "32px auto", padding: "0 16px" }}>
      <div className="settings-card">
        <h2>Xiaomi MiMo API</h2>

        <div className="field-row">
          <label className="label">Status</label>
          <span className="text-sm">
            {provider?.configured ? (
              <span className="text-success">Configured · {provider.masked_key}</span>
            ) : (
              <span className="text-muted">Not configured</span>
            )}
          </span>
        </div>

        <div className="field-row">
          <label className="label">Vision Model</label>
          <input className="input" value={provider?.vision_model || "mimo-v2.5"} readOnly style={{ background: "var(--color-surface-secondary)" }} />
        </div>

        <div className="field-row">
          <label className="label">Listing Model</label>
          <input className="input" value={provider?.listing_model || "mimo-v2.5-pro"} readOnly style={{ background: "var(--color-surface-secondary)" }} />
        </div>

        <div className="field-row">
          <label className="label">API Key</label>
          <input className="input" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." style={{ fontFamily: "var(--font-mono)" }} />
        </div>

        <p className="text-xs text-muted mt-4" style={{ marginBottom: 12 }}>
          Your key is stored in macOS Keychain and never sent to the browser.
        </p>

        <div className="flex-row">
          <button className="btn btn-primary btn-sm" onClick={() => setKeyMutation.mutate(apiKey)} disabled={!apiKey.trim()}>Save Key</button>
          {provider?.configured && (
            <>
              <button className="btn btn-secondary btn-sm" onClick={handleTest} disabled={testing}>{testing ? "Testing..." : "Test Connection"}</button>
              <button className="btn btn-danger btn-sm" onClick={() => deleteKeyMutation.mutate()}>Remove Key</button>
            </>
          )}
        </div>
        {testResult && (
          <div className="mt-8 text-sm" style={{ color: testResult.includes("successful") ? "var(--color-success)" : "var(--color-error)" }}>{testResult}</div>
        )}
      </div>
    </div>
  );
}
