import React, { useState } from "react";
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings-provider"] });
    },
  });

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.settings.testConnection();
      setTestResult(result.ok ? "Connection successful!" : "Connection failed");
    } catch (err: any) {
      setTestResult(`Error: ${err.message}`);
    }
    setTesting(false);
  };

  return (
    <div style={{ maxWidth: 480, margin: "0 auto", padding: 24 }}>
      <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 24 }}>Settings</h2>

      <div style={{ marginBottom: 24, padding: 16, background: "var(--color-surface)", borderRadius: "var(--radius-lg)", border: "1px solid var(--color-border)" }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Xiaomi MiMo API</h3>

        <div style={{ marginBottom: 12 }}>
          <label className="label">Status</label>
          <span style={{ fontSize: 13 }}>
            {provider?.configured ? (
              <span style={{ color: "var(--color-success)" }}>
                Configured · Key: {provider.masked_key}
              </span>
            ) : (
              <span style={{ color: "var(--color-text-muted)" }}>Not configured</span>
            )}
          </span>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label className="label">Vision Model</label>
          <input className="input" value={provider?.vision_model || "mimo-v2.5"} readOnly style={{ background: "var(--color-bg)" }} />
        </div>

        <div style={{ marginBottom: 16 }}>
          <label className="label">Listing Model</label>
          <input className="input" value={provider?.listing_model || "mimo-v2.5-pro"} readOnly style={{ background: "var(--color-bg)" }} />
        </div>

        <div style={{ marginBottom: 12 }}>
          <label className="label">API Key</label>
          <input
            className="input"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
            style={{ fontFamily: "var(--font-mono)" }}
          />
        </div>

        <p style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 12 }}>
          Your key is stored securely in macOS Keychain and never sent to the browser or extension.
        </p>

        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setKeyMutation.mutate(apiKey)}
            disabled={!apiKey.trim()}
          >
            Save Key
          </button>
          {provider?.configured && (
            <>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleTest}
                disabled={testing}
              >
                {testing ? "Testing..." : "Test Connection"}
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={() => deleteKeyMutation.mutate()}
              >
                Remove Key
              </button>
            </>
          )}
        </div>
        {testResult && (
          <div style={{ marginTop: 8, fontSize: 13, color: testResult.includes("successful") ? "var(--color-success)" : "var(--color-error)" }}>
            {testResult}
          </div>
        )}
      </div>
    </div>
  );
}
