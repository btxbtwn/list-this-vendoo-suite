import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function ExtensionLoadPath({
  compact = false,
  hideHint = false,
}: {
  compact?: boolean;
  hideHint?: boolean;
}) {
  const { data } = useQuery({
    queryKey: ["desktop-chrome"],
    queryFn: api.desktop.chrome,
  });
  const path = data?.extension_dir || "";
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!path) return;
    await navigator.clipboard.writeText(path);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div className={`extension-load-path${compact ? " compact" : ""}`}>
      {hideHint ? null : (
        <p className={compact ? "setup-step-note" : "setup-guide-note"}>
          In Chrome open chrome://extensions, turn on Developer mode, and click Load unpacked. Choose this folder:
        </p>
      )}
      {path ? (
        <div className="extension-load-path-row">
          <code className="extension-load-path-code">{path}</code>
          <button type="button" className="btn btn-sm btn-outline" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy path"}
          </button>
        </div>
      ) : (
        <p className={compact ? "setup-step-note" : "setup-guide-note"}>Looking up the extension folder…</p>
      )}
    </div>
  );
}
