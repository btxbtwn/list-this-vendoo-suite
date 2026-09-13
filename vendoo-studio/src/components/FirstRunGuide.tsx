import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { dismissSetupGuide } from "../onboarding";
import { ConnectChromeButton } from "./ConnectChromeButton";

export const SETUP_GUIDE_STEPS = [
  { id: "welcome", label: "Welcome" },
  { id: "listing-ai", label: "Listing AI" },
  { id: "brave", label: "Brave Search" },
  { id: "chrome", label: "Connect Chrome" },
  { id: "tour", label: "How Studio works" },
  { id: "ready", label: "Create a listing" },
] as const;

type StepId = (typeof SETUP_GUIDE_STEPS)[number]["id"];
type ListingChoice = "chatgpt" | "mimo";

type FirstRunGuideProps = {
  providerConfigured: boolean;
  chromeAvailable: boolean;
  extensionConnected: boolean;
  creating?: boolean;
  onClose: () => void;
  onCreateListing: () => boolean;
};

export function FirstRunGuide({
  providerConfigured,
  chromeAvailable,
  extensionConnected,
  creating,
  onClose,
  onCreateListing,
}: FirstRunGuideProps) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<StepId>("welcome");
  const [listingChoice, setListingChoice] = useState<ListingChoice | null>(null);
  const [mimoKey, setMimoKey] = useState("");
  const [braveKey, setBraveKey] = useState("");
  const [mimoMessage, setMimoMessage] = useState<string | null>(null);
  const [braveMessage, setBraveMessage] = useState<string | null>(null);

  const { data: provider } = useQuery({
    queryKey: ["settings-provider"],
    queryFn: api.settings.provider,
    refetchInterval: 2000,
  });
  const { data: brave } = useQuery({
    queryKey: ["settings-brave"],
    queryFn: api.settings.brave,
  });

  const chatgptSignedIn = Boolean(provider?.chatgpt?.signed_in);
  const chatgptPending = provider?.chatgpt?.pending;
  const mimoConfigured = Boolean(provider?.masked_key);
  const braveConfigured = Boolean(brave?.configured);
  const selectedListing = listingChoice ?? (chatgptSignedIn ? "chatgpt" : mimoConfigured ? "mimo" : "chatgpt");

  const refreshProvider = () => {
    queryClient.invalidateQueries({ queryKey: ["settings-provider"] });
    queryClient.invalidateQueries({ queryKey: ["status"] });
  };

  const chatgptLogin = useMutation({
    mutationFn: () => api.settings.chatgptLogin(),
    onSuccess: refreshProvider,
  });
  const chatgptCancel = useMutation({
    mutationFn: () => api.settings.chatgptCancelLogin(),
    onSuccess: refreshProvider,
  });
  const saveMimo = useMutation({
    mutationFn: (key: string) => api.settings.setProvider(key),
    onSuccess: () => {
      setMimoKey("");
      setMimoMessage("MiMo key saved in Keychain.");
      refreshProvider();
    },
    onError: (err: Error) => setMimoMessage(err.message),
  });
  const saveBrave = useMutation({
    mutationFn: (key: string) => api.settings.setBrave(key),
    onSuccess: () => {
      setBraveKey("");
      setBraveMessage("Brave key saved in Keychain.");
      queryClient.invalidateQueries({ queryKey: ["settings-brave"] });
    },
    onError: (err: Error) => setBraveMessage(err.message),
  });

  const stepIndex = SETUP_GUIDE_STEPS.findIndex((item) => item.id === step);
  const isLast = step === "ready";
  const listingReady = chatgptSignedIn || mimoConfigured || providerConfigured;
  const canCreateListing = providerConfigured;
  const chromeReady = extensionConnected;
  const canAdvance =
    step === "listing-ai" ? listingReady : true;

  useEffect(() => {
    if (!chatgptSignedIn && !mimoConfigured) return;
    queryClient.invalidateQueries({ queryKey: ["status"] });
  }, [chatgptSignedIn, mimoConfigured, queryClient]);

  const finish = () => {
    dismissSetupGuide();
    onClose();
  };

  const goNext = () => {
    if (isLast) {
      finish();
      return;
    }
    setStep(SETUP_GUIDE_STEPS[stepIndex + 1].id);
  };

  const goBack = () => {
    if (stepIndex <= 0) return;
    setStep(SETUP_GUIDE_STEPS[stepIndex - 1].id);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      dismissSetupGuide();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [onClose]);

  const doneFor = (id: StepId) => {
    if (id === "welcome") return stepIndex > 0;
    if (id === "listing-ai") return listingReady;
    if (id === "brave") return braveConfigured || stepIndex > SETUP_GUIDE_STEPS.findIndex((item) => item.id === "brave");
    if (id === "chrome") return chromeReady;
    if (id === "tour") return stepIndex > SETUP_GUIDE_STEPS.findIndex((item) => item.id === "tour");
    return false;
  };

  return (
    <div className="setup-guide" role="presentation">
      <div className="setup-guide-backdrop" />
      <div
        className="setup-guide-popup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="setup-guide-title"
      >
        <ol className="setup-guide-rail" aria-label="Setup steps">
          {SETUP_GUIDE_STEPS.map((item, index) => {
            const current = item.id === step;
            const done = doneFor(item.id);
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={`setup-guide-rail-item${current ? " current" : ""}${done ? " done" : ""}`}
                  onClick={() => setStep(item.id)}
                >
                  <span className="setup-guide-rail-mark" aria-hidden="true">
                    {done && !current ? "✓" : index + 1}
                  </span>
                  <span>{item.label}</span>
                </button>
              </li>
            );
          })}
        </ol>

        <div className="setup-guide-main">
          <div className="setup-guide-body">
            {step === "welcome" ? (
              <>
                <h2 id="setup-guide-title" className="setup-guide-title">Turn photos into Vendoo drafts</h2>
                <p className="setup-guide-copy">
                  List This Studio stays on this Mac. You add product photos, chat writes the listing, then Studio fills a Vendoo draft. It never publishes. You review and send live yourself.
                </p>
                <ul className="setup-guide-points">
                  <li>Choose ChatGPT or a Xiaomi MiMo key so chat can read photos.</li>
                  <li>Optionally add Brave Search for sold-price comps.</li>
                  <li>Connect everyday Chrome once, then create a listing.</li>
                </ul>
              </>
            ) : null}

            {step === "listing-ai" ? (
              <>
                <h2 id="setup-guide-title" className="setup-guide-title">Choose listing AI</h2>
                <p className="setup-guide-copy">
                  Pick one. ChatGPT uses your subscription. MiMo uses an API key stored in macOS Keychain, never in the browser.
                </p>
                <div className="setup-guide-choices" role="radiogroup" aria-label="Listing AI">
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selectedListing === "chatgpt"}
                    className={`setup-guide-choice${selectedListing === "chatgpt" ? " selected" : ""}`}
                    onClick={() => setListingChoice("chatgpt")}
                  >
                    <strong>ChatGPT</strong>
                    <span>Sign in. Best if you already pay for ChatGPT.</span>
                    {chatgptSignedIn ? <em>Signed in{provider?.chatgpt?.email ? ` as ${provider.chatgpt.email}` : ""}</em> : null}
                  </button>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selectedListing === "mimo"}
                    className={`setup-guide-choice${selectedListing === "mimo" ? " selected" : ""}`}
                    onClick={() => setListingChoice("mimo")}
                  >
                    <strong>Xiaomi MiMo</strong>
                    <span>Paste an API key if you are not using ChatGPT.</span>
                    {mimoConfigured ? <em>Key saved · {provider?.masked_key}</em> : null}
                  </button>
                </div>
                {selectedListing === "chatgpt" ? (
                  <div className="setup-guide-task">
                    {chatgptSignedIn ? (
                      <p className="setup-guide-copy">ChatGPT is ready. Continue when you want.</p>
                    ) : chatgptPending ? (
                      <>
                        <p className="setup-guide-copy">
                          Open{" "}
                          <a href={chatgptPending.verification_url} target="_blank" rel="noreferrer">
                            {chatgptPending.verification_url}
                          </a>{" "}
                          and enter <code>{chatgptPending.user_code}</code>
                        </p>
                        <button
                          type="button"
                          className="btn btn-sm btn-outline"
                          onClick={() => chatgptCancel.mutate()}
                          disabled={chatgptCancel.isPending}
                        >
                          Cancel sign-in
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => chatgptLogin.mutate()}
                        disabled={chatgptLogin.isPending}
                      >
                        {chatgptLogin.isPending ? "Starting…" : "Sign in with ChatGPT"}
                      </button>
                    )}
                    {chatgptLogin.isError ? (
                      <p className="setup-guide-error">{(chatgptLogin.error as Error).message}</p>
                    ) : null}
                  </div>
                ) : (
                  <div className="setup-guide-task">
                    <label className="setup-guide-field">
                      <span>MiMo API key</span>
                      <input
                        className="input font-mono"
                        type="password"
                        value={mimoKey}
                        onChange={(e) => setMimoKey(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && mimoKey.trim()) saveMimo.mutate(mimoKey);
                        }}
                        placeholder="sk-..."
                        autoComplete="off"
                        spellCheck={false}
                      />
                    </label>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={!mimoKey.trim() || saveMimo.isPending}
                      onClick={() => saveMimo.mutate(mimoKey)}
                    >
                      {saveMimo.isPending ? "Saving…" : "Save key"}
                    </button>
                    {mimoMessage ? <p className="setup-guide-note">{mimoMessage}</p> : null}
                  </div>
                )}
              </>
            ) : null}

            {step === "brave" ? (
              <>
                <h2 id="setup-guide-title" className="setup-guide-title">Brave Search (optional)</h2>
                <p className="setup-guide-copy">
                  Sold-price comps use ChatGPT web search first. A Brave API key is the fallback when that misses. Skip if you only use ChatGPT, or get a key at{" "}
                  <a href="https://api.search.brave.com" target="_blank" rel="noreferrer">
                    api.search.brave.com
                  </a>
                  . Stored in Keychain.
                </p>
                {braveConfigured ? (
                  <p className="setup-guide-note">Brave is configured · {brave?.masked_key}</p>
                ) : (
                  <div className="setup-guide-task">
                    <label className="setup-guide-field">
                      <span>Brave API key</span>
                      <input
                        className="input font-mono"
                        type="password"
                        value={braveKey}
                        onChange={(e) => setBraveKey(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && braveKey.trim()) saveBrave.mutate(braveKey);
                        }}
                        placeholder="BSA..."
                        autoComplete="off"
                        spellCheck={false}
                      />
                    </label>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={!braveKey.trim() || saveBrave.isPending}
                      onClick={() => saveBrave.mutate(braveKey)}
                    >
                      {saveBrave.isPending ? "Saving…" : "Save key"}
                    </button>
                    {braveMessage ? <p className="setup-guide-note">{braveMessage}</p> : null}
                  </div>
                )}
              </>
            ) : null}

            {step === "chrome" ? (
              <>
                <h2 id="setup-guide-title" className="setup-guide-title">Connect Chrome</h2>
                <p className="setup-guide-copy">
                  Studio opens Vendoo in a background tab in everyday Chrome. Load the listing extension there once, then sign in to Vendoo. After that, Send to Vendoo fills a draft in the background and stops. It never publishes.
                </p>
                {!chromeAvailable ? (
                  <p className="setup-guide-copy">
                    Install{" "}
                    <a href="https://www.google.com/chrome" target="_blank" rel="noreferrer">
                      Google Chrome
                    </a>
                    , then come back.
                  </p>
                ) : chromeReady ? (
                  <p className="setup-guide-note">Extension connected.</p>
                ) : (
                  <div className="setup-guide-task">
                    <ConnectChromeButton className="btn btn-primary btn-sm" />
                    <p className="setup-guide-note">
                      Then in that Chrome window: chrome://extensions → Developer mode → Load unpacked.
                      Zip users pick ~/Library/Application Support/List This Studio/vendoo-extension.
                    </p>
                  </div>
                )}
              </>
            ) : null}

            {step === "tour" ? (
              <>
                <h2 id="setup-guide-title" className="setup-guide-title">How the app is laid out</h2>
                <ul className="setup-guide-points">
                  <li>
                    <strong>Sidebar</strong> — your listings. Compose starts a new one. Settings is ChatGPT, MiMo, Brave, and Chrome.
                  </li>
                  <li>
                    <strong>Photos</strong> — drag product pictures into the tray. Order matters; the first photo is the hero.
                  </li>
                  <li>
                    <strong>Item details</strong> — cost, flaws, and measurements you already know. Chat uses these.
                  </li>
                  <li>
                    <strong>Chat</strong> — ask it to write the listing from the photos. Edit in conversation instead of starting over.
                  </li>
                  <li>
                    <strong>Listing panel</strong> — the draft fields for Vendoo, eBay, Poshmark, Mercari, Depop, and Etsy. Review here before send.
                  </li>
                  <li>
                    <strong>Send to Vendoo</strong> — fills and saves a draft in a background Chrome tab. Publish stays a human click on Vendoo.
                  </li>
                  <li>
                    <strong>Footer</strong> — extension and listing-AI status. If either is off, fix it in Settings before generating.
                  </li>
                </ul>
              </>
            ) : null}

            {step === "ready" ? (
              <>
                <h2 id="setup-guide-title" className="setup-guide-title">Create your first listing</h2>
                <p className="setup-guide-copy">
                  Drop in photos, add any notes, then ask chat to generate. Replay this guide anytime from Settings → General.
                </p>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={creating || !canCreateListing}
                  onClick={() => {
                    if (onCreateListing()) finish();
                  }}
                >
                  Create a listing
                </button>
                {!canCreateListing ? (
                  <p className="setup-guide-note">
                    {listingReady
                      ? "Waiting for Studio to see ChatGPT or MiMo before creating a listing."
                      : "Sign in with ChatGPT or save a MiMo key first."}
                  </p>
                ) : null}
              </>
            ) : null}
          </div>

          <div className="setup-guide-footer">
            <button type="button" className="btn btn-ghost btn-sm" onClick={finish}>
              Skip
            </button>
            <div className="setup-guide-footer-nav">
              <button type="button" className="btn btn-outline btn-sm" onClick={goBack} disabled={stepIndex === 0}>
                Back
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={goNext}
                disabled={!canAdvance}
                title={!canAdvance ? "Choose ChatGPT or MiMo first" : undefined}
              >
                {isLast ? "Done" : (step === "brave" && !braveConfigured) || (step === "chrome" && !chromeReady) ? "Skip for now" : "Continue"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
