import type {
  SendPreview,
  BackupSnapshot,
  BackupsStatus,
  Conversation,
  ConversationSummary,
  DatabaseReport,
  DeleteConversationResult,
  FillLogReport,
  Job,
  ListingData,
  ListingNames,
  ListingProviderId,
  PhotoProviderChoice,
  ListingResponse,
  ListingRevision,
  ListingUpdateResult,
  ConversationActivity,
  Message,
  OkResponse,
  Photo,
  PhotoUploadResult,
  PriceDropApplyResult,
  PriceDropCompsSource,
  PriceDropPreview,
  ProviderStatus,
  ProviderTestResult,
  VendooApiLogEntry,
  ChatGPTPendingLogin,
  RevisionRestoreResult,
  ValidationResult,
  VendooBulkImport,
  VendooLabelSync,
  VendooItemResult,
  MarketplaceForm,
  SuggestionsResponse,
  AnalyticsRange,
  InventoryAnalytics,
  ScoutCheck,
  ScoutState,
  SourceBoxInput,
  SourceBoxes,
  SourcingPrefs,
  SourcingEvidence,
  SourcingState,
} from "./types";
import { readSse } from "./sse";
import type { AdSpendEntry, AdSpendInput } from "./adSpend";
import type { AssistantMessage, AssistantStreamHandlers } from "./assistant";
import type { SaleCalendarData, SaleEventStatus, SalePlan, SaleRecord } from "./saleCalendar";

const BASE = "/api";

type ErrorBody = { detail?: unknown; message?: unknown } | null | undefined;
type ErrorItem = { msg?: string; message?: string } | string | null | undefined;

export function errorMessage(body: ErrorBody, fallback: string): string {
  const detail = body?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: ErrorItem) => (typeof item === "string" ? item : item?.msg || item?.message || ""))
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  if (detail && typeof detail === "object") {
    const record = detail as { message?: unknown; errors?: unknown };
    if (typeof record.message === "string" && record.message.trim()) return record.message;
    if (Array.isArray(record.errors)) {
      const messages = record.errors
        .map((item: ErrorItem) => (typeof item === "string" ? item : item?.message || item?.msg))
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
  }
  if (typeof body?.message === "string" && body.message.trim()) return body.message;
  return fallback;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorMessage(body, `Request failed: ${res.status}`));
  }
  return res.json();
}

async function requestWithTimeout<T>(
  path: string,
  options: RequestInit,
  timeoutMessage: string,
  timeoutMs = 30000,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await request<T>(path, { ...options, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) throw new Error(timeoutMessage);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export interface VendooSyncStatus {
  checked_at: string | null;
  conflict: boolean;
  revision_id: string | null;
}

export interface BrowserRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface BrowserViewport {
  width: number;
  height: number;
  scroll_x?: number;
  scroll_y?: number;
}

export interface BrowserField {
  marketplace: string;
  label: string;
  key: string;
  selector: string;
  value: string;
  filled: boolean;
  required: boolean;
  disabled: boolean;
  is_dropdown: boolean;
  account_managed: boolean;
  error: string;
  options: string[];
  rect: BrowserRect;
}

export interface BrowserInputEvent {
  kind: "mouse" | "key" | "text";
  type?: string;
  x_ratio?: number;
  y_ratio?: number;
  button?: "none" | "left" | "middle" | "right";
  buttons?: number;
  click_count?: number;
  delta_x?: number;
  delta_y?: number;
  modifiers?: number;
  key?: string;
  code?: string;
  text?: string;
}

export const api = {
  backups: {
    list: () => request<BackupsStatus>("/backups"),
    create: () => request<{ ok: boolean; snapshot: BackupSnapshot }>("/backups", { method: "POST" }),
    setFolder: (folder: string | null) =>
      request<{ ok: boolean; folder: string | null }>("/backups/folder", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder }),
      }),
  },
  catalog: {
    status: () => request<{running: boolean; complete: boolean; marketplaces: Record<string,
      {status: string; nodes: number; pending_branches: number; error: string | null}>}>("/catalog/sync"),
    sync: () => request<{started: boolean}>("/catalog/sync", {method: "POST"}),
    dropdownOptions: () =>
      request<{ forms: Record<string, Record<string, string[]>> }>("/catalog/dropdown-options"),
  },
  suggestions: {
    list: () => request<SuggestionsResponse>("/suggestions"),
  },
  analytics: {
    get: (range: AnalyticsRange) => request<InventoryAnalytics>(`/analytics?range=${range}`),
  },
  scout: {
    list: () => request<ScoutState>("/scout"),
    create: async (files: File[], askingPrice: number | null): Promise<ScoutCheck> => {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      if (askingPrice != null) form.append("asking_price", String(askingPrice));
      const response = await fetch(`${BASE}/scout`, { method: "POST", body: form });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(data, `Check failed: ${response.status}`));
      return data as ScoutCheck;
    },
    setAskingPrice: (id: string, askingPrice: number | null) =>
      request<ScoutCheck>(`/scout/${id}`, { method: "PATCH", body: JSON.stringify({ asking_price: askingPrice }) }),
    decide: (id: string, decision: "bought" | "passed") =>
      request<ScoutCheck>(`/scout/${id}/decision`, { method: "POST", body: JSON.stringify({ decision }) }),
  },
  assistant: {
    messages: () => request<AssistantMessage[]>("/assistant/messages"),
    clear: () => request<{ ok: boolean }>("/assistant/messages", { method: "DELETE" }),
    /** Stream an answer; the question and what was answered are saved server-side. */
    ask: async (text: string, handlers: AssistantStreamHandlers, signal?: AbortSignal): Promise<void> => {
      const res = await fetch(`${BASE}/assistant/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ text }),
        cache: "no-store",
        signal,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errorMessage(body, `Request failed: ${res.status}`));
      }
      let failure = "";
      await readSse(res, (event, data) => {
        if (event === "message") handlers.onText(data);
        else if (event === "status") handlers.onStatus(data);
        else if (event === "thinking") handlers.onStatus("Thinking…");
        else if (event === "error") failure = data;
      });
      if (failure) throw new Error(failure);
    },
  },
  adSpend: {
    list: () => request<AdSpendEntry[]>("/analytics/ads"),
    create: (entry: AdSpendInput) => request<AdSpendEntry>("/analytics/ads", { method: "POST", body: JSON.stringify(entry) }),
    update: (id: string, entry: AdSpendInput) => request<AdSpendEntry>(`/analytics/ads/${id}`, { method: "PUT", body: JSON.stringify(entry) }),
    remove: (id: string) => request<{ ok: boolean }>(`/analytics/ads/${id}`, { method: "DELETE" }),
  },
  saleCalendar: {
    record: (record: SaleRecord) => request<{ id: string }>("/analytics/calendar/records", { method: "POST", body: JSON.stringify(record) }),
    editRecord: (id: string, record: SaleRecord) => request<{ id: string }>(`/analytics/calendar/records/${id}`, { method: "PUT", body: JSON.stringify(record) }),
    get: (timezone: string) => request<SaleCalendarData>(`/analytics/calendar?timezone=${encodeURIComponent(timezone)}`),
    create: (plan: SalePlan) => request<{ id: string }>("/analytics/calendar", { method: "POST", body: JSON.stringify(plan) }),
    update: (id: string, plan: SalePlan) => request<{ id: string }>(`/analytics/calendar/${id}`, { method: "PUT", body: JSON.stringify(plan) }),
    status: (id: string, status: SaleEventStatus) => request<{ ok: boolean }>(`/analytics/calendar/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
    remove: (id: string) => request<{ ok: boolean }>(`/analytics/calendar/${id}`, { method: "DELETE" }),
  },

  boxes: {
    list: () => request<SourceBoxes>("/boxes"),
    create: (body: SourceBoxInput) =>
      request<SourceBoxes>("/boxes", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Partial<SourceBoxInput>) =>
      request<SourceBoxes>(`/boxes/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (id: string) => request<SourceBoxes>(`/boxes/${id}`, { method: "DELETE" }),
  },
  sourcing: {
    get: () => request<SourcingState>("/sourcing"),
    refresh: () => request<SourcingState>("/sourcing/refresh", { method: "POST" }),
    evidence: (theme: string) =>
      request<SourcingEvidence>(`/sourcing/evidence?theme=${encodeURIComponent(theme)}`),
    savePrefs: (prefs: Partial<SourcingPrefs>) =>
      request<SourcingState>("/sourcing/prefs", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prefs),
      }),
  },
  vendooApi: {
    listingFields: (convId: string) =>
      request<{ ok: boolean; forms: MarketplaceForm[] }>(
        `/conversations/${convId}/vendoo-api/fields`,
      ),
    create: (convId: string) =>
      request<{
        ok: boolean;
        job_id: string;
        item_id: string;
        url: string;
        unresolved: { marketplace?: string; field?: string; reason?: string }[];
        unfilled: { marketplace?: string; field?: string; reason?: string }[];
        diff: unknown[];
      }>(`/conversations/${convId}/vendoo-api/create`, { method: "POST" }),
    save: (convId: string) =>
      request<{ ok: boolean; item_id: string; updated: string[]; relist_needed: string[] }>(
        `/conversations/${convId}/vendoo-api/save`, { method: "POST" },
      ),
    relistDone: (convId: string) =>
      request<{ ok: boolean }>(
        `/conversations/${convId}/vendoo-api/relist-done`, { method: "POST" },
      ),
    sync: (convId: string, signal?: AbortSignal) =>
      request<{
        ok: boolean;
        action: "pull" | "label" | "none" | "unavailable";
        reason: string;
        item_id?: string;
        revision_id?: string;
        vendoo_status?: string;
      }>(
        `/conversations/${convId}/vendoo-api/sync`, { method: "POST", signal },
      ),
    syncStatus: (convId: string) =>
      request<VendooSyncStatus>(`/conversations/${convId}/vendoo-api/sync`),
    pull: (convId: string) =>
      request<{ ok: boolean; item_id: string; revision_id: string }>(
        `/conversations/${convId}/vendoo-api/pull`, { method: "POST" },
      ),
  },

  health: () => request<{ status: string; version: string }>("/health"),

  status: () =>
    request<{
      version: string;
      provider_configured: boolean;
      extension_connected: boolean;
      active_job_id: string | null;
      packaged?: boolean;
      chrome_available?: boolean;
      conversations?: number;
      setup_guide_dismissed?: boolean;
      data_dir?: string;
    }>("/status"),

  conversations: {
    duplicateVendooLinks: () => request<{
      vendoo_item_id: string;
      vendoo_url: string;
      listings: { id: string; title: string }[];
    }[]>("/conversations/vendoo-link-duplicates"),
    list: () => request<ConversationSummary[]>("/conversations"),
    get: (id: string) => request<Conversation>(`/conversations/${id}`),
    create: (body?: { title?: string; notes?: string; box_id?: string | null }) =>
      request<Conversation>("/conversations", { method: "POST", body: JSON.stringify(body || {}) }),
    // Status is not here on purpose: it follows the bound Vendoo item.
    update: (id: string, body: { title?: string; notes?: string; box_id?: string | null }) =>
      request<Conversation>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    settle: (id: string) =>
      request<Conversation>(`/conversations/${id}/settle`, { method: "POST" }),
    unsettle: (id: string) =>
      request<Conversation>(`/conversations/${id}/unsettle`, { method: "POST" }),
    linkVendoo: (id: string, urlOrId: string) =>
      request<{
        conversation: Conversation;
        vendoo_item_id: string;
        vendoo_url: string;
      }>(`/conversations/${id}/vendoo-link`, {
        method: "POST",
        body: JSON.stringify({ url_or_id: urlOrId }),
      }),
    stop: (id: string) =>
      request<{ ok: boolean }>(`/conversations/${id}/stop`, { method: "POST" }),
    activity: (id: string) => request<ConversationActivity>(`/conversations/${id}/activity`),
    messages: (id: string) => request<Message[]>(`/conversations/${id}/messages`),
    photos: (id: string) => request<Photo[]>(`/conversations/${id}/photos`),
    deletePhoto: (convId: string, photoId: string) =>
      request<OkResponse>(`/conversations/${convId}/photos/${photoId}`, { method: "DELETE" }),
    delete: (id: string) =>
      request<DeleteConversationResult>(`/conversations/${id}`, { method: "DELETE" }),
    reset: (id: string, opts?: { keepInputs?: boolean }) =>
      requestWithTimeout<Conversation>(`/conversations/${id}/reset`, {
        method: "POST",
        body: JSON.stringify({ keep_inputs: Boolean(opts?.keepInputs) }),
      }, "Resetting the listing took too long. Check the listing before trying Regenerate again; you do not need to restart Studio."),
    reorderPhotos: (convId: string, orderedIds: string[]) =>
      request<OkResponse>(`/conversations/${convId}/photos/order`, {
        method: "PATCH",
        body: JSON.stringify(orderedIds),
      }),
    uploadPhotos: (convId: string, files: File[]): Promise<PhotoUploadResult> => {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      return fetch(`${BASE}/conversations/${convId}/photos`, { method: "POST", body: form }).then(
        async (r) => {
          const data = await r.json();
          if (!r.ok) {
            throw new Error(data.detail || `Upload failed: ${r.status}`);
          }
          return data;
        }
      );
    },
  },

  imports: {
    bulkStatus: () => request<VendooBulkImport>("/imports/vendoo/bulk"),
    startBulk: () => request<VendooBulkImport>("/imports/vendoo/bulk", { method: "POST" }),
    cancelBulk: () =>
      request<VendooBulkImport>("/imports/vendoo/bulk/cancel", { method: "POST" }),
    syncLabels: () => request<VendooLabelSync>("/imports/vendoo/labels", { method: "POST" }),
    labelSyncStatus: () => request<VendooLabelSync>("/imports/vendoo/labels"),
  },

  listings: {
    get: (convId: string) => request<ListingResponse>(`/conversations/${convId}/listing`),
    update: (convId: string, listing: ListingData) =>
      request<ListingUpdateResult>(`/conversations/${convId}/listing`, {
        method: "PUT",
        body: JSON.stringify({ listing }),
      }),
    validate: (convId: string) =>
      request<ValidationResult>(`/conversations/${convId}/listing/validate`, { method: "POST" }),
    revisions: (convId: string) => request<ListingRevision[]>(`/conversations/${convId}/revisions`),
    revision: (convId: string, revisionId: string) =>
      request<{ id: string; listing: ListingData }>(`/conversations/${convId}/revisions/${revisionId}`),
    restore: (convId: string, revisionId: string, expectedRevisionId: string) =>
      request<RevisionRestoreResult>(`/conversations/${convId}/revisions/${revisionId}/restore`, {
        method: "POST", body: JSON.stringify({ expected_revision_id: expectedRevisionId }),
      }),
    priceDropPreview: (convId: string) =>
      request<PriceDropPreview>(`/conversations/${convId}/price-drop/preview`, { method: "POST" }),
    /** Stream sold comps: each source's progress, then the preview they imply. */
    priceDropComps: async (
      convId: string,
      handlers: {
        onSource: (source: PriceDropCompsSource) => void;
        onStep: (text: string) => void;
        onPreview: (preview: PriceDropPreview) => void;
      },
      signal?: AbortSignal,
    ): Promise<void> => {
      const res = await fetch(`${BASE}/conversations/${convId}/price-drop/comps`, {
        method: "POST",
        headers: { Accept: "text/event-stream" },
        cache: "no-store",
        signal,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errorMessage(body, `Request failed: ${res.status}`));
      }
      let failure = "";
      await readSse(res, (event, data) => {
        if (event === "source") handlers.onSource(JSON.parse(data) as PriceDropCompsSource);
        else if (event === "step") handlers.onStep(data);
        else if (event === "preview") handlers.onPreview(JSON.parse(data) as PriceDropPreview);
        else if (event === "error") failure = data;
      });
      if (failure) throw new Error(failure);
    },
    applyPriceDrop: (
      convId: string,
      body: { price: number; percent?: number | null; mode: "percent" | "comps" | "custom" },
    ) =>
      requestWithTimeout<PriceDropApplyResult>(`/conversations/${convId}/price-drop`, {
        method: "POST",
        body: JSON.stringify(body),
      }, "Saving the price took too long. Check the listing's price before confirming again; you do not need to restart Studio."),
  },

  jobs: {
    send: async (conversationId: string) => {
      // The button click approves the send. Freeze its preparation before queueing.
      const prepared = await request<SendPreview>("/jobs/send-preview", {
        method: "POST", body: JSON.stringify({ conversation_id: conversationId }),
      });
      return request<Job>("/jobs/send", {
        method: "POST", body: JSON.stringify({ conversation_id: conversationId, review_id: prepared.review_id }),
      });
    },
    queue: () => request<{
      work: { conversation_id: string; title: string; detail: string }[];
      jobs: Job[];
    }>("/jobs/queue"),
    list: (conversationId?: string) => {
      const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";
      return request<Job[]>(`/jobs${query}`);
    },
    ensureDraft: (conversationId: string) =>
      request<Job>("/jobs/ensure-draft", {
        method: "POST",
        body: JSON.stringify({ conversation_id: conversationId }),
      }),
    get: (id: string) => request<Job>(`/jobs/${id}`),
    importDraft: (id: string) =>
      request<{ ok: boolean; listing_title: string; photo_count: number; photo_warnings: string[] }>(
        `/jobs/${id}/import-draft`,
        { method: "POST" },
      ),
    fillLog: (id: string) => request<FillLogReport>(`/jobs/${id}/fill-log`),
    marketplaceStatuses: (ids: string[]) =>
      request<Record<string, Record<string, unknown>>>(
        `/jobs/marketplace-statuses?job_ids=${encodeURIComponent(ids.join(","))}`,
      ),
    vendooItem: (
      id: string,
      opts?: { refresh?: boolean; cacheOnly?: boolean; resolvePhotos?: boolean; signal?: AbortSignal },
    ) => {
      const params = new URLSearchParams();
      if (opts?.refresh) params.set("refresh", "true");
      if (opts?.cacheOnly) params.set("cache_only", "true");
      if (opts?.resolvePhotos) params.set("resolve_photos", "true");
      const query = params.toString();
      return request<VendooItemResult>(`/jobs/${id}/vendoo-item${query ? `?${query}` : ""}`, { method: "POST", signal: opts?.signal });
    },
    resolveCategory: (id: string, query?: string) =>
      request<{ ok: boolean; query?: string; path?: string; matches?: { text?: string; path?: string; score?: number }[]; error?: string }>(
        `/jobs/${id}/resolve-category`,
        {
          method: "POST",
          body: JSON.stringify({ query: query || null }),
        },
      ),
    open: (id: string) =>
      requestWithTimeout<{ ok: boolean; url: string; via: "extension" | "chrome" }>(
        `/jobs/${id}/open`, { method: "POST" },
        "Opening the listing took too long. Try Open listing again; you do not need to restart Studio.",
        25000,
      ),
    browser: {
      open: (id: string) =>
        request<{ ok: boolean; controller: string; input?: boolean; warning?: string }>(`/jobs/${id}/browser/open`, {
          method: "POST",
          body: JSON.stringify({}),
        }),
      close: (id: string) => request<{ ok: boolean }>(`/jobs/${id}/browser/close`, { method: "POST" }),
      input: (id: string, events: BrowserInputEvent[]) =>
        request<{ sent: boolean }>(`/jobs/${id}/browser/input`, {
          method: "POST",
          body: JSON.stringify({ events }),
        }),
      pick: (id: string, xRatio: number, yRatio: number) =>
        request<{ ok: boolean; viewport: BrowserViewport; field: BrowserField | null; element: { text: string; danger: boolean } | null }>(
          `/jobs/${id}/browser/pick`,
          { method: "POST", body: JSON.stringify({ x_ratio: xRatio, y_ratio: yRatio }) },
        ),
      snapshot: (id: string) =>
        request<{ ok: boolean; url: string; viewport: BrowserViewport; fields: BrowserField[] }>(`/jobs/${id}/browser/snapshot`),
    },
    cancel: (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  },

  settings: {
    provider: () => request<ProviderStatus>("/settings/provider"),
    setProvider: (apiKey: string) =>
      request<OkResponse>("/settings/provider", {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      }),
    deleteKey: () => request<OkResponse>("/settings/provider/key", { method: "DELETE" }),
    testConnection: () => request<ProviderTestResult>("/settings/provider/test", { method: "POST" }),
    testMimo: () =>
      request<ProviderTestResult>("/settings/provider/mimo/test", { method: "POST" }),
    setPreferredProvider: (order: {
      primary: ListingProviderId;
      fallback?: ListingProviderId | "none" | null;
    }) =>
      request<{ ok: boolean; primary: ListingProviderId; fallback: ListingProviderId | "none" }>(
        "/settings/provider/preferred",
        {
          method: "PUT",
          body: JSON.stringify(order),
        },
      ),
    setPhotoProvider: (choice: PhotoProviderChoice) =>
      request<{ ok: boolean; photo_provider: PhotoProviderChoice }>("/settings/provider/photos", {
        method: "PUT",
        body: JSON.stringify({ choice }),
      }),
    brave: () => request<{ configured: boolean; masked_key: string | null }>("/settings/brave"),
    setBrave: (apiKey: string) =>
      request<{ ok: boolean; configured: boolean; masked_key: string | null }>("/settings/brave", {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      }),
    deleteBrave: () =>
      request<{ ok: boolean; configured: boolean; masked_key: string | null }>("/settings/brave", {
        method: "DELETE",
      }),
    testBrave: () => request<{ ok: boolean; error?: string | null }>("/settings/brave/test", { method: "POST" }),
    cursor: () => request<{ configured: boolean; masked_key: string | null }>("/settings/cursor"),
    setCursor: (apiKey: string) =>
      request<{ ok: boolean; configured: boolean; masked_key: string | null }>("/settings/cursor", {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      }),
    deleteCursor: () =>
      request<{ ok: boolean; configured: boolean; masked_key: string | null }>("/settings/cursor", {
        method: "DELETE",
      }),
    testCursor: () => request<{ ok: boolean; error?: string | null }>("/settings/cursor/test", { method: "POST" }),
    chatgptLogin: () => request<ChatGPTPendingLogin>("/settings/chatgpt/login", { method: "POST" }),
    chatgptCancelLogin: () => request<OkResponse>("/settings/chatgpt/login", { method: "DELETE" }),
    chatgptLogout: () => request<OkResponse>("/settings/chatgpt", { method: "DELETE" }),
    /** WebSocket that runs `claude auth login` for the sign-in terminal. */
    claudeLoginTerminalUrl: (cols: number, rows: number) => {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      return `${scheme}://${window.location.host}${BASE}/settings/claude/terminal?cols=${cols}&rows=${rows}`;
    },
    claudeModels: () =>
      request<{
        models: { value: string; label: string; efforts: string[] }[];
        vision_model: string;
        listing_model: string;
        effort: string | null;
        efforts: string[];
        error?: string | null;
      }>("/settings/claude/models"),
    setClaudeModels: (models: { vision_model?: string; listing_model?: string; effort?: string }) =>
      request<OkResponse>("/settings/claude/models", {
        method: "PUT",
        body: JSON.stringify(models),
      }),
    chatgptModels: () =>
      request<{
        models: string[];
        vision_model: string;
        listing_model: string;
        reasoning_effort: string;
        reasoning_efforts: string[];
        error?: string | null;
      }>("/settings/chatgpt/models"),
    setChatGPTModels: (models: { vision_model?: string; listing_model?: string; reasoning_effort?: string }) =>
      request<{ ok: boolean; vision_model: string; listing_model: string; reasoning_effort: string }>(
        "/settings/chatgpt/models",
        {
          method: "PUT",
          body: JSON.stringify(models),
        },
      ),
    cursorModels: () =>
      request<{
        models: string[];
        vision_model: string;
        listing_model: string;
        reasoning: { param: string; options: { value: string; label: string }[]; value: string } | null;
        error?: string | null;
      }>("/settings/cursor/models"),
    setCursorModels: (models: { vision_model?: string; listing_model?: string; reasoning_effort?: string }) =>
      request<{ ok: boolean; vision_model: string; listing_model: string }>("/settings/cursor/models", {
        method: "PUT",
        body: JSON.stringify(models),
      }),
    marketplaces: () =>
      request<{
        available: { id: string; label: string; fillable: boolean }[];
        selected: string[];
        fillable: string[];
      }>("/settings/marketplaces"),
    setMarketplaces: (selected: string[]) =>
      request<{
        ok: boolean;
        available: { id: string; label: string; fillable: boolean }[];
        selected: string[];
        fillable: string[];
      }>("/settings/marketplaces", {
        method: "PUT",
        body: JSON.stringify({ selected }),
      }),
    packageDimensions: () =>
      request<{ length: number; width: number; height: number }>("/settings/package-dimensions"),
    setPackageDimensions: (dimensions: { length: number; width: number; height: number }) =>
      request<{ ok: boolean; length: number; width: number; height: number }>("/settings/package-dimensions", {
        method: "PUT",
        body: JSON.stringify(dimensions),
      }),
    hiddenFields: (conversationId?: string) =>
      request<{
        always: { marketplace: string; field: string; label: string }[];
        listing: { marketplace: string; field: string; label: string }[];
      }>(`/settings/hidden-fields${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`),
    hideField: (body: {
      marketplace: string;
      field: string;
      label?: string;
      scope: "always" | "listing";
      conversation_id?: string;
    }) =>
      request<{
        ok: boolean;
        always: { marketplace: string; field: string; label: string }[];
        listing: { marketplace: string; field: string; label: string }[];
      }>("/settings/hidden-fields", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    showField: (body: {
      marketplace: string;
      field: string;
      scope: "always" | "listing";
      conversation_id?: string;
    }) =>
      request<{
        ok: boolean;
        always: { marketplace: string; field: string; label: string }[];
        listing: { marketplace: string; field: string; label: string }[];
      }>("/settings/hidden-fields", {
        method: "DELETE",
        body: JSON.stringify(body),
      }),
    restoreAllHiddenFields: (conversationId?: string) =>
      request<{
        ok: boolean;
        always: { marketplace: string; field: string; label: string }[];
        listing: { marketplace: string; field: string; label: string }[];
      }>("/settings/hidden-fields/restore-all", {
        method: "POST",
        body: JSON.stringify({ conversation_id: conversationId }),
      }),
    restoreMatchingHiddenFields: (
      fields: { marketplace: string; field: string }[],
      conversationId?: string,
    ) =>
      request<{
        ok: boolean;
        always: { marketplace: string; field: string; label: string }[];
        listing: { marketplace: string; field: string; label: string }[];
      }>("/settings/hidden-fields/restore-matching", {
        method: "POST",
        body: JSON.stringify({ fields, conversation_id: conversationId }),
      }),
    dismissSetupGuide: () =>
      request<{ ok: boolean; dismissed: boolean }>("/settings/setup-guide/dismiss", { method: "POST" }),
    dataFolder: () =>
      request<{ path: string; contains: string[]; secrets: string }>("/settings/data-folder"),
    database: () => request<DatabaseReport>("/settings/database"),
    pruneDatabase: () =>
      request<DatabaseReport>("/settings/database/prune", { method: "POST" }),
    ui: () =>
      request<{
        ok: boolean;
        recent_vendoo_labels: string[];
        settled_shelf_expanded: boolean;
        hidden_vendoo_labels: string[];
        theme: "dark" | "light" | "system";
        listing_names: ListingNames;
      }>("/settings/ui"),
    setUi: (body: {
      recent_vendoo_labels?: string[];
      settled_shelf_expanded?: boolean;
      theme?: "dark" | "light" | "system";
      listing_names?: ListingNames;
      remember_labels?: string | string[];
      restore_labels?: string[];
      forget_label?: string;
    }) =>
      request<{
        ok: boolean;
        recent_vendoo_labels: string[];
        settled_shelf_expanded: boolean;
        hidden_vendoo_labels: string[];
        theme: "dark" | "light" | "system";
        listing_names: ListingNames;
      }>("/settings/ui", { method: "PUT", body: JSON.stringify(body) }),
    formulas: () =>
      request<{
        ok: boolean;
        title: string;
        description: string;
        default_title: string;
        default_description: string;
      }>("/settings/formulas"),
    setFormulas: (body: { title?: string | null; description?: string | null }) =>
      request<{
        ok: boolean;
        title: string;
        description: string;
        default_title: string;
        default_description: string;
      }>("/settings/formulas", { method: "PUT", body: JSON.stringify(body) }),
    tailscale: () =>
      request<{
        available: boolean;
        installed: boolean;
        enabled: boolean;
        https_port: number;
        target: string;
        dns_name: string | null;
        url: string | null;
        state: string;
        error: string | null;
        funnel: boolean;
      }>("/settings/tailscale"),
    enableTailscale: () =>
      request<{
        available: boolean;
        installed: boolean;
        enabled: boolean;
        https_port: number;
        target: string;
        dns_name: string | null;
        url: string | null;
        state: string;
        error: string | null;
        funnel: boolean;
      }>("/settings/tailscale/enable", { method: "POST" }),
    disableTailscale: () =>
      request<{
        available: boolean;
        installed: boolean;
        enabled: boolean;
        https_port: number;
        target: string;
        dns_name: string | null;
        url: string | null;
        state: string;
        error: string | null;
        funnel: boolean;
      }>("/settings/tailscale/disable", { method: "POST" }),
    vendooApiLogs: () => request<{ entries: VendooApiLogEntry[] }>("/settings/vendoo-api-logs"),
    clearVendooApiLogs: () => request<{ ok: boolean }>("/settings/vendoo-api-logs", { method: "DELETE" }),
  },

  extension: {
    status: () =>
      request<{
        connected: boolean;
        paired: boolean;
        version?: string | null;
        expected_version?: string | null;
        expected_build?: string | null;
        build?: string | null;
        up_to_date?: boolean;
        reload_pending?: boolean;
        files_in_sync?: boolean;
        version_mismatch?: boolean;
        load_path?: string | null;
      }>("/extension/status"),
    pairingToken: () => request<{ token: string }>("/extension/pairing-token"),
    reload: () => request<{ ok: boolean; sent: boolean }>("/extension/reload", { method: "POST" }),
  },

  desktop: {
    chrome: () =>
      request<{
        available: boolean;
        browser: string | null;
        extension_dir: string;
        profile?: string;
        profile_dir?: string;
      }>("/desktop/chrome"),
    connectChrome: () =>
      request<{
        ok: boolean;
        connected?: boolean;
        extension_reload?: boolean;
        via?: string;
      }>("/desktop/chrome/connect", { method: "POST" }),
  },

  updates: {
    status: () =>
      request<{
        available: boolean;
        packaged?: boolean;
        behind?: number;
        ahead?: number;
        branch?: string;
        local_sha?: string;
        remote_sha?: string;
        remote_ref?: string;
        summary?: string;
        commits?: string[];
        short_sha?: string;
        on_ref?: boolean;
        dirty?: string[];
        error?: string | null;
      }>("/updates"),
    progress: () =>
      request<{
        status: "idle" | "downloading" | "downloaded" | "installing" | "error";
        download_percent: number | null;
        sha: string | null;
        error: string | null;
      }>("/updates/progress"),
    download: () =>
      request<{ ok: boolean; updated: boolean; prepared?: boolean; sha?: string }>("/updates/download", {
        method: "POST",
      }),
    restart: () =>
      request<{ ok: boolean; updated: boolean; sha?: string; reloading?: boolean }>("/updates/restart", {
        method: "POST",
      }),
    apply: () =>
      request<{ ok: boolean; updated: boolean; sha?: string; reloading?: boolean }>("/updates/apply", {
        method: "POST",
      }),
  },

  changelog: () =>
    request<{
      version: string;
      entries: { version: string; date: string | null; body: string }[];
    }>("/changelog"),
};
