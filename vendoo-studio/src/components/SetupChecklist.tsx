import type { ReactNode } from "react";
import { ConnectChromeButton } from "./ConnectChromeButton";

type SetupChecklistProps = {
  providerConfigured: boolean;
  chromeAvailable: boolean;
  extensionConnected: boolean;
  creating?: boolean;
  onOpenSettings: () => void;
  onCreate: () => void;
};

function Step({
  done,
  label,
  children,
}: {
  done: boolean;
  label: string;
  children?: ReactNode;
}) {
  return (
    <li className={`setup-step${done ? " done" : ""}`}>
      <span className="setup-step-mark" aria-hidden="true">
        {done ? "✓" : ""}
      </span>
      <div className="setup-step-body">
        <p className="setup-step-label">{label}</p>
        {children}
      </div>
    </li>
  );
}

export function SetupChecklist({
  providerConfigured,
  chromeAvailable,
  extensionConnected,
  creating,
  onOpenSettings,
  onCreate,
}: SetupChecklistProps) {
  return (
    <div className="empty-state setup-checklist">
      <div className="empty-state-headline">
        Turn product photos
        <br />
        into marketplace-ready drafts.
      </div>
      <div className="empty-state-rule" />
      <ol className="setup-steps">
        <Step done={providerConfigured} label="Sign in with ChatGPT, or add a MiMo API key.">
          {providerConfigured ? (
            <p className="setup-step-note">Ready to generate listings.</p>
          ) : (
            <button type="button" className="btn btn-primary btn-sm" onClick={onOpenSettings}>
              Open Settings
            </button>
          )}
        </Step>
        <Step
          done={extensionConnected}
          label="Connect Chrome, load the listing extension once, and sign in to Vendoo."
        >
          {!chromeAvailable ? (
            <p className="setup-step-note">
              Install{" "}
              <a href="https://www.google.com/chrome" target="_blank" rel="noreferrer">
                Google Chrome
              </a>
              , then come back here.
            </p>
          ) : extensionConnected ? (
            <p className="setup-step-note">Extension connected.</p>
          ) : (
            <>
              <ConnectChromeButton className="btn btn-sm btn-outline" />
              <p className="setup-step-note">
                Then load the extension once in that Chrome window: chrome://extensions → Developer mode → Load unpacked.
              </p>
            </>
          )}
        </Step>
        <Step
          done={false}
          label="Create a listing and drop in photos."
        >
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={creating || !providerConfigured}
            onClick={onCreate}
          >
            Create a listing
          </button>
          {!providerConfigured ? (
            <p className="setup-step-note">Sign in first so chat can generate the listing.</p>
          ) : null}
        </Step>
      </ol>
    </div>
  );
}
