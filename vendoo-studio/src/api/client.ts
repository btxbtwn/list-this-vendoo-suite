const BASE = "/api";

function errorMessage(body: any, fallback: string): string {
  const detail = body?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => item?.msg || item?.message || (typeof item === "string" ? item : ""))
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string" && detail.message.trim()) return detail.message;
    if (Array.isArray(detail.errors)) {
      const messages = detail.errors.map((item: any) => item?.message || item?.msg).filter(Boolean);
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

export const api = {
  catalog: {
    status: () => request<{running: boolean; complete: boolean; marketplaces: Record<string,
      {status: string; nodes: number; pending_branches: number; error: string | null}>}>("/catalog/sync"),
    sync: () => request<{started: boolean}>("/catalog/sync", {method: "POST"}),
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
    }>("/status"),

  conversations: {
    list: () => request<any[]>("/conversations"),
    get: (id: string) => request<any>(`/conversations/${id}`),
    create: (body?: { title?: string; notes?: string }) =>
      request<any>("/conversations", { method: "POST", body: JSON.stringify(body || {}) }),
    update: (id: string, body: { notes?: string }) =>
      request<any>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    settle: (id: string) =>
      request<any>(`/conversations/${id}/settle`, { method: "POST" }),
    unsettle: (id: string) =>
      request<any>(`/conversations/${id}/unsettle`, { method: "POST" }),
    cancelMessages: (id: string) =>
      request<{ ok: boolean }>(`/conversations/${id}/messages/cancel`, { method: "POST" }),
    messages: (id: string) => request<any[]>(`/conversations/${id}/messages`),
    photos: (id: string) => request<any[]>(`/conversations/${id}/photos`),
    deletePhoto: (convId: string, photoId: string) =>
      request<any>(`/conversations/${convId}/photos/${photoId}`, { method: "DELETE" }),
    delete: (id: string) =>
      request<any>(`/conversations/${id}`, { method: "DELETE" }),
    reset: (id: string) =>
      request<any>(`/conversations/${id}/reset`, { method: "POST" }),
    reorderPhotos: (convId: string, orderedIds: string[]) =>
      request<any>(`/conversations/${convId}/photos/order`, {
        method: "PATCH",
        body: JSON.stringify(orderedIds),
      }),
    uploadPhotos: (convId: string, files: File[]) => {
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

  listings: {
    get: (convId: string) => request<any>(`/conversations/${convId}/listing`),
    update: (convId: string, listing: any) =>
      request<any>(`/conversations/${convId}/listing`, {
        method: "PUT",
        body: JSON.stringify({ listing }),
      }),
    validate: (convId: string) =>
      request<any>(`/conversations/${convId}/listing/validate`, { method: "POST" }),
    revisions: (convId: string) => request<any[]>(`/conversations/${convId}/revisions`),
    restore: (convId: string, revisionId: string) =>
      request<any>(`/conversations/${convId}/revisions/${revisionId}/restore`, { method: "POST" }),
  },

  jobs: {
    create: (conversationId: string, opts?: { confirmOverwrite?: boolean }) =>
      request<any>("/jobs", {
        method: "POST",
        body: JSON.stringify({
          conversation_id: conversationId,
          confirm_overwrite: Boolean(opts?.confirmOverwrite),
        }),
      }),
    list: (conversationId?: string) => {
      const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : "";
      return request<any[]>(`/jobs${query}`);
    },
    ensureDraft: (conversationId: string) =>
      request<any>("/jobs/ensure-draft", {
        method: "POST",
        body: JSON.stringify({ conversation_id: conversationId }),
      }),
    get: (id: string) => request<any>(`/jobs/${id}`),
    fillLog: (id: string) => request<any>(`/jobs/${id}/fill-log`),
    fillFields: (id: string, fields: { id?: string; marketplace?: string; field?: string; value?: string }[]) =>
      request<any>(`/jobs/${id}/fill-fields`, {
        method: "POST",
        body: JSON.stringify({ fields }),
      }),
    vendooItem: (id: string, opts?: { refresh?: boolean; cacheOnly?: boolean }) => {
      const params = new URLSearchParams();
      if (opts?.refresh) params.set("refresh", "true");
      if (opts?.cacheOnly) params.set("cache_only", "true");
      const query = params.toString();
      return request<any>(`/jobs/${id}/vendoo-item${query ? `?${query}` : ""}`, { method: "POST" });
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
    retry: (id: string) => request<any>(`/jobs/${id}/retry`, { method: "POST" }),
    cancel: (id: string) => request<any>(`/jobs/${id}/cancel`, { method: "POST" }),
  },

  settings: {
    provider: () => request<any>("/settings/provider"),
    setProvider: (apiKey: string) =>
      request<any>("/settings/provider", {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      }),
    deleteKey: () => request<any>("/settings/provider/key", { method: "DELETE" }),
    testConnection: () => request<any>("/settings/provider/test", { method: "POST" }),
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
    chatgptLogin: () => request<any>("/settings/chatgpt/login", { method: "POST" }),
    chatgptCancelLogin: () => request<any>("/settings/chatgpt/login", { method: "DELETE" }),
    chatgptLogout: () => request<any>("/settings/chatgpt", { method: "DELETE" }),
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
    pairingToken: () => request<any>("/extension/pairing-token"),
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
