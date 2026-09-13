import React, { useEffect, useState } from "react";
import { OpenListingButton } from "./OpenListingButton";

interface PreviewFrame {
  mime: string;
  data: string;
  url?: string;
  step?: string;
  width?: number | null;
  height?: number | null;
}

interface Props {
  jobId: string | null;
  step?: string | null;
  status?: string | null;
  vendooItemId?: string | null;
  vendooUrl?: string | null;
  onCancel?: () => void;
  cancelling?: boolean;
}

export function BrowserPreview({
  jobId,
  step,
  status,
  vendooItemId,
  vendooUrl,
  onCancel,
  cancelling,
}: Props) {
  const [frame, setFrame] = useState<PreviewFrame | null>(null);
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!jobId) {
      setFrame(null);
      setLive(false);
      return;
    }

    const source = new EventSource(`/api/jobs/${jobId}/preview`);
    source.onopen = () => setLive(true);
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as PreviewFrame;
        if (payload?.data) {
          setFrame(payload);
        }
      } catch {
        /* ignore malformed frames */
      }
    };
    source.onerror = () => setLive(false);

    return () => {
      source.close();
      setLive(false);
    };
  }, [jobId]);

  const url = frame?.url || "";
  const label = step || frame?.step || status || "idle";

  return (
    <section className="browser-preview is-open" aria-label="Live listing browser">
      <div className="browser-preview-bar">
        <span className="browser-preview-title">Browser</span>
        <span className="browser-preview-url" title={url}>
          {url || "Waiting for Vendoo…"}
        </span>
        <span className={`browser-preview-live${live && frame ? " on" : live ? " wait" : ""}`}>
          {live && frame ? "Live" : live ? "Connecting" : "Standby"}
        </span>
        <span className="browser-preview-step">{label.replace(/_/g, " ")}</span>
        <div className="browser-preview-actions">
          {jobId && (vendooItemId || vendooUrl) ? (
            <OpenListingButton
              jobId={jobId}
              vendooItemId={vendooItemId}
              vendooUrl={vendooUrl}
              className="browser-preview-open"
            />
          ) : null}
          {onCancel && (
            <button
              type="button"
              className="browser-preview-cancel"
              onClick={onCancel}
              disabled={cancelling}
            >
              {cancelling ? "Cancelling…" : "Cancel"}
            </button>
          )}
        </div>
      </div>
      <div className="browser-preview-stage">
        {frame ? (
          <img
            className="browser-preview-frame"
            src={`data:${frame.mime};base64,${frame.data}`}
            alt="Live Vendoo listing"
          />
        ) : (
          <div className="browser-preview-empty">
            <p>{live ? "Connecting to the Vendoo tab…" : "Starting live view…"}</p>
            <p className="text-xs text-muted">Chrome is filling the listing in a background tab. The tab closes when the draft is saved.</p>
          </div>
        )}
      </div>
    </section>
  );
}
