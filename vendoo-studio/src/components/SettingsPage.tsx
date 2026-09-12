import { type ReactNode, useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ConnectChromeButton } from "./ConnectChromeButton";
import { useStudioUpdate } from "./UpdateButton";

function SettingsSection({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="settings-section">
      <h2 className="settings-section-title">{title}</h2>
      <div className="settings-group">{children}</div>
    </section>
  );
}

function SettingsRow({
  title,
  description,
  status,
  control,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  status?: ReactNode;
  control?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="settings-row">
      <div className="settings-row-main">
        <div className="settings-row-copy">
          <h3 className="settings-row-title">{title}</h3>
          {description ? <p className="settings-row-desc">{description}</p> : null}
          {status ? <div className="settings-row-status">{status}</div> : null}
        </div>
        {control ? <div className="settings-row-control">{control}</div> : null}
      </div>
      {children}
    </div>
  );
}

function AboutVersionRow({ version }: { version: string }) {
  const { available, busy, description, iconTooltip, onClick, settingsLabel } = useStudioUpdate();
  return (
    <SettingsRow
      title={
        <span className="settings-version-title">
          Version
          <code className="settings-row-code">{version}</code>
        </span>
      }
      description={description}
      control={
        <button
          type="button"
          className={`btn btn-sm ${available && !busy ? "btn-primary" : "btn-outline"}`}
          onClick={onClick}
          disabled={busy}
          title={iconTooltip}
        >
          {settingsLabel}
        </button>
      }
    />
  );
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
  });
  const { data: provider } = useQuery({
    queryKey: ["settings-provider"],
    queryFn: api.settings.provider,
  });
  const chatgptSignedIn = Boolean(provider?.chatgpt?.signed_in);
  const { data: chatgptModels } = useQuery({
    queryKey: ["chatgpt-models"],
    queryFn: api.settings.chatgptModels,
    enabled: chatgptSignedIn,
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

  const refreshProvider = () => {
    queryClient.invalidateQueries({ queryKey: ["settings-provider"] });
    queryClient.invalidateQueries({ queryKey: ["chatgpt-models"] });
    queryClient.invalidateQueries({ queryKey: ["status"] });
  };

  const chatgptLoginMutation = useMutation({
    mutationFn: () => api.settings.chatgptLogin(),
    onSuccess: refreshProvider,
  });
  const chatgptCancelMutation = useMutation({
    mutationFn: () => api.settings.chatgptCancelLogin(),
    onSuccess: refreshProvider,
  });
  const chatgptLogoutMutation = useMutation({
    mutationFn: () => api.settings.chatgptLogout(),
    onSuccess: refreshProvider,
  });
  const setChatGPTModelsMutation = useMutation({
    mutationFn: (models: { vision_model?: string; listing_model?: string }) =>
      api.settings.setChatGPTModels(models),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings-provider"] });
      queryClient.invalidateQueries({ queryKey: ["chatgpt-models"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });

  const chatgpt = provider?.chatgpt;
  const chatgptPending = chatgpt?.pending;
  const pendingCode = chatgptPending?.user_code;
  const mimoConfigured = Boolean(provider?.masked_key);
  const visionModel = chatgptModels?.vision_model || provider?.vision_model || "mimo-v2.5";
  const listingModel = chatgptModels?.listing_model || provider?.listing_model || "mimo-v2.5-pro";
  const modelOptions = (() => {
    const slugs = [...(chatgptModels?.models || [])];
    for (const slug of [visionModel, listingModel]) {
      if (slug && !slugs.includes(slug)) slugs.push(slug);
    }
    return slugs;
  })();

  useEffect(() => {
    if (!pendingCode) return;
    const id = window.setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ["settings-provider"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    }, 2000);
    return () => window.clearInterval(id);
  }, [pendingCode, queryClient]);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.settings.testConnection();
      setTestResult(result.ok ? "Connection successful" : (result.error || "Connection failed"));
    } catch (err: any) {
      setTestResult(`Error: ${err.message}`);
    }
    setTesting(false);
  };

  const saveKey = () => {
    if (!apiKey.trim()) return;
    setKeyMutation.mutate(apiKey);
  };

  return (
    <div className="settings-page">
      <div className="settings-page-inner">
        <SettingsSection id="chatgpt" title="ChatGPT">
          <SettingsRow
            title="Sign in with ChatGPT"
            description="Uses your ChatGPT subscription to generate listings. Usage counts against Codex quota, not a Platform API key."
            status={
              chatgptSignedIn && testResult ? (
                <span className={testResult.includes("successful") ? "text-success" : "text-error"}>{testResult}</span>
              ) : chatgpt?.error ? (
                <span className="text-error">{chatgpt.error}</span>
              ) : null
            }
            control={
              chatgptSignedIn ? (
                <>
                  <button type="button" className="btn btn-sm btn-outline" onClick={handleTest} disabled={testing}>
                    {testing ? "Testing…" : "Test"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost settings-danger"
                    onClick={() => chatgptLogoutMutation.mutate()}
                    disabled={chatgptLogoutMutation.isPending}
                  >
                    Sign out
                  </button>
                </>
              ) : chatgptPending ? (
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  onClick={() => chatgptCancelMutation.mutate()}
                  disabled={chatgptCancelMutation.isPending}
                >
                  Cancel
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={() => chatgptLoginMutation.mutate()}
                  disabled={chatgptLoginMutation.isPending}
                >
                  {chatgptLoginMutation.isPending ? "Starting…" : "Sign in"}
                </button>
              )
            }
          >
            {chatgptSignedIn ? (
              <p className="settings-row-desc">
                Signed in{chatgpt.email ? ` as ${chatgpt.email}` : ""}
                {chatgpt.plan ? ` · ${chatgpt.plan}` : ""}. Listings use this account first.
              </p>
            ) : chatgptPending ? (
              <p className="settings-row-desc">
                Open{" "}
                <a href={chatgptPending.verification_url} target="_blank" rel="noreferrer">
                  {chatgptPending.verification_url}
                </a>{" "}
                and enter code <code className="settings-row-code">{chatgptPending.user_code}</code>
              </p>
            ) : chatgptLoginMutation.isError ? (
              <p className="settings-row-desc text-error">{(chatgptLoginMutation.error as Error).message}</p>
            ) : null}
          </SettingsRow>
        </SettingsSection>

        <SettingsSection id="models" title="Models">
          <SettingsRow
            title="Vision model"
            description="Used to read product photos."
            status={chatgptSignedIn && chatgptModels?.error ? <span className="text-error">{chatgptModels.error}</span> : null}
            control={
              chatgptSignedIn ? (
                <select
                  className="input settings-model-select"
                  aria-label="Vision model"
                  value={visionModel}
                  disabled={setChatGPTModelsMutation.isPending || modelOptions.length === 0}
                  onChange={(event) => setChatGPTModelsMutation.mutate({ vision_model: event.target.value })}
                >
                  {modelOptions.map((slug) => (
                    <option key={`vision-${slug}`} value={slug}>
                      {slug}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="settings-row-value">{visionModel}</span>
              )
            }
          />
          <SettingsRow
            title="Listing model"
            description="Used to write marketplace copy."
            control={
              chatgptSignedIn ? (
                <select
                  className="input settings-model-select"
                  aria-label="Listing model"
                  value={listingModel}
                  disabled={setChatGPTModelsMutation.isPending || modelOptions.length === 0}
                  onChange={(event) => setChatGPTModelsMutation.mutate({ listing_model: event.target.value })}
                >
                  {modelOptions.map((slug) => (
                    <option key={`listing-${slug}`} value={slug}>
                      {slug}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="settings-row-value">{listingModel}</span>
              )
            }
          />
        </SettingsSection>

        <SettingsSection id="provider" title="Xiaomi MiMo">
          <SettingsRow
            title="API key"
            description="Stored in macOS Keychain and never sent to the browser."
          >
            <div className="settings-row-field">
              <input
                className="input font-mono"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveKey();
                }}
                placeholder="sk-..."
                autoComplete="off"
                spellCheck={false}
              />
              <button type="button" className="btn btn-sm btn-outline" onClick={saveKey} disabled={!apiKey.trim() || setKeyMutation.isPending}>
                {setKeyMutation.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          </SettingsRow>
          <SettingsRow
            title="Status"
            description={
              mimoConfigured
                ? `Configured · ${provider?.masked_key}`
                : chatgptSignedIn
                  ? "Fallback when ChatGPT is signed out"
                  : "Not configured"
            }
            status={
              !chatgptSignedIn && testResult ? (
                <span className={testResult.includes("successful") ? "text-success" : "text-error"}>{testResult}</span>
              ) : null
            }
            control={
              mimoConfigured ? (
                <>
                  {!chatgptSignedIn ? (
                    <button type="button" className="btn btn-sm btn-outline" onClick={handleTest} disabled={testing}>
                      {testing ? "Testing…" : "Test"}
                    </button>
                  ) : null}
                  <button type="button" className="btn btn-sm btn-ghost settings-danger" onClick={() => deleteKeyMutation.mutate()}>
                    Remove
                  </button>
                </>
              ) : null
            }
          />
        </SettingsSection>

        <SettingsSection id="connections" title="Connections">
          <SettingsRow
            title="Vendoo in Chrome"
            description="Send to Vendoo opens a Studio-managed Chrome window with the listing extension already loaded. Sign in to Vendoo there once."
            control={<ConnectChromeButton className="btn btn-sm btn-outline" />}
          />
        </SettingsSection>

        <SettingsSection id="about" title="About">
          <AboutVersionRow version={status?.version || "0.1.0"} />
        </SettingsSection>
      </div>
    </div>
  );
}
