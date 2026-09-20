import type {
  Conversation,
  DeleteConversationResult,
  FillLogReport,
  Job,
  ListingData,
  ListingProviderId,
  ListingResponse,
  ListingRevision,
  ListingUpdateResult,
  ConversationActivity,
  Message,
  OkResponse,
  Photo,
  PhotoUploadResult,
  ProviderStatus,
  ProviderTestResult,
  ChatGPTPendingLogin,
  RevisionRestoreResult,
  ValidationResult,
  VendooBulkImport,
  VendooItemResult,
  MarketplaceForm,
} from "./types";

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
  catalog: {
    status: () => request<{running: boolean; complete: boolean; marketplaces: Record<string,
      {status: string; nodes: number; pending_branches: number; error: string | null}>}>("/catalog/sync"),
    sync: () => request<{started: boolean}>("/catalog/sync", {method: "POST"}),
    dropdownOptions: () =>
      request<{ forms: Record<string, Record<string, string[]>> }>("/catalog/dropdown-options"),
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
      request<{ ok: boolean; item_id: string; updated: string[] }>(
        `/conversations/${convId}/vendoo-api/save`, { method: "POST" },
      ),
    sync: (convId: string) =>
      request<{
        ok: boolean;
        action: "pull" | "conflict" | "none" | "unavailable";
        reason: string;
        item_id?: string;
        revision_id?: string;
      }>(
        `/conversations/${convId}/vendoo-api/sync`, { method: "POST" },
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
    list: () => request<Conversation[]>("/conversations"),
    get: (id: string) => request<Conversation>(`/conversations/${id}`),
    create: (body?: { title?: string; notes?: string }) =>
      request<Conversation>("/conversations", { method: "POST", body: JSON.stringify(body || {}) }),
    update: (id: string, body: { title?: string; notes?: string; status?: string }) =>
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
      request<Conversation>(`/conversations/${id}/reset`, {
        method: "POST",
        body: JSON.stringify({ keep_inputs: Boolean(opts?.keepInputs) }),
      }),
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
    restore: (convId: string, revisionId: string) =>
      request<RevisionRestoreResult>(`/conversations/${convId}/revisions/${revisionId}/restore`, { method: "POST" }),
  },

  jobs: {
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
    vendooItem: (id: string, opts?: { refresh?: boolean; cacheOnly?: boolean; resolvePhotos?: boolean }) => {
      const params = new URLSearchParams();
      if (opts?.refresh) params.set("refresh", "true");
      if (opts?.cacheOnly) params.set("cache_only", "true");
      if (opts?.resolvePhotos) params.set("resolve_photos", "true");
      const query = params.toString();
      return request<VendooItemResult>(`/jobs/${id}/vendoo-item${query ? `?${query}` : ""}`, { method: "POST" });
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
      request<{ ok: boolean; url: string; via: "extension" | "chrome" }>(`/jobs/${id}/open`, { method: "POST" }),
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
        error?: string | null;
      }>("/settings/cursor/models"),
    setCursorModels: (models: { vision_model?: string; listing_model?: string }) =>
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
    ui: () =>
      request<{
        ok: boolean;
        recent_vendoo_labels: string[];
        settled_shelf_expanded: boolean;
        hidden_vendoo_labels: string[];
      }>("/settings/ui"),
    setUi: (body: {
      recent_vendoo_labels?: string[];
      settled_shelf_expanded?: boolean;
      remember_labels?: string | string[];
      restore_labels?: string[];
      forget_label?: string;
    }) =>
      request<{
        ok: boolean;
        recent_vendoo_labels: string[];
        settled_shelf_expanded: boolean;
        hidden_vendoo_labels: string[];
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
    connectChrome: () => request<{ ok: boolean }>("/desktop/chrome/connect", { method: "POST" }),
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
    apply: () =>
      request<{ ok: boolean; updated: boolean; sha?: string; reloading?: boolean }>("/updates/apply", {
        method: "POST",
      }),
  },
};
