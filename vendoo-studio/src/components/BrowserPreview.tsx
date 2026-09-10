import React, { useEffect, useState } from "react";

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
}

export function BrowserPreview({ jobId, step, status }: Props) {
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
        <span className={`browser-preview-live${live && frame ? " on" : ""}`}>
          {live && frame ? "Live" : "Standby"}
        </span>
        <span className="browser-preview-step">{label.replace(/_/g, " ")}</span>
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
            <p>Watch the listing fill here. The Vendoo tab stays in the background.</p>
            <p className="text-xs text-muted">Chrome may show a debugging banner on that tab. Stay in Studio.</p>
          </div>
        )}
      </div>
    </section>
  );
}
