import React, { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  convId: string;
}

export function ChatPanel({ convId }: Props) {
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [streamText, setStreamText] = useState("");
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

  const streamFromFetch = useCallback(async (url: string) => {
    setStreaming(true);
    setStreamText("");

    try {
      const res = await fetch(url, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setStreamText(`Error: ${err.detail || err.message || "Failed"}`);
        setStreaming(false);
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) { setStreaming(false); return; }

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
            setStreamText((prev) => prev + chunk);
          }
        }
      }
    } catch (e: any) {
      setStreamText(`Error: ${e.message}`);
    }
    setStreaming(false);
    setGenerating(false);
    await queryClient.invalidateQueries({ queryKey: ["messages", convId] });
    await queryClient.invalidateQueries({ queryKey: ["listing", convId] });
  }, [convId, queryClient]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    await streamFromFetch(`/api/conversations/${convId}/generate`);
  }, [convId, streamFromFetch]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setStreaming(true);
    setStreamText("");

    try {
      const res = await fetch(`/api/conversations/${convId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setStreamText(`Error: ${err.detail || err.message || "Failed"}`);
        setStreaming(false);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) { setStreaming(false); return; }

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
            setStreamText((prev) => prev + chunk);
          }
        }
      }
    } catch (e: any) {
      setStreamText(`Error: ${e.message}`);
    }
    setStreaming(false);
    queryClient.invalidateQueries({ queryKey: ["messages", convId] });
    queryClient.invalidateQueries({ queryKey: ["listing", convId] });
  }, [input, streaming, convId, queryClient]);

  const hasPhotos = (photos && (photos as any[]).length > 0);
  const hasMessages = messages && (messages as any[]).length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflow: "auto",
          padding: 16,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {isLoading && !hasMessages && (
          <div className="empty-state"><p>Loading...</p></div>
        )}

        {!isLoading && !hasMessages && (
          <div className="empty-state">
            <h3 style={{ marginBottom: 8 }}>Generate Listing</h3>
            {hasPhotos ? (
              <>
                <p>{photos ? (photos as any[]).length : 0} photos uploaded. Ready to generate.</p>
                <button
                  className="btn btn-primary"
                  onClick={handleGenerate}
                  disabled={generating || streaming}
                  style={{ marginTop: 16, fontSize: 14, padding: "10px 24px" }}
                >
                  {generating ? "Analyzing photos..." : "Generate Listing"}
                </button>
              </>
            ) : (
              <p style={{ color: "var(--color-text-muted)" }}>
                Upload product photos using the Add Photos button above, then click Generate Listing.
              </p>
            )}
          </div>
        )}

        {messages?.map((m: any) => (
          <div
            key={m.id}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "80%",
              padding: "8px 14px",
              borderRadius: "var(--radius-md)",
              background: m.role === "user" ? "var(--color-primary)" : "var(--color-surface)",
              color: m.role === "user" ? "white" : "var(--color-text)",
              border: m.role === "user" ? "none" : "1px solid var(--color-border)",
              fontSize: 13,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
            }}
          >
            {m.text}
          </div>
        ))}
        {streamText && (
          <div
            style={{
              alignSelf: "flex-start",
              maxWidth: "80%",
              padding: "8px 14px",
              borderRadius: "var(--radius-md)",
              background: "var(--color-surface)",
              color: "var(--color-text)",
              border: "1px solid var(--color-border)",
              fontSize: 13,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
            }}
          >
            {streamText}
          </div>
        )}
        {(streaming || generating) && !streamText && (
          <div style={{ alignSelf: "flex-start", padding: 8, color: "var(--color-text-muted)" }}>
            {generating ? "Analyzing photos and generating listing..." : "MiMo is thinking..."}
          </div>
        )}
      </div>

      {hasMessages && (
        <div style={{ padding: 12, borderTop: "1px solid var(--color-border)" }}>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
              placeholder="Refine the listing..."
              disabled={streaming}
            />
            <button className="btn btn-primary" onClick={handleSend} disabled={streaming || !input.trim()}>
              {streaming ? "..." : "Send"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
