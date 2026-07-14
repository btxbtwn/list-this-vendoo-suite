const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || body.message || `Request failed: ${res.status}`);
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
    }>("/status"),

  conversations: {
    list: () => request<any[]>("/conversations"),
    get: (id: string) => request<any>(`/conversations/${id}`),
    create: (body?: { title?: string; notes?: string }) =>
      request<any>("/conversations", { method: "POST", body: JSON.stringify(body || {}) }),
    update: (id: string, body: { notes?: string }) =>
      request<any>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
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
  },

  extension: {
    status: () => request<any>("/extension/status"),
    pairingToken: () => request<any>("/extension/pairing-token"),
  },
};
