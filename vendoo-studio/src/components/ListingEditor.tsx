import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  convId: string;
}

export function ListingEditor({ convId }: Props) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState("general");
  const [jsonText, setJsonText] = React.useState("");

  const { data } = useQuery({
    queryKey: ["listing", convId],
    queryFn: () => api.listings.get(convId),
  });

  const updateMutation = useMutation({
    mutationFn: (listing: any) => api.listings.update(convId, listing),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
    },
  });

  React.useEffect(() => {
    if (data?.listing) {
      setJsonText(JSON.stringify(data.listing, null, 2));
    }
  }, [data?.listing]);

  const tabs = ["general", "ebay", "poshmark", "mercari", "depop", "etsy", "json"];

  const applyJsonEdit = () => {
    try {
      const parsed = JSON.parse(jsonText);
      updateMutation.mutate(parsed);
    } catch {
      alert("Invalid JSON");
    }
  };

  const listing = data?.listing || {};

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600 }}>Listing</h3>
        {data?.can_send && (
          <span style={{ fontSize: 11, color: "var(--color-success)", fontWeight: 600 }}>Ready</span>
        )}
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 12, flexWrap: "wrap" }}>
        {tabs.map((tab) => (
          <button
            key={tab}
            className={`btn btn-sm ${activeTab === tab ? "btn-primary" : "btn-secondary"}`}
            style={{ textTransform: "capitalize" }}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "json" ? (
        <div>
          <textarea
            className="input"
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            style={{ height: 400, fontFamily: "var(--font-mono)", fontSize: 12 }}
          />
          <button
            className="btn btn-primary btn-sm"
            style={{ marginTop: 8, width: "100%" }}
            onClick={applyJsonEdit}
          >
            Apply JSON
          </button>
        </div>
      ) : (
        <StructuredEditor listing={listing} tab={activeTab} onChange={(updated) => updateMutation.mutate(updated)} />
      )}

      <div style={{ marginTop: 16 }}>
        <SendToVendooButton convId={convId} canSend={data?.can_send ?? false} />
      </div>
    </div>
  );
}

function StructuredEditor({ listing, tab, onChange }: { listing: any; tab: string; onChange: (v: any) => void }) {
  const fields = getFieldsForTab(listing, tab);
  const [local, setLocal] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    const init: Record<string, string> = {};
    fields.forEach((f) => {
      const val = getNestedValue(listing, f.key);
      init[f.key] = val != null ? String(val) : "";
    });
    setLocal(init);
  }, [listing, tab]);

  const handleBlur = (key: string) => {
    if (local[key] == null) return;
    const updated = setNestedValue({ ...listing }, key, coerce(local[key]));
    onChange(updated);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {fields.map((f) => (
        <div key={f.key}>
          <label className="label">{f.label}</label>
          {f.key === "description" ? (
            <textarea
              className="input"
              style={{ height: 100 }}
              value={local[f.key] || ""}
              onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })}
              onBlur={() => handleBlur(f.key)}
            />
          ) : (
            <input
              className="input"
              type={f.type || "text"}
              value={local[f.key] || ""}
              onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })}
              onBlur={() => handleBlur(f.key)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function getFieldsForTab(listing: any, tab: string): { key: string; label: string; type?: string }[] {
  switch (tab) {
    case "general":
      return [
        { key: "title", label: "Title" },
        { key: "description", label: "Description" },
        { key: "price", label: "Price", type: "number" },
        { key: "cost", label: "Cost", type: "number" },
        { key: "quantity", label: "Quantity", type: "number" },
        { key: "brand", label: "Brand" },
        { key: "condition", label: "Condition" },
        { key: "primaryColor", label: "Primary Color" },
        { key: "size", label: "Size" },
        { key: "sizeType", label: "Size Type" },
        { key: "category_path", label: "Category" },
      ];
    case "ebay":
      return Object.keys(listing?.ebay_specifics || {}).map((k) => ({
        key: `ebay_specifics.${k}`,
        label: k,
      }));
    case "depop":
      return Object.keys(listing?.depop_specifics || {}).map((k) => ({
        key: `depop_specifics.${k}`,
        label: k,
      }));
    case "etsy":
      return Object.keys(listing?.etsy_specifics || {}).map((k) => ({
        key: `etsy_specifics.${k}`,
        label: k,
      }));
    default:
      return [];
  }
}

function getNestedValue(obj: any, path: string): any {
  return path.split(".").reduce((o, k) => (o ? o[k] : undefined), obj);
}

function setNestedValue(obj: any, path: string, value: any): any {
  const keys = path.split(".");
  const last = keys.pop()!;
  let target = obj;
  for (const k of keys) {
    if (!target[k]) target[k] = {};
    target = target[k];
  }
  target[last] = value;
  return obj;
}

function coerce(val: string): any {
  if (val === "") return null;
  if (!isNaN(Number(val)) && val.trim() !== "") return Number(val);
  return val;
}

import React from "react";

function SendToVendooButton({ convId, canSend }: { convId: string; canSend: boolean }) {
  const queryClient = useQueryClient();
  const [error, setError] = React.useState<string | null>(null);

  const { data: extStatus } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: 5000,
  });

  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs.list,
  });

  const sendMutation = useMutation({
    mutationFn: () => api.jobs.create(convId),
    onSuccess: (data) => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err: any) => {
      setError(err.message || "Failed to send");
    },
  });

  const retryMutation = useMutation({
    mutationFn: (jobId: string) => api.jobs.retry(jobId),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err: any) => {
      setError(err.message || "Failed to retry");
    },
  });

  const existingJob = jobs?.find((j: any) => j.conversation_id === convId && j.status !== "cancelled");
  const extensionConnected = extStatus?.connected ?? false;

  if (existingJob) {
    const isFailed = existingJob.status === "failed";
    const isDispatched = existingJob.status === "dispatched";
    const isCompleted = existingJob.status === "completed";
    const canRestart = isFailed || isDispatched || isCompleted;
    const buttonLabel = retryMutation.isPending ? "Restarting..." : isFailed ? "Retry" : isCompleted ? "Run Again" : "Restart Job";
    return (
      <div style={{ padding: "8px 12px", background: "var(--color-surface)", borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)" }}>
        <span style={{ fontSize: 12, color: isFailed ? "var(--color-error)" : "var(--color-text-secondary)" }}>
          Job {existingJob.status}: {existingJob.current_step || "queued"}
          {existingJob.last_error && <div style={{ marginTop: 4 }}>{existingJob.last_error}</div>}
        </span>
        {canRestart && (
          <button
            className="btn btn-primary"
            style={{ width: "100%", marginTop: 8, fontSize: 13 }}
            disabled={retryMutation.isPending}
            onClick={() => { setError(null); retryMutation.mutate(existingJob.id); }}
          >
            {buttonLabel}
          </button>
        )}
      </div>
    );
  }

  if (!extensionConnected) {
    return (
      <div style={{ fontSize: 12, color: "var(--color-text-muted)", textAlign: "center", padding: 8 }}>
        Extension not connected. Open the Vendoo Lister popup and pair with Studio first.
      </div>
    );
  }

  return (
    <div>
      <button
        className="btn btn-success"
        style={{ width: "100%" }}
        disabled={!canSend || sendMutation.isPending}
        onClick={() => { setError(null); sendMutation.mutate(); }}
      >
        {sendMutation.isPending ? "Sending..." : "Send to Vendoo"}
      </button>
      {error && (
        <div style={{ marginTop: 8, fontSize: 12, color: "var(--color-error)" }}>{error}</div>
      )}
    </div>
  );
}
