import React, { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ChatMarkdown } from "./ChatMarkdown";
import { SoldCompsCard } from "./SoldCompsCard";
import { parseThinkingTodos } from "./thinkingTodos";

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
  const embeddedArray = stripped.match(/\[[\s\S]*\]/);
  if (embeddedArray) {
    try {
      const parsed = JSON.parse(embeddedArray[0]);
      if (Array.isArray(parsed) && parsed[0]?.op) return embeddedArray[0];
    } catch {
      /* fall through */
    }
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

const PATCH_LABELS: Record<string, string> = {
  category_path: "Category",
  department: "Department",
  styleTags: "Style tags",
  primaryStoreCategory: "Store category",
  secondaryStoreCategory: "Secondary store category",
  primaryColor: "Primary color",
  secondaryColor: "Secondary color",
};

function humanKey(token: string): string {
  return token
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/-/g, " ")
    .trim()
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function pathLabel(path: string): string {
  const parts = (path || "").replace(/^\//, "").split("/").filter((part) => part && part !== "-" && !/^\d+$/.test(part));
  if (!parts.length) return "Field";
  let prefix = "";
  if (parts[0].endsWith("_specifics")) {
    const market = parts[0].slice(0, -"_specifics".length);
    prefix = market === "ebay" ? "eBay" : market.charAt(0).toUpperCase() + market.slice(1);
    parts.shift();
  }
  const key = parts[parts.length - 1] || "";
  const label = PATCH_LABELS[key] || humanKey(key);
  return prefix ? `${prefix} ${label}` : label;
}

function displayValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (value == null) return "";
  return String(value);
}

function summarizeJsonPatch(ops: { op?: string; path?: string; value?: unknown }[]): string {
  const lines = ops.flatMap((op) => {
    const label = pathLabel(op.path || "");
    if (op.op === "remove") return [`Removed ${label}`];
    if (op.op === "replace" || op.op === "add") return [`${label}: ${displayValue(op.value)}`];
    return [];
  });
  if (!lines.length) return "Saved those changes to the listing.";
  if (lines.length === 1) return `Updated the listing — ${lines[0]}.`;
  return `Updated the listing:\n${lines.map((line) => `- ${line}`).join("\n")}`;
}

const MARKETPLACE_DISPLAY: Record<string, string> = {
  general: "Vendoo",
  ebay: "eBay",
  etsy: "Etsy",
  poshmark: "Poshmark",
  mercari: "Mercari",
  depop: "Depop",
  facebook: "Facebook",
  shopify: "Shopify",
};

function summarizeMissingFields(
  rows: { marketplace?: string; field?: string; value?: unknown }[],
): string {
  const lines = rows.flatMap((row) => {
    const field = String(row.field || "").trim();
    const value = displayValue(row.value).trim();
    if (!field || !value) return [];
    const market = String(row.marketplace || "general").trim().toLowerCase() || "general";
    const label = MARKETPLACE_DISPLAY[market] || humanKey(market);
    return [`${label} / ${field}: ${value}`];
  });
  if (!lines.length) return "Saved field values to the listing JSON.";
  if (lines.length === 1) return `Saved to the listing JSON — ${lines[0]}. Fill on Vendoo when ready.`;
  return `Saved to the listing JSON:\n${lines.map((line) => `- ${line}`).join("\n")}`;
}

function stripJsonPayloads(text: string): string {
  let visible = text.replace(/```(?:json)?\s*[\s\S]*?(```|$)/gi, "\n");
  visible = visible.replace(/\n\s*\[[\s\S]*$/, "\n").replace(/\n\s*\{[\s\S]*$/, "\n").trim();
  if (/^[\[{]/.test(visible)) return "";
  return visible;
}

function looksLikeJsonStream(text: string): boolean {
  const trimmed = text.trim();
  return trimmed.startsWith("[") || trimmed.startsWith("{") || /```json/i.test(text);
}

function assistantDisplayText(text: string): string {
  const prose = stripJsonPayloads(text);
  if (prose) return prose;

  const json = extractJson(text);
  if (!json) return looksLikeJsonStream(text) ? "" : text.trim();
  try {
    const parsed = JSON.parse(json);
    if (Array.isArray(parsed) && parsed[0]?.op) return summarizeJsonPatch(parsed);
    if (parsed && typeof parsed === "object" && Array.isArray(parsed.missing_fields)) {
      return summarizeMissingFields(parsed.missing_fields);
    }
    if (parsed && typeof parsed === "object" && typeof parsed.message === "string" && parsed.message.trim()) {
      return parsed.message.trim();
    }
    if (isListingJson(json) || isListingJson(text)) {
      return "Listing saved. Open Fields to see what is still missing in Studio and on Vendoo.";
    }
  } catch {
    /* ignore */
  }
  return looksLikeJsonStream(text) ? "" : text.trim();
}

function isPhotoAnalysis(text: string): boolean {
  return (
    text.startsWith("Photo analysis") &&
    (/-\s*brand:/i.test(text) || /-\s*size:/i.test(text) || /-\s*color:/i.test(text))
  );
}

function isCompResearch(text: string): boolean {
  return text.startsWith("Sold comps:");
}

function isStreamError(text: string): boolean {
  return text.startsWith("Error:");
}

function detailFromResponseBody(body: unknown): string {
  if (!body || typeof body !== "object") return "";
  const detail = (body as { detail?: unknown; message?: unknown }).detail
    ?? (body as { message?: unknown }).message;
  if (typeof detail === "string") return detail.trim();
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) return String((item as { msg: unknown }).msg);
        return "";
      })
      .filter(Boolean)
      .join("; ");
  }
  return detail != null ? String(detail) : "";
}

/** Turn opaque browser/HTTP failures into actionable chat errors. */
function formatClientStreamError(
  source: unknown,
  opts: {
    action: "generate" | "send";
    httpStatus?: number;
    lastStatus?: string;
    probeActive?: boolean;
    probeStep?: string;
  },
): string {
  const raw = (() => {
    if (typeof source === "string") return source.trim();
    if (source instanceof Error) return source.message.trim();
    if (source && typeof source === "object") return detailFromResponseBody(source);
    return "";
  })().replace(/^Error:\s*/i, "");

  const actionLabel = opts.action === "send" ? "Chat request" : "Listing generation";
  const stage = (opts.lastStatus || "").trim();
  const stageBit = stage ? ` during “${stage}”` : "";
  const stageImpliesProbe = /identifying category|discovering.*(field|schema)|field discovery/i.test(stage);
  const probeActive = Boolean(opts.probeActive || stageImpliesProbe);
  const probeBit = probeActive
    ? ` Chrome is still on field discovery${opts.probeStep ? ` (${opts.probeStep})` : ""}.`
    : "";

  const network = /^(load failed|failed to fetch|networkerror when attempting to fetch resource|network request failed|the internet connection appears to be offline\.?)$/i.test(raw)
    || /failed to fetch|networkerror|load failed/i.test(raw);

  if (network) {
    return (
      `Error: ${actionLabel} connection dropped${stageBit}.${probeBit} `
      + (probeActive
        ? "Retry reconnects to the same generate — only Cancel discovery if Chrome is stuck."
        : "Retry to resume. If this keeps happening on mobile, use a stronger connection or desktop Studio.")
    );
  }

  if (opts.httpStatus) {
    const detail = raw || "Request failed";
    return `Error: ${actionLabel} failed (HTTP ${opts.httpStatus})${stageBit}: ${detail}.${probeBit}`.trim();
  }

  if (!raw) {
    return `Error: ${actionLabel} failed${stageBit}.${probeBit} Retry, or cancel discovery if Chrome is stuck.`.trim();
  }

  if (/^error:/i.test(raw)) return raw.startsWith("Error:") ? raw : `Error: ${raw}`;
  return `Error: ${raw}`;
}

type SseParts = { content: string; thinking: string; status: string };
type SseParseState = { eventType: string; parts: SseParts };

const SSE_FETCH: RequestInit = {
  method: "POST",
  headers: { Accept: "text/event-stream" },
  cache: "no-store",
};

function applySseLine(
  raw: string,
  state: SseParseState,
  onEvent: (event: string, parts: SseParts) => void,
): boolean {
  const line = raw.replace(/\r$/, "");
  if (!line) {
    state.eventType = "message";
    return false;
  }
  if (line.startsWith(":")) return false;
  if (line.startsWith("event:")) {
    state.eventType = line.slice(6).trim() || "message";
    return false;
  }
  if (!line.startsWith("data:")) return false;
  const chunk = line.startsWith("data: ") ? line.slice(6) : line.slice(5);
  if (chunk === "[DONE]") {
    state.eventType = "message";
    return true;
  }
  if (state.eventType === "thinking") state.parts.thinking += chunk;
  else if (state.eventType === "status") state.parts.status = chunk;
  else state.parts.content += chunk;
  onEvent(state.eventType, state.parts);
  return false;
}

function consumeSseText(
  text: string,
  onEvent: (event: string, parts: SseParts) => void,
): { parts: SseParts; sawDone: boolean } {
  const state: SseParseState = { eventType: "message", parts: { content: "", thinking: "", status: "" } };
  let sawDone = false;
  for (const line of text.split("\n")) {
    if (applySseLine(line, state, onEvent)) sawDone = true;
  }
  return { parts: state.parts, sawDone };
}

async function consumeSse(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: string, parts: SseParts) => void,
): Promise<{ parts: SseParts; sawDone: boolean }> {
  const decoder = new TextDecoder();
  let buffer = "";
  let sawDone = false;
  const state: SseParseState = { eventType: "message", parts: { content: "", thinking: "", status: "" } };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const raw of lines) {
      if (applySseLine(raw, state, onEvent)) sawDone = true;
    }
  }
  if (buffer && applySseLine(buffer, state, onEvent)) sawDone = true;
  return { parts: state.parts, sawDone };
}

async function consumeResponseSse(
  res: Response,
  onEvent: (event: string, parts: SseParts) => void,
): Promise<{ parts: SseParts; sawDone: boolean }> {
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    reader = res.body?.getReader();
  } catch {
    reader = undefined;
  }
  if (reader) return consumeSse(reader, onEvent);
  return consumeSseText(await res.text(), onEvent);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isResumableGenerateFailure(text: string): boolean {
  return /connection dropped|did not finish|reconnecting/i.test(text);
}

type LiveStream = {
  controller: AbortController | null;
  streaming: boolean;
  generating: boolean;
  streamText: string;
  streamThinking: string;
  streamStatus: string;
  thinkingStarted: boolean;
  failedAction: "generate" | "send" | null;
  lastSendText: string;
  userCancelled: boolean;
  restoreInputOnAbort: boolean;
  listeners: Set<() => void>;
};

const liveStreams: Record<string, LiveStream> = {};

function emptyLive(): Omit<LiveStream, "listeners"> {
  return {
    controller: null,
    streaming: false,
    generating: false,
    streamText: "",
    streamThinking: "",
    streamStatus: "",
    thinkingStarted: false,
    failedAction: null,
    lastSendText: "",
    userCancelled: false,
    restoreInputOnAbort: false,
  };
}

function getLive(convId: string): LiveStream {
  if (!liveStreams[convId]) liveStreams[convId] = { ...emptyLive(), listeners: new Set() };
  return liveStreams[convId];
}

function emitLive(convId: string) {
  getLive(convId).listeners.forEach((listener) => listener());
}

export function resetChatLive(convId: string) {
  const live = liveStreams[convId];
  if (!live) return;
  const controller = live.controller;
  live.restoreInputOnAbort = false;
  controller?.abort();
  Object.assign(live, emptyLive());
  emitLive(convId);
}

function patchLive(convId: string, patch: Partial<Omit<LiveStream, "listeners">>) {
  Object.assign(getLive(convId), patch);
  emitLive(convId);
}

function applySseToLive(convId: string, event: string, parts: SseParts) {
  const live = getLive(convId);
  if (event === "thinking" || event === "status") live.thinkingStarted = true;
  if (event === "thinking") live.streamThinking = parts.thinking;
  if (event === "status") live.streamStatus = parts.status;
  if (event !== "thinking" && event !== "status" && event !== "listing_updated") {
    live.streamText = parts.content;
  }
  emitLive(convId);
}

async function refreshListingQueries(queryClient: QueryClient, convId: string) {
  await queryClient.invalidateQueries({ queryKey: ["messages", convId] });
  await queryClient.invalidateQueries({ queryKey: ["listing", convId] });
  await queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
  queryClient.invalidateQueries({ queryKey: ["conversations"] });
  queryClient.invalidateQueries({ queryKey: ["fill-log"] });
}

export function ChatPanel({ convId, queuedMessage, onQueuedMessageConsumed }: Props) {
  const live = getLive(convId);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(live.streaming);
  const [generating, setGenerating] = useState(live.generating);
  const [streamText, setStreamText] = useState(live.streamText);
  const [streamThinking, setStreamThinking] = useState(live.streamThinking);
  const [streamStatus, setStreamStatus] = useState(live.streamStatus);
  const [thinkingStarted, setThinkingStarted] = useState(live.thinkingStarted);
  const [failedAction, setFailedAction] = useState<"generate" | "send" | null>(live.failedAction);
  const [lastSendText, setLastSendText] = useState(live.lastSendText);
  const scrollRef = useRef<HTMLDivElement>(null);
  const thinkingBodyRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const queryClient = useQueryClient();

  const { data: messages, isLoading } = useQuery({
    queryKey: ["messages", convId],
    queryFn: () => api.conversations.messages(convId),
    refetchInterval: streaming || generating ? 2000 : false,
  });

  const { data: photos } = useQuery({
    queryKey: ["photos", convId],
    queryFn: () => api.conversations.photos(convId),
  });

  const { data: listing } = useQuery({
    queryKey: ["listing", convId],
    queryFn: () => api.listings.get(convId),
    refetchInterval: streaming || generating ? 2000 : false,
  });

  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.jobs.list(),
    refetchInterval: streaming || generating ? 2000 : 5000,
  });

  const activeProbe = (jobs || []).find(
    (j: any) =>
      j.conversation_id === convId
      && j.mode === "schema_probe"
      && ["queued", "awaiting_extension", "dispatched"].includes(String(j.status || "")),
  );

  useEffect(() => {
    const sync = () => {
      const next = getLive(convId);
      setStreaming(next.streaming);
      setGenerating(next.generating);
      setStreamText(next.streamText);
      setStreamThinking(next.streamThinking);
      setStreamStatus(next.streamStatus);
      setThinkingStarted(next.thinkingStarted);
      setFailedAction(next.failedAction);
      setLastSendText(next.lastSendText);
    };
    setInput("");
    sync();
    getLive(convId).listeners.add(sync);
    return () => {
      getLive(convId).listeners.delete(sync);
    };
  }, [convId]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages, streamText, streamThinking]);

  useEffect(() => {
    const el = thinkingBodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [streamThinking]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
  }, [input]);

  const streamFromFetch = useCallback(async (url: string, initialStatus = "") => {
    const liveState = getLive(convId);
    liveState.controller?.abort();
    const controller = new AbortController();
    patchLive(convId, {
      controller,
      streaming: true,
      generating: url.endsWith("/generate") ? true : liveState.generating,
      streamText: "",
      streamThinking: "",
      streamStatus: initialStatus,
      thinkingStarted: Boolean(initialStatus),
      failedAction: null,
      userCancelled: false,
    });
    const stillMine = () => getLive(convId).controller === controller;
    const errorContext = () => {
      const live = getLive(convId);
      const probe = (queryClient.getQueryData<any[]>(["jobs"]) || []).find(
        (j: any) =>
          j.conversation_id === convId
          && j.mode === "schema_probe"
          && ["queued", "awaiting_extension", "dispatched"].includes(String(j.status || "")),
      );
      return {
        action: "generate" as const,
        lastStatus: live.streamStatus || initialStatus,
        probeActive: Boolean(probe),
        probeStep: String(probe?.current_step || ""),
      };
    };
    const isNetworkFailure = (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err || "");
      return /^(load failed|failed to fetch|networkerror when attempting to fetch resource|network request failed|the internet connection appears to be offline\.?)$/i.test(msg.trim())
        || /failed to fetch|networkerror|load failed/i.test(msg);
    };
    const readStream = async (): Promise<{ content: string; sawDone: boolean }> => {
      const res = await fetch(url, { ...SSE_FETCH, signal: controller.signal });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        throw Object.assign(new Error(detailFromResponseBody(err) || "Request failed"), {
          httpStatus: res.status,
          body: err,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      const { parts, sawDone } = await consumeResponseSse(
        res,
        (event, nextParts) => applySseToLive(convId, event, nextParts),
      );
      return { content: parts.content, sawDone };
    };
    const canResumeGenerate = url.includes("/generate");
    const maxAttempts = canResumeGenerate ? 20 : 1;
    let assembled = "";
    let sawDone = false;
    let attempt = 0;
    try {
      while (stillMine()) {
        attempt += 1;
        try {
          const result = await readStream();
          assembled = result.content;
          sawDone = result.sawDone;
          if (
            canResumeGenerate
            && !sawDone
            && stillMine()
            && attempt < maxAttempts
          ) {
            const priorStatus = getLive(convId).streamStatus || initialStatus;
            patchLive(convId, {
              streamStatus: priorStatus
                ? `${priorStatus.replace(/\s*·\s*reconnecting….*$/i, "")} · reconnecting…`
                : "Reconnecting to listing generation…",
              thinkingStarted: true,
              failedAction: null,
              streamText: isStreamError(assembled) ? "" : assembled,
            });
            queryClient.invalidateQueries({ queryKey: ["jobs"] });
            await sleep(Math.min(1500 * attempt, 5000));
            continue;
          }
          break;
        } catch (first: any) {
          // Generation continues server-side; keep reattaching through mobile drops mid-discovery.
          if (
            canResumeGenerate
            && stillMine()
            && first?.name !== "AbortError"
            && isNetworkFailure(first)
            && attempt < maxAttempts
          ) {
            const priorStatus = getLive(convId).streamStatus || initialStatus;
            patchLive(convId, {
              streamStatus: priorStatus
                ? `${priorStatus.replace(/\s*·\s*reconnecting….*$/i, "")} · reconnecting…`
                : "Reconnecting to listing generation…",
              thinkingStarted: true,
              failedAction: null,
              streamText: "",
            });
            queryClient.invalidateQueries({ queryKey: ["jobs"] });
            await sleep(Math.min(1500 * attempt, 5000));
            continue;
          }
          throw first;
        }
      }
      if (stillMine()) {
        if (!assembled.trim() && !sawDone) {
          assembled = formatClientStreamError("Listing generation did not finish.", errorContext());
          patchLive(convId, { streamText: assembled });
        }
        if (isStreamError(assembled)) patchLive(convId, { failedAction: "generate" });
      }
    } catch (e: any) {
      if (e?.name === "AbortError") {
        if (!stillMine()) return;
        if (getLive(convId).userCancelled) {
          const restoreText = getLive(convId).lastSendText;
          const restore = getLive(convId).restoreInputOnAbort;
          patchLive(convId, {
            streamText: "",
            streamThinking: "",
            streamStatus: "",
            thinkingStarted: false,
            failedAction: null,
            streaming: false,
            generating: false,
            controller: null,
            userCancelled: false,
            restoreInputOnAbort: false,
          });
          if (restore && restoreText) setInput(restoreText);
          return;
        }
        patchLive(convId, { controller: null });
        return;
      }
      if (stillMine()) {
        assembled = formatClientStreamError(e?.body || e, {
          ...errorContext(),
          httpStatus: e?.httpStatus,
        });
        patchLive(convId, {
          streamText: assembled,
          streamThinking: "",
          streamStatus: "",
          failedAction: "generate",
        });
      }
    }
    const failed = isStreamError(assembled);
    if (stillMine()) {
      patchLive(convId, { streaming: false, generating: false, controller: null });
    }
    await refreshListingQueries(queryClient, convId);
    if (stillMine() && !failed) {
      patchLive(convId, {
        streamText: "",
        streamThinking: "",
        streamStatus: "",
        thinkingStarted: false,
      });
    }
  }, [convId, queryClient]);

  const handleGenerate = useCallback(async () => {
    patchLive(convId, {
      generating: true,
      streamStatus: "Analyzing photos…",
      thinkingStarted: true,
      userCancelled: false,
    });
    await streamFromFetch(`/api/conversations/${convId}/generate`, "Analyzing photos…");
  }, [convId, streamFromFetch]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text || getLive(convId).streaming) return;
    const liveState = getLive(convId);
    liveState.controller?.abort();
    const controller = new AbortController();
    patchLive(convId, {
      controller,
      lastSendText: text,
      streaming: true,
      generating: false,
      streamText: "",
      streamThinking: "",
      streamStatus: "",
      thinkingStarted: true,
      failedAction: null,
      userCancelled: false,
      restoreInputOnAbort: false,
    });
    setInput("");
    const stillMine = () => getLive(convId).controller === controller;
    const errorContext = () => ({
      action: "send" as const,
      lastStatus: getLive(convId).streamStatus || "",
    });
    try {
      const res = await fetch(`/api/conversations/${convId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ text }),
        cache: "no-store",
        signal: controller.signal,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        if (stillMine()) {
          patchLive(convId, {
            streamText: formatClientStreamError(err, { ...errorContext(), httpStatus: res.status }),
            streamThinking: "",
            streamStatus: "",
            failedAction: "send",
            streaming: false,
            controller: null,
          });
        }
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      const { parts } = await consumeResponseSse(res, (event, nextParts) => applySseToLive(convId, event, nextParts));
      const assembled = parts.content;
      if (stillMine() && isStreamError(assembled)) patchLive(convId, { failedAction: "send" });
      if (stillMine()) patchLive(convId, { streaming: false, controller: null });
      await refreshListingQueries(queryClient, convId);
      if (stillMine() && !isStreamError(assembled)) {
        patchLive(convId, {
          streamText: "",
          streamThinking: "",
          streamStatus: "",
          thinkingStarted: false,
        });
      }
      return;
    } catch (e: any) {
      if (e?.name === "AbortError") {
        if (!stillMine()) return;
        if (getLive(convId).userCancelled) {
          const restore = getLive(convId).restoreInputOnAbort;
          patchLive(convId, {
            streamText: "",
            streamThinking: "",
            streamStatus: "",
            thinkingStarted: false,
            failedAction: null,
            streaming: false,
            generating: false,
            controller: null,
            userCancelled: false,
            restoreInputOnAbort: false,
          });
          if (restore) setInput(text);
          return;
        }
        patchLive(convId, { controller: null, streaming: false });
        return;
      }
      if (stillMine()) {
        patchLive(convId, {
          streamText: formatClientStreamError(e, errorContext()),
          streamThinking: "",
          streamStatus: "",
          failedAction: "send",
          streaming: false,
          controller: null,
        });
      }
    }
  }, [convId, queryClient]);

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
    const liveState = getLive(convId);
    const wasGenerating = liveState.generating;
    patchLive(convId, { userCancelled: true, restoreInputOnAbort: true });
    liveState.controller?.abort();
    if (wasGenerating) {
      void fetch(`/api/conversations/${convId}/generate/cancel`, { method: "POST" });
    } else {
      void api.conversations.cancelMessages(convId);
    }
    const probe = (jobs || []).find(
      (j: any) =>
        j.conversation_id === convId
        && j.mode === "schema_probe"
        && ["queued", "awaiting_extension", "dispatched"].includes(String(j.status || "")),
    );
    if (probe?.id) {
      void api.jobs.cancel(probe.id).then(() => {
        queryClient.invalidateQueries({ queryKey: ["jobs"] });
      });
    }
  }, [convId, jobs, queryClient]);

  const handleCancelDiscovery = useCallback(async () => {
    const probeId = activeProbe?.id;
    patchLive(convId, {
      userCancelled: true,
      restoreInputOnAbort: false,
      streamText: "",
      streamThinking: "",
      streamStatus: "",
      thinkingStarted: false,
      failedAction: null,
      streaming: false,
      generating: false,
      controller: null,
    });
    getLive(convId).controller?.abort();
    await Promise.allSettled([
      fetch(`/api/conversations/${convId}/generate/cancel`, { method: "POST" }),
      probeId ? api.jobs.cancel(probeId) : Promise.resolve(),
    ]);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      queryClient.invalidateQueries({ queryKey: ["messages", convId] }),
      queryClient.invalidateQueries({ queryKey: ["conversations"] }),
    ]);
  }, [activeProbe?.id, convId, queryClient]);

  const handleRetry = useCallback(async () => {
    if (failedAction === "send" && lastSendText) {
      void sendMessage(lastSendText);
      return;
    }
    const liveText = getLive(convId).streamText || streamText || "";
    // Connection drops leave Chrome/Studio working — reattach instead of cancelling discovery.
    if (activeProbe?.id && !isResumableGenerateFailure(liveText)) {
      await handleCancelDiscovery();
    }
    void handleGenerate();
  }, [failedAction, lastSendText, sendMessage, handleGenerate, activeProbe?.id, handleCancelDiscovery, convId, streamText]);

  const hasPhotos = (photos && (photos as any[]).length > 0);
  const hasMessages = messages && (messages as any[]).length > 0;
  const hasListingJson = Boolean(messages?.some((m: any) => {
    const json = extractJson(m.text);
    return Boolean(json && isListingJson(json));
  }) || (listing?.listing && isListingJson(JSON.stringify(listing.listing))));
  const streamFailed = isStreamError(streamText);
  const errorHint = activeProbe
    ? isResumableGenerateFailure(streamText || "")
      ? "Studio is still discovering fields in Chrome. Retry reconnects — use Cancel discovery only if Chrome is stuck."
      : `Active discovery job: ${activeProbe.current_step || activeProbe.status}. Cancel it here if Chrome is stuck, then retry.`
    : /connection dropped/i.test(streamText || "")
      ? "This is a client/network failure, not a model refusal. Retry resumes the same generate when Studio still has it running."
      : /HTTP 5\d\d/i.test(streamText || "")
        ? "Studio hit an internal error before the model answered. Retry; if it keeps failing, check Studio logs or restart Studio."
        : /HTTP \d+/i.test(streamText || "")
          ? "The generate request was rejected before streaming started. Check Settings (provider sign-in / API key), then retry."
          : "";
  const streamVisible = streamFailed ? "" : assistantDisplayText(streamText);
  // Persist finishes (and messages refetch) before the SSE stream is cleared —
  // hide the live bubble once the same assistant prose is already on screen.
  const streamAlreadyPersisted = Boolean(
    streamVisible
      && messages?.some((m: any) => {
        if (m.role !== "assistant" && m.role !== "model") return false;
        return assistantDisplayText(m.text) === streamVisible;
      }),
  );
  const showStreamBubble = Boolean(streamText && !streamFailed && !streamAlreadyPersisted);
  const busy = streaming || generating;
  const canRetry = failedAction === "send" ? Boolean(lastSendText) : Boolean(hasPhotos);
  const awaitingSellerAnswers = Boolean(
    messages?.length
      && (() => {
        const lastUserIdx = [...messages].map((m: any) => m.role).lastIndexOf("user");
        // Legacy conversations may still have system prompts that asked for answers.
        return messages.slice(lastUserIdx + 1).some((m: any) => {
          if (m.role !== "system") return false;
          return /answer the questions above|please confirm|waiting for your answers/i.test(m.text || "");
        });
      })(),
  );
  const composerPlaceholder = !hasPhotos
    ? "Upload photos to begin"
    : awaitingSellerAnswers
      ? "Answer the questions above..."
      : hasMessages
        ? "Refine the listing..."
        : "Add a note, or generate the listing...";

  useEffect(() => {
    const reattach = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      const liveState = getLive(convId);
      if (liveState.controller || liveState.userCancelled || !liveState.generating) return;
      void streamFromFetch(
        `/api/conversations/${convId}/generate`,
        liveState.streamStatus || "Analyzing photos…",
      );
    };
    document.addEventListener("visibilitychange", reattach);
    reattach();
    return () => document.removeEventListener("visibilitychange", reattach);
  }, [convId, generating, streamFromFetch]);

  useEffect(() => {
    const liveState = getLive(convId);
    if (!liveState.generating || liveState.controller) return;
    if (!hasListingJson) return;
    patchLive(convId, {
      generating: false,
      streaming: false,
      streamText: "",
      streamThinking: "",
      streamStatus: "",
      thinkingStarted: false,
    });
  }, [convId, hasListingJson]);

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

    if (m.role === "system" && isCompResearch(m.text)) {
      return <SoldCompsCard key={m.id} text={m.text} />;
    }

    if (m.role === "system") {
      return (
        <div key={m.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "4px 0" }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-border-bright)", flexShrink: 0, marginTop: 6 }} />
          <span className="msg-system" style={{ padding: 0, borderLeft: "none", maxWidth: "none", whiteSpace: "pre-wrap" }}>{m.text}</span>
        </div>
      );
    }

    const visible = assistantDisplayText(m.text);
    if (!visible) return null;
    return (
      <div key={m.id} className="msg msg-assistant">
        <ChatMarkdown text={visible} />
      </div>
    );
  }

  return (
    <div className="chat-panel">
      <div ref={scrollRef} className="chat-scroll">
        {isLoading && !hasMessages && (
          <div className="empty-state" style={{ padding: "16px 0" }}><p className="text-xs text-muted">Loading...</p></div>
        )}

        {!isLoading && !hasMessages && !busy && !streamFailed && (
          <div className="empty-state" style={{ padding: "32px 16px" }}>
            <h3 style={{ fontFamily: "var(--font-serif)", fontStyle: "italic", fontSize: 20, marginBottom: 4, lineHeight: 1.2 }}>Generate a Listing</h3>
            {hasPhotos ? (
              <>
                <p className="text-xs font-mono text-muted">{(photos as any[]).length} photo{(photos as any[]).length !== 1 ? "s" : ""} uploaded</p>
                <button type="button" className="btn btn-primary" onClick={handleGenerate} disabled={generating || streaming} style={{ marginTop: 12, padding: "9px 22px" }}>
                  Generate Listing
                </button>
              </>
            ) : (
              <p className="text-xs font-mono text-muted">Upload photos to begin</p>
            )}
          </div>
        )}

        {messages?.map(renderMessage)}

        {(streaming || generating) && !streamFailed && (streamThinking || !streamText) && (
          <div className="thinking-block">
            <div className="thinking-header">
              <div className="thinking-dot" />
              <span className="text-xs font-mono text-muted">
                {generating && !streamThinking
                  ? streamStatus && streamStatus !== "thinking"
                    ? streamStatus
                    : "Analyzing photos…"
                  : "Thinking"}
              </span>
            </div>
            {streamThinking ? (
              <div ref={thinkingBodyRef} className="thinking-body">
                <ul className="thinking-todos">
                  {parseThinkingTodos(streamThinking, Boolean(streamText)).map((item, index) => (
                    <li
                      key={`${index}-${item.text}`}
                      className={[
                        "thinking-todo",
                        item.done ? "is-done" : "",
                        item.current ? "is-current" : "",
                        item.current && !streamText ? "is-live" : "",
                      ].filter(Boolean).join(" ")}
                    >
                      <span className="thinking-todo-mark">{item.done ? "- [x]" : "- [ ]"}</span>
                      <span className="thinking-todo-text">{item.text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        )}

        {showStreamBubble && (
          streamVisible ? (
            <div className="msg msg-assistant">
              <ChatMarkdown text={streamVisible} />
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 8 }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-cobalt)", flexShrink: 0 }} />
              <span className="text-xs font-mono text-muted">UPDATING LISTING…</span>
            </div>
          )
        )}

        {streamFailed && (
          <div className="chat-error" role="alert">
            <div className="chat-error-text">{streamText}</div>
            {errorHint ? <div className="chat-error-hint">{errorHint}</div> : null}
            <div className="chat-error-actions">
              {activeProbe ? (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => { void handleCancelDiscovery(); }}
                  disabled={busy}
                >
                  Cancel discovery
                </button>
              ) : null}
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => { void handleRetry(); }}
                disabled={busy || !canRetry}
              >
                {busy ? "Retrying..." : activeProbe ? "Cancel & retry" : "Retry"}
              </button>
            </div>
          </div>
        )}

        {hasMessages && !hasListingJson && !streamFailed && !busy && hasPhotos && (
          <div className="chat-error">
            <div className="chat-error-text">Listing generation did not finish.</div>
            {activeProbe ? (
              <div className="chat-error-hint">
                Field discovery is still running in Chrome. Cancel it from here, then retry.
              </div>
            ) : null}
            <div className="chat-error-actions">
              {activeProbe ? (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => { void handleCancelDiscovery(); }}
                >
                  Cancel discovery
                </button>
              ) : null}
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => { void (activeProbe ? handleRetry() : handleGenerate()); }}
              >
                {activeProbe ? "Cancel & retry" : "Retry"}
              </button>
            </div>
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
