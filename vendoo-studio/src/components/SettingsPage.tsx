import { type ReactNode, useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ListingFallbackId, ListingProviderId } from "../api/types";
import { ConnectChromeButton } from "./ConnectChromeButton";
import { ExtensionLoadPath } from "./ExtensionLoadPath";
import { useStudioUpdate } from "./UpdateButton";
import {
  DEFAULT_SETTINGS_SECTION,
  type SettingsSectionId,
} from "./settingsNav";

function providerLabel(choice: ListingProviderId | ListingFallbackId): string {
  if (choice === "auto") return "Auto";
  if (choice === "chatgpt") return "ChatGPT";
  if (choice === "mimo") return "MiMo";
  if (choice === "cursor") return "Cursor";
  return "None";
}

function activeProviderChoice(providerName: string | undefined): Exclude<ListingProviderId, "auto"> | null {
  if (providerName === "chatgpt") return "chatgpt";
  if (providerName === "xiaomi-mimo") return "mimo";
  if (providerName === "cursor") return "cursor";
  return null;
}

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
    <section id={id} className="settings-section" tabIndex={-1}>
      <h2 className="settings-section-title">{title}</h2>
      <div className="settings-group">{children}</div>
    </section>
  );
}

function SettingsRow({
  id,
  title,
  description,
  status,
  control,
  children,
}: {
  id?: string;
  title: ReactNode;
  description?: ReactNode;
  status?: ReactNode;
  control?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div id={id} className="settings-row" tabIndex={id ? -1 : undefined}>
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

function orderedSelection(
  available: { id: string }[],
  selected: Iterable<string>,
): string[] {
  const chosen = new Set(selected);
  return available.map((item) => item.id).filter((id) => chosen.has(id));
}

function CategoryTreesRow() {
  const queryClient = useQueryClient();
  const {data, error} = useQuery({queryKey: ["category-trees"], queryFn: api.catalog.status,
    refetchInterval: 3000});
  const sync = useMutation({mutationFn: api.catalog.sync,
    onSuccess: () => queryClient.invalidateQueries({queryKey: ["category-trees"]})});
  return <SettingsRow title="Marketplace category trees"
    description="Extract the full General, eBay, Poshmark, Mercari, Depop, and Etsy trees from Vendoo. Keep Chrome connected. Interrupted extraction resumes from its last saved branch."
    control={<button className="btn btn-sm btn-outline" disabled={data?.running || data?.complete || sync.isPending}
      onClick={() => sync.mutate()}>{data?.complete ? "Complete" : data?.running ? "Extracting…" : "Extract / resume"}</button>}>
    {Object.entries(data?.marketplaces || {}).map(([marketplace, tree]) =>
      <p className="settings-row-desc" key={marketplace}>
        {marketplace === "general" ? "General" : marketplace}: {tree.nodes.toLocaleString()} categories · {tree.status}
        {tree.pending_branches > 0 ? ` · ${tree.pending_branches} branches remaining` : ""}
        {tree.error ? ` — ${tree.error}` : ""}
      </p>)}
    {(error || sync.error) && <p role="alert">{(error || sync.error)?.message}</p>}
  </SettingsRow>;
}

function BraveSearchSection({ chatgptSignedIn }: { chatgptSignedIn: boolean }) {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const { data: brave } = useQuery({
    queryKey: ["settings-brave"],
    queryFn: api.settings.brave,
  });
  const setKeyMutation = useMutation({
    mutationFn: (key: string) => api.settings.setBrave(key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings-brave"] });
      setApiKey("");
      setTestResult(null);
    },
  });
  const deleteKeyMutation = useMutation({
    mutationFn: () => api.settings.deleteBrave(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings-brave"] });
      setTestResult(null);
    },
  });
  const configured = Boolean(brave?.configured);
  const saveKey = () => {
    if (!apiKey.trim()) return;
    setKeyMutation.mutate(apiKey);
  };
  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.settings.testBrave();
      setTestResult(result.ok ? "Connection successful" : result.error || "Connection failed");
    } catch (err) {
      setTestResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
    setTesting(false);
  };

  return (
    <SettingsSection id="brave" title="Brave Search">
      <SettingsRow
        id="brave-api-key"
        title="API key"
        description={
          <>
            Used to look up sold comps if ChatGPT web search is unavailable or finds nothing. Get a key at{" "}
            <a href="https://api.search.brave.com" target="_blank" rel="noreferrer">
              api.search.brave.com
            </a>
            . Stored in macOS Keychain and never sent to the browser.
          </>
        }
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
            placeholder="BSA..."
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
          configured
            ? `Fallback · ${brave?.masked_key}`
            : chatgptSignedIn
              ? "Optional fallback when ChatGPT web search misses comps"
              : "Not configured — listing prices use an estimated baseline unless ChatGPT is signed in"
        }
        status={
          testResult ? (
            <span className={testResult.includes("successful") ? "text-success" : "text-error"}>{testResult}</span>
          ) : setKeyMutation.isError ? (
            <span className="text-error">{(setKeyMutation.error as Error).message}</span>
          ) : null
        }
        control={
          configured ? (
            <>
              <button type="button" className="btn btn-sm btn-outline" onClick={handleTest} disabled={testing}>
                {testing ? "Testing…" : "Test"}
              </button>
              <button type="button" className="btn btn-sm btn-ghost settings-danger" onClick={() => deleteKeyMutation.mutate()}>
                Remove
              </button>
            </>
          ) : null
        }
      />
    </SettingsSection>
  );
}

function MarketplacesSection() {
  const queryClient = useQueryClient();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["settings-marketplaces"],
    queryFn: api.settings.marketplaces,
  });
  const mutation = useMutation({
    mutationFn: (selected: string[]) => api.settings.setMarketplaces(selected),
    onSuccess: (payload) => {
      queryClient.setQueryData(["settings-marketplaces"], payload);
    },
  });
  const available = data?.available || [];
  const selected = data?.selected || [];
  const selectedSet = new Set(selected);
  const save = (next: Iterable<string>) => mutation.mutate(orderedSelection(available, next));

  return (
    <SettingsSection id="marketplaces" title="Marketplaces">
      <SettingsRow
        title="List to"
        description="Empty-field prompts and Send to Vendoo use only the marketplaces you check."
        control={
          <>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={mutation.isPending || available.filter((item) => item.fillable).length === 0 || selected.filter((id) => available.find((item) => item.id === id)?.fillable).length === available.filter((item) => item.fillable).length}
              onClick={() => save(available.filter((item) => item.fillable).map((item) => item.id))}
            >
              All
            </button>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={mutation.isPending || selected.length === 0}
              onClick={() => save([])}
            >
              None
            </button>
          </>
        }
      >
        {isPending ? (
          <p className="settings-row-desc">Loading marketplaces…</p>
        ) : isError ? (
          <p className="settings-row-desc text-error">{(error as Error).message || "Could not load marketplaces"}</p>
        ) : (
          <div className="settings-marketplace-grid" role="group" aria-label="Marketplaces to list to">
            {available.map((item) => (
              <label key={item.id} className="settings-marketplace-option">
                <input
                  type="checkbox"
                  checked={item.fillable && selectedSet.has(item.id)}
                  disabled={mutation.isPending || !item.fillable}
                  onChange={(event) => {
                    if (!item.fillable) return;
                    const next = new Set(selected.filter((id) => available.find((entry) => entry.id === id)?.fillable));
                    if (event.target.checked) next.add(item.id);
                    else next.delete(item.id);
                    save(next);
                  }}
                />
                <span>
                  {item.label}
                  {!item.fillable ? " — unsupported for Send" : ""}
                </span>
              </label>
            ))}
            {available.some((item) => !item.fillable) ? (
              <p className="settings-row-desc">
                Facebook, Grailed, Whatnot, and Shopify are not available for Send. They cannot be selected,
                cannot enter an approved job snapshot, and are blocked before a job is created.
              </p>
            ) : null}
          </div>
        )}
        {mutation.isError ? (
          <p className="settings-row-desc text-error">{(mutation.error as Error).message}</p>
        ) : null}
      </SettingsRow>
    </SettingsSection>
  );
}

function HiddenFieldsSection() {
  const queryClient = useQueryClient();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["settings-hidden-fields"],
    queryFn: () => api.settings.hiddenFields(),
  });
  const restoreMutation = useMutation({
    mutationFn: (item: { marketplace: string; field: string }) =>
      api.settings.showField({ ...item, scope: "always" }),
    onSuccess: (payload) => {
      queryClient.setQueryData(["settings-hidden-fields"], payload);
      queryClient.invalidateQueries({ queryKey: ["settings-hidden-fields"] });
    },
  });
  const always = data?.always || [];

  return (
    <SettingsSection id="hidden-fields" title="Fields">
      <SettingsRow
        title="Always hidden"
        description="These marketplace fields stay off the Fields tab on every listing. Hide more from a field’s × menu, or restore them here."
      >
        {isPending ? (
          <p className="settings-row-desc">Loading hidden fields…</p>
        ) : isError ? (
          <p className="settings-row-desc text-error">{(error as Error).message || "Could not load hidden fields"}</p>
        ) : always.length === 0 ? (
          <p className="settings-row-desc">None yet. On Fields, open a field’s × menu and choose Always hide.</p>
        ) : (
          <div className="settings-hidden-list">
            {always.map((item) => (
              <div key={`${item.marketplace}:${item.field}`} className="settings-hidden-row">
                <div className="settings-hidden-copy">
                  <span className="settings-hidden-name">{item.label || item.field}</span>
                  <span className="settings-hidden-meta">
                    {item.marketplace === "general" ? "Vendoo" : item.marketplace}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  disabled={restoreMutation.isPending}
                  onClick={() => restoreMutation.mutate({ marketplace: item.marketplace, field: item.field })}
                >
                  Show
                </button>
              </div>
            ))}
          </div>
        )}
        {restoreMutation.isError ? (
          <p className="settings-row-desc text-error">{(restoreMutation.error as Error).message}</p>
        ) : null}
      </SettingsRow>
    </SettingsSection>
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

function DataFolderRow() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["settings-data-folder"],
    queryFn: api.settings.dataFolder,
  });
  const [copied, setCopied] = useState(false);
  const path = data?.path || "";

  const copy = async () => {
    if (!path) return;
    await navigator.clipboard.writeText(path);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <SettingsRow
      id="data-folder"
      title="Data folder"
      description="Listings, photos, drafts, hidden fields, fill logs, settings, and logs stay here when you reinstall the app. API keys remain in macOS Keychain on this Mac."
    >
      {isLoading ? (
        <p className="settings-row-desc">Looking up the data folder…</p>
      ) : error ? (
        <p className="settings-row-desc text-error">{(error as Error).message || "Could not load data folder"}</p>
      ) : (
        <div className="extension-load-path-row">
          <code className="extension-load-path-code">{path}</code>
          <button type="button" className="btn btn-sm btn-outline" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy path"}
          </button>
        </div>
      )}
    </SettingsRow>
  );
}

function ListingFormulasSection() {
  const queryClient = useQueryClient();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["settings-formulas"],
    queryFn: () => api.settings.formulas(),
  });
  const [draft, setDraft] = useState<{ title: string; description: string } | null>(null);

  const defaultTitle = data?.default_title || "";
  const defaultDescription = data?.default_description || "";
  const serverTitle = data ? data.title || defaultTitle : "";
  const serverDescription = data ? data.description || defaultDescription : "";
  const title = draft?.title ?? serverTitle;
  const description = draft?.description ?? serverDescription;

  const saveMutation = useMutation({
    mutationFn: (body: { title: string; description: string }) => api.settings.setFormulas(body),
    onSuccess: (payload) => {
      queryClient.setQueryData(["settings-formulas"], payload);
      setDraft(null);
    },
  });

  const dirty =
    draft !== null &&
    (draft.title.trim() !== serverTitle.trim() || draft.description.trim() !== serverDescription.trim());
  const usingCustom = Boolean(data?.title || data?.description);

  const persist = (nextTitle: string, nextDescription: string) => {
    const titleToSave = nextTitle.trim() === defaultTitle.trim() ? "" : nextTitle;
    const descriptionToSave = nextDescription.trim() === defaultDescription.trim() ? "" : nextDescription;
    saveMutation.mutate({ title: titleToSave, description: descriptionToSave });
  };

  return (
    <SettingsSection id="listing-formulas" title="Listing formulas">
      <SettingsRow
        title="Title and description"
        description="Studio pins these formulas into every listing generation. Leave them as the defaults, or edit the placeholders for your shop. Clearing a field and saving restores the built-in formula."
      >
        {isPending ? (
          <p className="settings-row-desc">Loading formulas…</p>
        ) : isError ? (
          <p className="settings-row-desc text-error">{(error as Error).message || "Could not load formulas"}</p>
        ) : (
          <div className="settings-formula-editor">
            <label className="settings-formula-field">
              <span className="settings-formula-label">Title</span>
              <input
                className="input"
                value={title}
                onChange={(e) => setDraft({ title: e.target.value, description })}
                spellCheck={false}
                aria-label="Title formula"
              />
            </label>
            <label className="settings-formula-field">
              <span className="settings-formula-label">Description</span>
              <textarea
                className="input settings-formula-textarea"
                value={description}
                onChange={(e) => setDraft({ title, description: e.target.value })}
                spellCheck={false}
                rows={6}
                aria-label="Description formula"
              />
            </label>
            <div className="settings-formula-actions">
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={saveMutation.isPending || !dirty}
                onClick={() => persist(title, description)}
              >
                {saveMutation.isPending ? "Saving…" : "Save formulas"}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-outline"
                disabled={saveMutation.isPending || (!usingCustom && !dirty)}
                onClick={() => {
                  setDraft({ title: defaultTitle, description: defaultDescription });
                  persist(defaultTitle, defaultDescription);
                }}
              >
                Reset to defaults
              </button>
            </div>
            {usingCustom ? (
              <p className="settings-row-desc">Custom formulas are active for new generations.</p>
            ) : (
              <p className="settings-row-desc">Using the built-in list-this formulas.</p>
            )}
          </div>
        )}
        {saveMutation.isError ? (
          <p className="settings-row-desc text-error">{(saveMutation.error as Error).message}</p>
        ) : null}
      </SettingsRow>
    </SettingsSection>
  );
}

function GeneralPanel({ onOpenSetupGuide }: { onOpenSetupGuide?: () => void }) {
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
  });
  return (
    <>
      <MarketplacesSection />
      <HiddenFieldsSection />
      <ListingFormulasSection />
      <SettingsSection id="setup-guide" title="Setup guide">
        <SettingsRow
          title="First-run tutorial"
          description="Walk through ChatGPT or MiMo, Brave Search, Connect Chrome, and how the listing workspace is laid out."
          control={
            <button type="button" className="btn btn-sm btn-outline" onClick={onOpenSetupGuide}>
              Open setup guide
            </button>
          }
        />
      </SettingsSection>
      <SettingsSection id="about" title="About">
        <DataFolderRow />
        <AboutVersionRow version={status?.version || "…"} />
      </SettingsSection>
    </>
  );
}

function ProvidersPanel() {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [cursorKey, setCursorKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [mimoTesting, setMimoTesting] = useState(false);
  const [mimoTestResult, setMimoTestResult] = useState<string | null>(null);
  const [cursorTesting, setCursorTesting] = useState(false);
  const [cursorTestResult, setCursorTestResult] = useState<string | null>(null);

  const { data: provider } = useQuery({
    queryKey: ["settings-provider"],
    queryFn: api.settings.provider,
  });
  const chatgptSignedIn = Boolean(provider?.chatgpt?.signed_in);
  const { data: chatgptModels } = useQuery({
    queryKey: ["chatgpt-models"],
    queryFn: api.settings.chatgptModels,
    enabled: chatgptSignedIn && provider?.provider === "chatgpt",
  });

  const refreshProvider = () => {
    queryClient.invalidateQueries({ queryKey: ["settings-provider"] });
    queryClient.invalidateQueries({ queryKey: ["chatgpt-models"] });
    queryClient.invalidateQueries({ queryKey: ["status"] });
  };

  const setKeyMutation = useMutation({
    mutationFn: (key: string) => api.settings.setProvider(key),
    onSuccess: () => {
      refreshProvider();
      setApiKey("");
      setMimoTestResult(null);
    },
  });

  const deleteKeyMutation = useMutation({
    mutationFn: () => api.settings.deleteKey(),
    onSuccess: () => {
      refreshProvider();
      setMimoTestResult(null);
    },
  });

  const setCursorMutation = useMutation({
    mutationFn: (key: string) => api.settings.setCursor(key),
    onSuccess: () => {
      refreshProvider();
      setCursorKey("");
    },
  });

  const deleteCursorMutation = useMutation({
    mutationFn: () => api.settings.deleteCursor(),
    onSuccess: refreshProvider,
  });

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
    mutationFn: (models: { vision_model?: string; listing_model?: string; reasoning_effort?: string }) =>
      api.settings.setChatGPTModels(models),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings-provider"] });
      queryClient.invalidateQueries({ queryKey: ["chatgpt-models"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const setPreferredMutation = useMutation({
    mutationFn: (order: { primary: ListingProviderId; fallback: ListingFallbackId }) =>
      api.settings.setPreferredProvider(order),
    onSuccess: refreshProvider,
  });

  const chatgpt = provider?.chatgpt;
  const chatgptPending = chatgpt?.pending;
  const pendingCode = chatgptPending?.user_code;
  const mimoConfigured = Boolean(provider?.masked_key);
  const cursorConfigured = Boolean(provider?.masked_cursor_key);
  const primary: ListingProviderId =
    provider?.primary === "auto" ||
    provider?.primary === "mimo" ||
    provider?.primary === "cursor" ||
    provider?.primary === "chatgpt"
      ? provider.primary
      : "chatgpt";
  const fallback: ListingFallbackId =
    primary === "auto"
      ? "none"
      : provider?.fallback === "chatgpt" ||
          provider?.fallback === "mimo" ||
          provider?.fallback === "cursor" ||
          provider?.fallback === "none"
        ? provider.fallback
        : primary === "chatgpt"
          ? "mimo"
          : "chatgpt";
  const usingChatGPT = provider?.provider === "chatgpt";
  const usingCursor = provider?.provider === "cursor";
  const activeChoice = activeProviderChoice(provider?.provider);
  const choiceReady = (choice: ListingFallbackId) =>
    choice === "chatgpt"
      ? chatgptSignedIn
      : choice === "mimo"
        ? mimoConfigured
        : choice === "cursor"
          ? cursorConfigured
          : false;
  const primaryReady =
    primary === "auto"
      ? chatgptSignedIn || mimoConfigured || cursorConfigured
      : choiceReady(primary);
  const fallbackReady = choiceReady(fallback);

  const saveOrder = (nextPrimary: ListingProviderId, nextFallback: ListingFallbackId) => {
    let fallbackValue = nextPrimary === "auto" ? "none" : nextFallback;
    if (fallbackValue === nextPrimary) {
      fallbackValue = "none";
    }
    setPreferredMutation.mutate({ primary: nextPrimary, fallback: fallbackValue });
  };

  const visionModel = usingChatGPT
    ? chatgptModels?.vision_model || provider?.vision_model || "gpt-5.5"
    : provider?.vision_model || (usingCursor ? "composer-2.5" : "mimo-v2.5");
  const listingModel = usingChatGPT
    ? chatgptModels?.listing_model || provider?.listing_model || "gpt-5.5"
    : provider?.listing_model || (usingCursor ? "composer-2.5" : "mimo-v2.5-pro");
  const reasoningEffort = chatgptModels?.reasoning_effort || "low";
  const reasoningOptions = chatgptModels?.reasoning_efforts?.length
    ? chatgptModels.reasoning_efforts
    : ["none", "low", "medium", "high", "xhigh"];
  const reasoningLabels: Record<string, string> = {
    none: "Off",
    low: "Low",
    medium: "Medium",
    high: "High",
    xhigh: "Extra high",
    max: "Max",
  };
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
    } catch (err) {
      setTestResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
    setTesting(false);
  };

  const handleMimoTest = async () => {
    setMimoTesting(true);
    setMimoTestResult(null);
    try {
      const result = await api.settings.testMimo();
      setMimoTestResult(result.ok ? "Connection successful" : (result.error || "Connection failed"));
    } catch (err) {
      setMimoTestResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
    setMimoTesting(false);
  };

  const handleCursorTest = async () => {
    setCursorTesting(true);
    setCursorTestResult(null);
    try {
      const result = await api.settings.testCursor();
      setCursorTestResult(result.ok ? "Connection successful" : (result.error || "Connection failed"));
    } catch (err) {
      setCursorTestResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
    setCursorTesting(false);
  };

  const saveKey = () => {
    if (!apiKey.trim()) return;
    setKeyMutation.mutate(apiKey);
  };

  const saveCursorKey = () => {
    if (!cursorKey.trim()) return;
    setCursorMutation.mutate(cursorKey);
  };

  return (
    <>
      <SettingsSection id="listing-ai" title="Listing AI">
        <SettingsRow
          title="Primary"
          description="Tried first when generating listings and reading photos. Auto picks the first ready provider (ChatGPT, then MiMo, then Cursor)."
          control={
            <select
              className="input settings-model-select"
              aria-label="Primary listing AI"
              value={primary}
              disabled={setPreferredMutation.isPending}
              onChange={(event) => saveOrder(event.target.value as ListingProviderId, fallback)}
            >
              <option value="auto">Auto</option>
              <option value="chatgpt">ChatGPT</option>
              <option value="mimo">Xiaomi MiMo</option>
              <option value="cursor">Cursor</option>
            </select>
          }
        />
        <SettingsRow
          title="Fallback"
          description={
            primary === "auto"
              ? "Not used when Primary is Auto."
              : "Used only when the primary provider is not ready."
          }
          control={
            <select
              className="input settings-model-select"
              aria-label="Fallback listing AI"
              value={primary === "auto" || fallback === primary ? "none" : fallback}
              disabled={setPreferredMutation.isPending || primary === "auto"}
              onChange={(event) =>
                saveOrder(primary, event.target.value as ListingFallbackId)
              }
            >
              <option value="none">None</option>
              {primary !== "chatgpt" && primary !== "auto" ? (
                <option value="chatgpt">ChatGPT</option>
              ) : null}
              {primary !== "mimo" && primary !== "auto" ? (
                <option value="mimo">Xiaomi MiMo</option>
              ) : null}
              {primary !== "cursor" && primary !== "auto" ? (
                <option value="cursor">Cursor</option>
              ) : null}
            </select>
          }
        />
        <SettingsRow title="In use">
          <p className="settings-row-desc">
            {provider?.configured && activeChoice
              ? `${providerLabel(activeChoice)} is active${
                  primary === "auto"
                    ? " (auto)"
                    : activeChoice === primary
                      ? " (primary)"
                      : " (fallback)"
                }.`
              : primaryReady
                ? `${providerLabel(primary)} is ready.`
                : fallback !== "none" && fallbackReady
                  ? `${providerLabel(primary)} is not ready — ${providerLabel(fallback)} will be used.`
                  : primary === "auto"
                    ? "Configure ChatGPT, MiMo, or Cursor below."
                    : `Configure ${providerLabel(primary)}${
                        fallback !== "none" ? ` or ${providerLabel(fallback)}` : ""
                      } below.`}
          </p>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection id="chatgpt" title="ChatGPT">
        <SettingsRow
          title="Sign in with ChatGPT"
          description="Uses your ChatGPT subscription to generate listings and look up sold comps. Usage counts against Codex quota, not a Platform API key."
          status={
            chatgptSignedIn && testResult && provider?.provider === "chatgpt" ? (
              <span className={testResult.includes("successful") ? "text-success" : "text-error"}>{testResult}</span>
            ) : chatgpt?.error ? (
              <span className="text-error">{chatgpt.error}</span>
            ) : null
          }
          control={
            chatgptSignedIn ? (
              <>
                {provider?.provider === "chatgpt" ? (
                  <button type="button" className="btn btn-sm btn-outline" onClick={handleTest} disabled={testing}>
                    {testing ? "Testing…" : "Test"}
                  </button>
                ) : null}
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
              Signed in{chatgpt?.email ? ` as ${chatgpt.email}` : ""}
              {chatgpt?.plan ? ` · ${chatgpt.plan}` : ""}.
              {primary === "chatgpt"
                ? " Primary for listings."
                : fallback === "chatgpt"
                  ? " Fallback for listings."
                  : " Not in the listing order."}
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
          status={usingChatGPT && chatgptModels?.error ? <span className="text-error">{chatgptModels.error}</span> : null}
          control={
            usingChatGPT ? (
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
            usingChatGPT ? (
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
        <SettingsRow
          title="Reasoning"
          description="Higher uses more Codex quota and takes longer. Default is Low. Applied to listing generation and photo analysis."
          control={
            usingChatGPT ? (
              <select
                className="input settings-model-select"
                aria-label="Reasoning"
                value={reasoningOptions.includes(reasoningEffort) ? reasoningEffort : reasoningOptions[0]}
                disabled={setChatGPTModelsMutation.isPending}
                onChange={(event) => setChatGPTModelsMutation.mutate({ reasoning_effort: event.target.value })}
              >
                {reasoningOptions.map((effort) => (
                  <option key={`reasoning-${effort}`} value={effort}>
                    {reasoningLabels[effort] || effort}
                  </option>
                ))}
              </select>
            ) : (
              <span className="settings-row-value">
                {usingCursor ? "Not used with Cursor" : "Not used with MiMo"}
              </span>
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
              ? primary === "mimo"
                ? `Primary · ${provider?.masked_key}`
                : fallback === "mimo"
                  ? `Fallback · ${provider?.masked_key}`
                  : `Saved · ${provider?.masked_key}`
              : primary === "mimo"
                ? "Primary — add a key to use MiMo"
                : fallback === "mimo"
                  ? "Fallback — add a key if ChatGPT is unavailable"
                  : "Not configured"
          }
          status={
            mimoTestResult ? (
              <span className={mimoTestResult.includes("successful") ? "text-success" : "text-error"}>{mimoTestResult}</span>
            ) : null
          }
          control={
            mimoConfigured ? (
              <>
                <button type="button" className="btn btn-sm btn-outline" onClick={handleMimoTest} disabled={mimoTesting}>
                  {mimoTesting ? "Testing…" : "Test"}
                </button>
                <button type="button" className="btn btn-sm btn-ghost settings-danger" onClick={() => deleteKeyMutation.mutate()}>
                  Remove
                </button>
              </>
            ) : null
          }
        />
      </SettingsSection>

      <SettingsSection id="cursor" title="Cursor">
        <SettingsRow
          title="API key"
          description="From Cursor Dashboard → Integrations. Stored in Keychain; listing runs use the local Cursor SDK against an empty scratch folder."
        >
          <div className="settings-row-field">
            <input
              className="input font-mono"
              type="password"
              value={cursorKey}
              onChange={(e) => setCursorKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveCursorKey();
              }}
              placeholder="cursor_..."
              autoComplete="off"
              spellCheck={false}
            />
            <button
              type="button"
              className="btn btn-sm btn-outline"
              onClick={saveCursorKey}
              disabled={!cursorKey.trim() || setCursorMutation.isPending}
            >
              {setCursorMutation.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </SettingsRow>
        <SettingsRow
          title="Status"
          description={
            cursorConfigured
              ? primary === "cursor"
                ? `Primary · ${provider?.masked_cursor_key}`
                : fallback === "cursor"
                  ? `Fallback · ${provider?.masked_cursor_key}`
                  : `Saved · ${provider?.masked_cursor_key}`
              : primary === "cursor"
                ? "Primary — add a Cursor API key"
                : fallback === "cursor"
                  ? "Fallback — add a key if other providers are unavailable"
                  : "Not configured"
          }
          status={
            cursorTestResult ? (
              <span className={cursorTestResult.includes("successful") ? "text-success" : "text-error"}>
                {cursorTestResult}
              </span>
            ) : null
          }
          control={
            cursorConfigured ? (
              <>
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  onClick={handleCursorTest}
                  disabled={cursorTesting}
                >
                  {cursorTesting ? "Testing…" : "Test"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost settings-danger"
                  onClick={() => deleteCursorMutation.mutate()}
                >
                  Remove
                </button>
              </>
            ) : null
          }
        />
      </SettingsSection>
    </>
  );
}

function IntegrationsPanel() {
  const { data: provider } = useQuery({
    queryKey: ["settings-provider"],
    queryFn: api.settings.provider,
  });
  return <BraveSearchSection chatgptSignedIn={Boolean(provider?.chatgpt?.signed_in)} />;
}

function ConnectionsPanel() {
  return (
    <SettingsSection id="connections" title="Connections">
      <TailscaleHttpsRow />
      <SettingsRow
        title="Vendoo in Chrome"
        description="Connect Chrome opens Vendoo in your everyday Chrome and reloads Studio's listing extension so it matches this build. Send to Vendoo creates or updates a draft over Vendoo's API using that signed-in session."
        control={<ConnectChromeButton className="btn btn-sm btn-outline" />}
      />
      <SettingsRow
        title="Listing extension folder"
        description="Copy this path. In chrome://extensions turn on Developer mode, click Load unpacked, press Control-Shift-G (⌘⇧G) to search for the folder, paste the path, then Open. Studio overwrites this folder on launch so Chrome and Studio stay on the same files."
      >
        <ExtensionLoadPath compact hideHint />
      </SettingsRow>
      <CategoryTreesRow />
    </SettingsSection>
  );
}

type TailscaleStatus = Awaited<ReturnType<typeof api.settings.tailscale>>;

function TailscaleHttpsRow() {
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["settings-tailscale"],
    queryFn: api.settings.tailscale,
    refetchInterval: 5000,
  });
  const enableMutation = useMutation({
    mutationFn: api.settings.enableTailscale,
    onSuccess: (payload) => {
      queryClient.setQueryData(["settings-tailscale"], payload);
    },
  });
  const disableMutation = useMutation({
    mutationFn: api.settings.disableTailscale,
    onSuccess: (payload) => {
      queryClient.setQueryData(["settings-tailscale"], payload);
    },
  });
  const busy = enableMutation.isPending || disableMutation.isPending;
  const actionError =
    (enableMutation.error as Error | null)?.message ||
    (disableMutation.error as Error | null)?.message ||
    null;

  async function copyUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  const control = (() => {
    if (isPending || !data) {
      return <span className="settings-row-value">Checking…</span>;
    }
    if (data.enabled) {
      return (
        <button
          type="button"
          className="btn btn-sm btn-outline"
          disabled={busy || data.state === "conflict" || data.funnel}
          onClick={() => disableMutation.mutate()}
        >
          {disableMutation.isPending ? "Disabling…" : "Disable"}
        </button>
      );
    }
    const canEnable = data.installed && Boolean(data.dns_name) && data.state !== "conflict" && !data.funnel;
    return (
      <button
        type="button"
        className="btn btn-sm btn-outline"
        disabled={busy || !canEnable}
        onClick={() => enableMutation.mutate()}
      >
        {enableMutation.isPending ? "Enabling…" : "Enable"}
      </button>
    );
  })();

  return (
    <SettingsRow
      id="tailscale-https"
      title="Tailscale HTTPS"
      description="Share this Mac's Studio with your phone over your private Tailnet. Studio stays on 127.0.0.1; Tailscale proxies HTTPS. Funnel stays off."
      control={control}
    >
      {isError ? (
        <p className="settings-row-desc text-error" role="alert">
          {(error as Error).message || "Could not read Tailscale status"}
        </p>
      ) : null}
      {data ? <TailscaleStatusDetails data={data} copied={copied} onCopy={copyUrl} /> : null}
      {actionError ? (
        <p className="settings-row-desc text-error" role="alert">
          {actionError}
        </p>
      ) : null}
    </SettingsRow>
  );
}

function TailscaleStatusDetails({
  data,
  copied,
  onCopy,
}: {
  data: TailscaleStatus;
  copied: boolean;
  onCopy: (url: string) => void;
}) {
  if (!data.installed) {
    return (
      <p className="settings-row-desc">
        Install Tailscale on this Mac and your phone, sign in to the same account, then enable here.
      </p>
    );
  }
  if (!data.dns_name) {
    return (
      <p className="settings-row-desc text-error" role="alert">
        {data.error || "Sign in to Tailscale on this Mac first."}
      </p>
    );
  }
  if (data.error && !data.enabled) {
    return (
      <p className="settings-row-desc text-error" role="alert">
        {data.error}
      </p>
    );
  }
  if (!data.enabled || !data.url) {
    return (
      <p className="settings-row-desc">
        After Enable, open the HTTPS link on any device on your Tailnet — same Studio, same listings.
      </p>
    );
  }
  return (
    <div className="settings-tailscale-url">
      <code className="settings-row-code">{data.url}</code>
      <div className="settings-tailscale-actions">
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => onCopy(data.url!)}>
          {copied ? "Copied" : "Copy link"}
        </button>
        <a className="btn btn-sm btn-ghost" href={data.url} target="_blank" rel="noreferrer">
          Open
        </a>
      </div>
      <p className="settings-row-desc">
        On your phone: Tailscale app signed in → Safari/Chrome → paste this link. You are not running a second Studio.
      </p>
    </div>
  );
}

function scrollToSettingsTarget(targetId: string) {
  const target = document.getElementById(targetId);
  if (!target) return false;
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({
    behavior: prefersReducedMotion ? "auto" : "smooth",
    block: "center",
  });
  target.focus({ preventScroll: true });
  target.classList.remove("settings-search-target-pulse");
  if (!prefersReducedMotion) {
    void target.offsetWidth;
    target.classList.add("settings-search-target-pulse");
    target.addEventListener("blur", () => target.classList.remove("settings-search-target-pulse"), { once: true });
  }
  return true;
}

export function SettingsPage({
  section = DEFAULT_SETTINGS_SECTION,
  targetId = null,
  onTargetHandled,
  onOpenSetupGuide,
}: {
  section?: SettingsSectionId;
  targetId?: string | null;
  onTargetHandled?: () => void;
  onOpenSetupGuide?: () => void;
}) {
  useEffect(() => {
    if (!targetId) return;
    const frame = window.requestAnimationFrame(() => {
      if (scrollToSettingsTarget(targetId)) onTargetHandled?.();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [section, targetId, onTargetHandled]);

  return (
    <div className="settings-page" data-settings-page-scroll>
      <div className="settings-page-inner">
        {section === "general" ? <GeneralPanel onOpenSetupGuide={onOpenSetupGuide} /> : null}
        {section === "providers" ? <ProvidersPanel /> : null}
        {section === "integrations" ? <IntegrationsPanel /> : null}
        {section === "connections" ? <ConnectionsPanel /> : null}
      </div>
    </div>
  );
}
