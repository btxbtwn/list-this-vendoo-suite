import React, { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ChatMarkdown } from "./ChatMarkdown";

interface Props {
  convId: string;
  queuedMessage?: string | null;
  onQueuedMessageConsumed?: () => void;
}

function isListingJson(text: string): boolean {
  return text.includes('"title"') && (text.includes('"description"') || text.includes('"price"'));
}

function extractJson(text: string): string | null {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced) {
    const inner = fenced[1].trim();
    try {
      JSON.parse(inner);
      return inner;
    } catch {
      /* fall through */
    }
  }
  const stripped = text.trim();
  try {
    JSON.parse(stripped);
    return stripped;
  } catch {
    /* fall through */
  }
  const embedded = stripped.match(/\{[\s\S]*\}/);
  if (!embedded) return null;
  try {
    JSON.parse(embedded[0]);
    return embedded[0];
  } catch {
    return null;
  }
}

function missingFieldsCount(json: string): number | null {
  try {
    const parsed = JSON.parse(json);
    if (parsed && typeof parsed === "object" && Array.isArray(parsed.missing_fields)) {
      return parsed.missing_fields.length;
    }
  } catch {
    /* ignore */
  }
  return null;
}

function prettyJson(json: string): string {
  try {
    return JSON.stringify(JSON.parse(json), null, 2);
  } catch {
    return json;
  }
}

function JsonCollapse({
  json,
  label,
  fieldCount,
}: {
  json: string;
  label: string;
  fieldCount: number;
}) {
  return (
    <details className="json-collapse">
      <summary className="json-collapse-summary">
        <span className="json-badge">{fieldCount} FIELDS</span>
        {label}
        <span className="text-2xs text-muted font-mono" style={{ marginLeft: "auto" }}>RAW JSON</span>
      </summary>
      <div className="json-collapse-body">{json}</div>
    </details>
  );
}

function renderJsonCard(text: string) {
  const json = extractJson(text);
  if (!json) return null;
  const missingCount = missingFieldsCount(json);
  if (missingCount !== null) {
    return (
      <JsonCollapse
        json={prettyJson(json)}
        label="Field values generated"
        fieldCount={missingCount}
      />
    );
  }
  if (isListingJson(json) || isListingJson(text)) {
    return (
      <JsonCollapse
        json={json}
        label="Listing generated"
        fieldCount={(json.match(/"\w+":/g) || []).length}
      />
    );
  }
  return null;
}

function isPhotoAnalysis(text: string): boolean {
  return text.startsWith("Photo analysis") && (text.includes("Brand:") || text.includes("Size:"));
}

function isStreamError(text: string): boolean {
  return text.startsWith("Error:");
}

export function ChatPanel({ convId, queuedMessage, onQueuedMessageConsumed }: Props) {
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [failedAction, setFailedAction] = useState<"generate" | "send" | null>(null);
  const [lastSendText, setLastSendText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortByConvRef = useRef<Record<string, AbortController>>({});
  const convIdRef = useRef(convId);
  const restoreOnAbortRef = useRef(false);
  const queryClient = useQueryClient();
  convIdRef.current = convId;

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
    restoreOnAbortRef.current = false;
    setInput("");
    setStreaming(false);
    setGenerating(false);
    setStreamText("");
    setFailedAction(null);
    setLastSendText("");
  }, [convId]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
  }, [input]);

  const isCurrent = useCallback(() => convIdRef.current === convId, [convId]);

  const streamFromFetch = useCallback(async (url: string) => {
    abortByConvRef.current[convId]?.abort();
    const controller = new AbortController();
    abortByConvRef.current[convId] = controller;
    setStreaming(true);
    setStreamText("");
    setFailedAction(null);
    let assembled = "";
    try {
      const res = await fetch(url, { method: "POST", signal: controller.signal });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        if (isCurrent()) {
          setStreamText(`Error: ${err.detail || err.message || "Failed"}`);
          setFailedAction("generate");
          setStreaming(false);
          setGenerating(false);
        }
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      const reader = res.body?.getReader();
      if (!reader) {
        if (isCurrent()) {
          setStreaming(false);
          setGenerating(false);
        }
        return;
      }
      const decoder = new TextDecoder();
      let buffer = "";
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
            if (isCurrent()) setStreamText(assembled);
          }
        }
      }
      if (isCurrent()) {
        if (!assembled.trim()) {
          assembled = "Error: Listing generation did not finish.";
          setStreamText(assembled);
        }
        if (isStreamError(assembled)) setFailedAction("generate");
      }
    } catch (e: any) {
      if (e?.name === "AbortError") {
        if (isCurrent()) {
          setStreamText("");
          setFailedAction(null);
          setStreaming(false);
          setGenerating(false);
        }
        return;
      }
      if (isCurrent()) {
        assembled = `Error: ${e.message}`;
        setStreamText(assembled);
        setFailedAction("generate");
      }
    }
    const failed = isStreamError(assembled);
    if (isCurrent()) {
      setStreaming(false);
      setGenerating(false);
    }
    await queryClient.invalidateQueries({ queryKey: ["messages", convId] });
    await queryClient.invalidateQueries({ queryKey: ["listing", convId] });
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
    if (isCurrent() && !failed) setStreamText("");
  }, [convId, isCurrent, queryClient]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    await streamFromFetch(`/api/conversations/${convId}/generate`);
  }, [convId, streamFromFetch]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text || streaming) return;
    abortByConvRef.current[convId]?.abort();
    const controller = new AbortController();
    abortByConvRef.current[convId] = controller;
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
        signal: controller.signal,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        if (isCurrent()) {
          setStreamText(`Error: ${err.detail || err.message || "Failed"}`);
          setFailedAction("send");
          setStreaming(false);
        }
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      const reader = res.body?.getReader();
      if (!reader) {
        if (isCurrent()) setStreaming(false);
        return;
      }
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
            if (isCurrent()) setStreamText(assembled);
          }
        }
      }
      if (isStreamError(assembled) && isCurrent()) setFailedAction("send");
      if (isCurrent()) setStreaming(false);
      await queryClient.invalidateQueries({ queryKey: ["messages", convId] });
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (isCurrent() && !isStreamError(assembled)) setStreamText("");
      return;
    } catch (e: any) {
      if (e?.name === "AbortError") {
        if (isCurrent()) {
          setStreamText("");
          setFailedAction(null);
          if (restoreOnAbortRef.current) setInput(text);
          restoreOnAbortRef.current = false;
          setStreaming(false);
        }
        return;
      }
      if (isCurrent()) {
        setStreamText(`Error: ${e.message}`);
        setFailedAction("send");
        setStreaming(false);
      }
      return;
    }
  }, [streaming, convId, isCurrent, queryClient]);

  useEffect(() => {
    if (!queuedMessage || streaming) return;
    const text = queuedMessage;
    onQueuedMessageConsumed?.();
    void sendMessage(text);
  }, [queuedMessage, streaming, sendMessage, onQueuedMessageConsumed]);

  const handleSend = useCallback(() => {
    void sendMessage(input.trim());
  }, [input, sendMessage]);

  const handleCancel = useCallback(() => {
    restoreOnAbortRef.current = true;
    abortByConvRef.current[convId]?.abort();
  }, [convId]);

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
    return Boolean(json && missingFieldsCount(json) === null && isListingJson(json));
  }));
  const streamFailed = isStreamError(streamText);
  const busy = streaming || generating;
  const canRetry = failedAction === "send" ? Boolean(lastSendText) : Boolean(hasPhotos);
  const composerPlaceholder = !hasPhotos
    ? "Upload photos to begin"
    : hasMessages
      ? "Refine the listing..."
      : "Add a note, or generate the listing...";

  function renderMessage(m: any) {
    if (m.role === "user") {
      return (
        <div key={m.id} className="msg msg-user">
          <ChatMarkdown text={m.text} lineBreaks />
        </div>
      );
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

    const jsonCard = renderJsonCard(m.text);
    if (jsonCard) {
      return <React.Fragment key={m.id}>{jsonCard}</React.Fragment>;
    }

    return (
      <div key={m.id} className="msg msg-assistant">
        <ChatMarkdown text={m.text} />
      </div>
    );
  }

  return (
    <div className="chat-panel">
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

        {streamText && !streamFailed && (
          renderJsonCard(streamText) || (
            <div className="msg msg-assistant">
              <ChatMarkdown text={streamText} />
            </div>
          )
        )}

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

      <div className="chat-composer">
        <div className="chat-composer-pill">
          <textarea
            ref={textareaRef}
            className="chat-composer-input"
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={composerPlaceholder}
            disabled={streaming}
          />
          {busy ? (
            <button
              type="button"
              className="chat-send chat-send-cancel"
              onClick={handleCancel}
              aria-label="Cancel"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                <rect x="1" y="1" width="8" height="8" rx="1" />
              </svg>
            </button>
          ) : (
            <button
              type="button"
              className="chat-send"
              onClick={handleSend}
              disabled={!input.trim()}
              aria-label="Send"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M8 12.5V3.5M8 3.5L3.5 8M8 3.5L12.5 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
