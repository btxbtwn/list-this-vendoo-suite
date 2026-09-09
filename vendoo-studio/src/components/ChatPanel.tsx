import React, { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  convId: string;
}

function isJsonBlock(text: string): boolean {
  return text.includes('"title"') && (text.includes('"description"') || text.includes('"price"'));
}

function extractJson(text: string): string | null {
  const match = text.match(/```json\s*([\s\S]*?)```/);
  if (match) return match[1].trim();
  try { JSON.parse(text); return text; } catch { return null; }
}

function isPhotoAnalysis(text: string): boolean {
  return text.startsWith("Photo analysis") && (text.includes("Brand:") || text.includes("Size:"));
}

function isStreamError(text: string): boolean {
  return text.startsWith("Error:");
}

export function ChatPanel({ convId }: Props) {
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [failedAction, setFailedAction] = useState<"generate" | "send" | null>(null);
  const [lastSendText, setLastSendText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: messages, isLoading } = useQuery({
    queryKey: ["messages", convId],
    queryFn: () => api.conversations.messages(convId),
  });

  const { data: photos } = useQuery({
    queryKey: ["photos", convId],
    queryFn: () => api.conversations.photos(convId),
  });

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages, streamText]);

  useEffect(() => {
    setInput("");
    setStreaming(false);
    setGenerating(false);
    setStreamText("");
    setFailedAction(null);
    setLastSendText("");
  }, [convId]);

  const streamFromFetch = useCallback(async (url: string) => {
    setStreaming(true);
    setStreamText("");
    setFailedAction(null);
    try {
      const res = await fetch(url, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setStreamText(`Error: ${err.detail || err.message || "Failed"}`);
        setFailedAction("generate");
        setStreaming(false);
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      const reader = res.body?.getReader();
      if (!reader) { setStreaming(false); return; }
      const decoder = new TextDecoder();
      let buffer = "";
      let assembled = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const chunk = line.slice(6);
            if (chunk === "[DONE]") continue;
            assembled += chunk;
            setStreamText(assembled);
          }
        }
      }
      if (isStreamError(assembled)) setFailedAction("generate");
    } catch (e: any) {
      setStreamText(`Error: ${e.message}`);
      setFailedAction("generate");
    }
    setStreaming(false);
    setGenerating(false);
    await queryClient.invalidateQueries({ queryKey: ["messages", convId] });
    await queryClient.invalidateQueries({ queryKey: ["listing", convId] });
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
  }, [convId, queryClient]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    await streamFromFetch(`/api/conversations/${convId}/generate`);
  }, [convId, streamFromFetch]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text || streaming) return;
    setInput("");
    setLastSendText(text);
    setStreaming(true);
    setStreamText("");
    setFailedAction(null);
    try {
      const res = await fetch(`/api/conversations/${convId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setStreamText(`Error: ${err.detail || err.message || "Failed"}`);
        setFailedAction("send");
        setStreaming(false);
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      const reader = res.body?.getReader();
      if (!reader) { setStreaming(false); return; }
      const decoder = new TextDecoder();
      let buffer = "";
      let assembled = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const chunk = line.slice(6);
            if (chunk === "[DONE]") continue;
            assembled += chunk;
            setStreamText(assembled);
          }
        }
      }
      if (isStreamError(assembled)) setFailedAction("send");
    } catch (e: any) {
      setStreamText(`Error: ${e.message}`);
      setFailedAction("send");
    }
    setStreaming(false);
    queryClient.invalidateQueries({ queryKey: ["messages", convId] });
    queryClient.invalidateQueries({ queryKey: ["listing", convId] });
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
  }, [streaming, convId, queryClient]);

  const handleSend = useCallback(() => {
    void sendMessage(input.trim());
  }, [input, sendMessage]);

  const handleRetry = useCallback(() => {
    if (failedAction === "send" && lastSendText) {
      void sendMessage(lastSendText);
      return;
    }
    void handleGenerate();
  }, [failedAction, lastSendText, sendMessage, handleGenerate]);

  const hasPhotos = (photos && (photos as any[]).length > 0);
  const hasMessages = messages && (messages as any[]).length > 0;
  const hasListingJson = Boolean(messages?.some((m: any) => {
    const json = extractJson(m.text);
    return Boolean(json && isJsonBlock(m.text));
  }));
  const streamFailed = isStreamError(streamText);
  const busy = streaming || generating;
  const canRetry = failedAction === "send" ? Boolean(lastSendText) : Boolean(hasPhotos);

  function renderMessage(m: any) {
    if (m.role === "user") {
      return <div key={m.id} className="msg msg-user">{m.text}</div>;
    }

    if (m.role === "system" && isPhotoAnalysis(m.text)) {
      const lines = m.text.split("\n").filter((l: string) => l.trim());
      const body = lines.slice(1).join("\n");
      return (
        <div key={m.id} className="evidence-card">
          <div className="evidence-header">EVIDENCE</div>
          <div className="evidence-body">{body || m.text}</div>
        </div>
      );
    }

    if (m.role === "system") {
      return (
        <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-border-bright)", flexShrink: 0 }} />
          <span className="msg-system" style={{ padding: 0, borderLeft: "none", maxWidth: "none" }}>{m.text}</span>
        </div>
      );
    }

    const json = extractJson(m.text);
    if (json && isJsonBlock(m.text)) {
      const fieldCount = (json.match(/"\w+":/g) || []).length;
      return (
        <details key={m.id} className="json-collapse">
          <summary className="json-collapse-summary">
            <span className="json-badge">{fieldCount} FIELDS</span>
            Listing generated
            <span className="text-2xs text-muted font-mono" style={{ marginLeft: "auto" }}>RAW JSON</span>
          </summary>
          <div className="json-collapse-body">{json}</div>
        </details>
      );
    }

    return <div key={m.id} className="msg msg-assistant">{m.text}</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      <div ref={scrollRef} className="chat-scroll">
        {isLoading && !hasMessages && (
          <div className="empty-state" style={{ padding: "16px 0" }}><p className="text-xs text-muted">Loading...</p></div>
        )}

        {!isLoading && !hasMessages && (
          <div className="empty-state" style={{ padding: "32px 16px" }}>
            <h3 style={{ fontFamily: "var(--font-serif)", fontStyle: "italic", fontSize: 20, marginBottom: 4, lineHeight: 1.2 }}>Generate a Listing</h3>
            {hasPhotos ? (
              <>
                <p className="text-xs font-mono text-muted">{(photos as any[]).length} photo{(photos as any[]).length !== 1 ? "s" : ""} uploaded</p>
                <button className="btn btn-primary" onClick={handleGenerate} disabled={generating || streaming} style={{ marginTop: 12, padding: "9px 22px" }}>
                  {generating ? "Analyzing..." : "Generate Listing"}
                </button>
              </>
            ) : (
              <p className="text-xs font-mono text-muted">Upload photos to begin</p>
            )}
          </div>
        )}

        {messages?.map(renderMessage)}

        {streamText && !streamFailed && <div className="msg msg-assistant">{streamText}</div>}

        {streamFailed && (
          <div className="chat-error" role="alert">
            <div className="chat-error-text">{streamText}</div>
            <button
              className="btn btn-primary btn-sm"
              onClick={handleRetry}
              disabled={busy || !canRetry}
            >
              {busy ? "Retrying..." : "Retry"}
            </button>
          </div>
        )}

        {hasMessages && !hasListingJson && !streamFailed && !busy && hasPhotos && (
          <div className="chat-error">
            <div className="chat-error-text">Listing generation did not finish.</div>
            <button className="btn btn-primary btn-sm" onClick={handleGenerate}>
              Retry
            </button>
          </div>
        )}

        {(streaming || generating) && !streamText && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 8 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-cobalt)", flexShrink: 0 }} />
            <span className="text-xs font-mono text-muted">{generating ? "ANALYZING PHOTOS…" : "MIMO IS THINKING…"}</span>
          </div>
        )}
      </div>

      {hasMessages && (
        <div className="chat-composer">
          <div className="flex-row" style={{ width: "100%" }}>
            <input
              className="input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
              placeholder="Refine the listing..."
              disabled={streaming}
              style={{ flex: 1 }}
            />
            <button className="btn btn-primary" onClick={handleSend} disabled={streaming || !input.trim()}>
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
