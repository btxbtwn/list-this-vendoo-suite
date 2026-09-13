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
  health: () => request<{ status: string; version: string }>("/health"),

  status: () =>
    request<{
      version: string;
      provider_configured: boolean;
      extension_connected: boolean;
      active_job_id: string | null;
      packaged?: boolean;
      chrome_available?: boolean;
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
    messages: (id: string) => request<any[]>(`/conversations/${id}/messages`),
    photos: (id: string) => request<any[]>(`/conversations/${id}/photos`),
    deletePhoto: (convId: string, photoId: string) =>
      request<any>(`/conversations/${convId}/photos/${photoId}`, { method: "DELETE" }),
    delete: (id: string) =>
      request<any>(`/conversations/${id}`, { method: "DELETE" }),
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
    create: (conversationId: string) =>
      request<any>("/jobs", { method: "POST", body: JSON.stringify({ conversation_id: conversationId }) }),
    list: () => request<any[]>("/jobs"),
    get: (id: string) => request<any>(`/jobs/${id}`),
    events: (id: string) => request<any[]>(`/jobs/${id}/events`),
    fillLog: (id: string) => request<any>(`/jobs/${id}/fill-log`),
    fillFields: (id: string, fields: { id?: string; marketplace?: string; field?: string; value?: string }[]) =>
      request<any>(`/jobs/${id}/fill-fields`, {
        method: "POST",
        body: JSON.stringify({ fields }),
      }),
    vendooItem: (id: string) =>
      request<any>(`/jobs/${id}/vendoo-item`, { method: "POST" }),
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
  },

  extension: {
    status: () => request<any>("/extension/status"),
    pairingToken: () => request<any>("/extension/pairing-token"),
  },

  desktop: {
    chrome: () =>
      request<{
        available: boolean;
        browser: string | null;
        extension_dir: string;
        profile_dir: string;
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
