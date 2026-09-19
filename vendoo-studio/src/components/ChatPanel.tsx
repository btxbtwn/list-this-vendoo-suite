import React, { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BrowserField } from "../api/client";
import type { Job, Message } from "../api/types";
import { ChatMarkdown } from "./ChatMarkdown";
import { SoldCompsCard } from "./SoldCompsCard";
import { parseThinkingTodos, type ThinkingTodo } from "./thinkingTodos";

interface Props {
  convId: string;
  queuedMessage?: string | null;
  onQueuedMessageConsumed?: () => void;
  /** Draft open in Studio's browser. Messages then go to the fix agent with the picked fields. */
  browser?: { jobId: string; fields: BrowserField[] } | null;
  onBrowserFieldsChange?: (fields: BrowserField[]) => void;
}

const MARKET_LABELS: Record<string, string> = {
  general: "Vendoo",
  ebay: "eBay",
  etsy: "Etsy",
  poshmark: "Poshmark",
  mercari: "Mercari",
  depop: "Depop",
};

function thinkingItemClass(item: ThinkingTodo, live: boolean): string {
  return [
    item.done ? "is-done" : "",
    item.current ? "is-current" : "",
    item.current && live ? "is-live" : "",
  ].filter(Boolean).join(" ");
}

function ThinkingStreamBody({
  text,
  finished,
}: {
  text: string;
  finished: boolean;
}) {
  const items = parseThinkingTodos(text, finished);
  const live = !finished;
  if (items.length > 0 && items.every((item) => item.prose)) {
    return (
      <div className="thinking-prose">
        {items.map((item, index) => (
          <p
            key={`${index}-${item.text.slice(0, 24)}`}
            className={["thinking-prose-line", thinkingItemClass(item, live)].filter(Boolean).join(" ")}
          >
            {item.text}
          </p>
        ))}
      </div>
    );
  }
  return (
    <ul className="thinking-todos">
      {items.map((item, index) => (
        <li
          key={`${index}-${item.text}`}
          className={["thinking-todo", thinkingItemClass(item, live)].filter(Boolean).join(" ")}
        >
          <span className="thinking-todo-mark">{item.done ? "- [x]" : "- [ ]"}</span>
          <span className="thinking-todo-text">{item.text}</span>
        </li>
      ))}
    </ul>
  );
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
  if (/^[[{]/.test(visible)) return "";
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

type StreamRequestError = Error & { httpStatus?: number; body?: unknown };

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
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
type SseParseState = { eventType: string; parts: SseParts; dataLines: number };

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
    state.dataLines = 0;
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
  // Data lines within one event are joined with newlines (the server splits multi-line text this way).
  const text = state.dataLines++ > 0 ? `\n${chunk}` : chunk;
  if (state.eventType === "thinking") state.parts.thinking += text;
  else if (state.eventType === "status") state.parts.status = state.dataLines > 1 ? state.parts.status + text : text;
  else state.parts.content += text;
  onEvent(state.eventType, state.parts);
  return false;
}

function consumeSseText(
  text: string,
  onEvent: (event: string, parts: SseParts) => void,
): { parts: SseParts; sawDone: boolean } {
  const state: SseParseState = { eventType: "message", parts: { content: "", thinking: "", status: "" }, dataLines: 0 };
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
  const state: SseParseState = { eventType: "message", parts: { content: "", thinking: "", status: "" }, dataLines: 0 };
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

/** Start a generate for this listing; a mounted ChatPanel picks it up and streams it. */
export function queueChatGenerate(convId: string) {
  resetChatLive(convId);
  patchLive(convId, { generating: true, streamStatus: "Analyzing photos…" });
}

/** True while the listing is being generated or chat is still answering. */
export function useChatBusy(convId: string): boolean {
  return React.useSyncExternalStore(
    (listener) => {
      const live = getLive(convId);
      live.listeners.add(listener);
      return () => live.listeners.delete(listener);
    },
    () => {
      const live = getLive(convId);
      return live.streaming || live.generating;
    },
  );
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

export function ChatPanel({ convId, queuedMessage, onQueuedMessageConsumed, browser, onBrowserFieldsChange }: Props) {
  const browserRef = useRef(browser);
  browserRef.current = browser;
  const live = getLive(convId);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(live.streaming);
  const [generating, setGenerating] = useState(live.generating);
  const [streamText, setStreamText] = useState(live.streamText);
  const [streamThinking, setStreamThinking] = useState(live.streamThinking);
  const [streamStatus, setStreamStatus] = useState(live.streamStatus);
  const [failedAction, setFailedAction] = useState<"generate" | "send" | null>(live.failedAction);
  const [lastSendText, setLastSendText] = useState(live.lastSendText);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const thinkingBodyRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const queryClient = useQueryClient();

  const isNearBottom = (el: HTMLDivElement, threshold = 96) =>
    el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;

  const scrollChatToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo(0, el.scrollHeight);
  }, []);

  const pinChatToBottom = useCallback(() => {
    stickToBottomRef.current = true;
    scrollChatToBottom();
  }, [scrollChatToBottom]);

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
    (j) =>
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
    stickToBottomRef.current = true;
    scrollChatToBottom();
  }, [convId, scrollChatToBottom]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickToBottomRef.current) return;
    if (!isNearBottom(el)) {
      stickToBottomRef.current = false;
      return;
    }
    scrollChatToBottom();
  }, [messages, streamText, streamThinking, scrollChatToBottom]);

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

  const handleChatScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = isNearBottom(el);
  }, []);

  const handleChatWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    if (e.deltaY < 0) stickToBottomRef.current = false;
  }, []);

  const touchYRef = useRef<number | null>(null);
  const handleChatTouchStart = useCallback((e: React.TouchEvent<HTMLDivElement>) => {
    touchYRef.current = e.touches[0]?.clientY ?? null;
  }, []);
  const handleChatTouchMove = useCallback((e: React.TouchEvent<HTMLDivElement>) => {
    const y = e.touches[0]?.clientY;
    if (touchYRef.current == null || y == null) return;
    if (y > touchYRef.current + 2) stickToBottomRef.current = false;
    touchYRef.current = y;
  }, []);

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
      const probe = (queryClient.getQueryData<Job[]>(["jobs"]) || []).find(
        (j) =>
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
        } catch (first) {
          // Generation continues server-side; keep reattaching through mobile drops mid-discovery.
          if (
            canResumeGenerate
            && stillMine()
            && !isAbortError(first)
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
    } catch (e) {
      if (isAbortError(e)) {
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
        const failure = e as StreamRequestError | null;
        assembled = formatClientStreamError(failure?.body || e, {
          ...errorContext(),
          httpStatus: failure?.httpStatus,
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
    pinChatToBottom();
    patchLive(convId, {
      generating: true,
      streamStatus: "Analyzing photos…",
      thinkingStarted: true,
      userCancelled: false,
    });
    await streamFromFetch(`/api/conversations/${convId}/generate`, "Analyzing photos…");
  }, [convId, streamFromFetch, pinChatToBottom]);

  const sendMessage = useCallback(async (text: string) => {
    const browserContext = browserRef.current;
    const pointedAt = browserContext?.fields || [];
    if ((!text && !pointedAt.length) || getLive(convId).streaming) return;
    pinChatToBottom();
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
        body: JSON.stringify({
          text,
          ...(browserContext
            ? {
                browser: {
                  job_id: browserContext.jobId,
                  fields: pointedAt.map((field) => ({
                    marketplace: field.marketplace,
                    label: field.label,
                    value: field.value,
                  })),
                },
              }
            : {}),
        }),
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
      if (pointedAt.length) onBrowserFieldsChange?.([]);
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
    } catch (e) {
      if (isAbortError(e)) {
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
  }, [convId, queryClient, pinChatToBottom, onBrowserFieldsChange]);

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
      (j) =>
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

  const hasPhotos = Boolean(photos && photos.length > 0);
  const hasMessages = Boolean(messages && messages.length > 0);
  const hasListingJson = Boolean(messages?.some((m) => {
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
      : /timed out during|category selection timed out/i.test(streamText || "")
        ? "The listing model or Chrome step stalled. Retry generate. Cancel discovery only if the Listing tab shows a stuck probe."
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
      && messages?.some((m) => {
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
        const lastUserIdx = [...messages].map((m) => m.role).lastIndexOf("user");
        // Legacy conversations may still have system prompts that asked for answers.
        return messages.slice(lastUserIdx + 1).some((m) => {
          if (m.role !== "system") return false;
          return /answer the questions above|please confirm|waiting for your answers/i.test(m.text || "");
        });
      })(),
  );
  const composerPlaceholder = browser
    ? "Tell Studio what to fix in the Vendoo draft..."
    : !hasPhotos
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

  function renderMessage(m: Message) {
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
      <div
        ref={scrollRef}
        className="chat-scroll"
        onScroll={handleChatScroll}
        onWheel={handleChatWheel}
        onTouchStart={handleChatTouchStart}
        onTouchMove={handleChatTouchMove}
      >
        {isLoading && !hasMessages && (
          <div className="empty-state" style={{ padding: "16px 0" }}><p className="text-xs text-muted">Loading...</p></div>
        )}

        {!isLoading && !hasMessages && !busy && !streamFailed && (
          <div className="empty-state" style={{ padding: "32px 16px" }}>
            <h3 style={{ fontFamily: "var(--font-serif)", fontStyle: "italic", fontSize: 20, marginBottom: 4, lineHeight: 1.2 }}>Generate a Listing</h3>
            {hasPhotos ? (
              <>
                <p className="text-xs font-mono text-muted">{photos?.length ?? 0} photo{photos?.length !== 1 ? "s" : ""} uploaded</p>
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
                <ThinkingStreamBody text={streamThinking} finished={Boolean(streamText)} />
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
        {browser && browser.fields.length > 0 && (
          <div className="chat-browser-fields" aria-label="Fields pointed at in the Vendoo browser">
            <div className="chat-browser-fields-head">
              <span>
                {browser.fields.length} field{browser.fields.length === 1 ? "" : "s"} from the browser go with your message
              </span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => onBrowserFieldsChange?.([])}>
                Clear
              </button>
            </div>
            <div className="chat-browser-fields-list">
              {browser.fields.map((field) => (
                <span
                  key={`${field.marketplace}:${field.key || field.label}`}
                  className={`browser-chip${field.account_managed ? " is-muted" : ""}`}
                  title={field.value || "empty"}
                >
                  {MARKET_LABELS[field.marketplace] || field.marketplace} / {field.label}
                  {!field.filled && <span className="browser-chip-empty">empty</span>}
                  <button
                    type="button"
                    aria-label={`Remove ${field.label}`}
                    onClick={() => onBrowserFieldsChange?.(browser.fields.filter((item) => item !== field))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="chat-composer-pill">
          <textarea
            ref={textareaRef}
            className="chat-composer-input"
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={(e) => {
              const pasted = e.clipboardData?.getData("text/plain");
              if (pasted == null) return;
              // Keep paste reliable in the controlled composer (desktop webview
              // sometimes delivers Paste without updating React state).
              e.preventDefault();
              const el = e.currentTarget;
              const start = el.selectionStart ?? input.length;
              const end = el.selectionEnd ?? input.length;
              const next = `${input.slice(0, start)}${pasted}${input.slice(end)}`;
              setInput(next);
              requestAnimationFrame(() => {
                const cursor = start + pasted.length;
                el.setSelectionRange(cursor, cursor);
              });
            }}
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
              disabled={!input.trim() && !browser?.fields.length}
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
