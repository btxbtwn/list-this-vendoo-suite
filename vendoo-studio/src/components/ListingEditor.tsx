import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { FillLogPanel, FillLogSummary } from "./FillLogPanel";
import { ConnectChromeButton } from "./ConnectChromeButton";

interface Props {
  convId: string;
  onJobStarted?: () => void;
}

interface EditorField {
  key: string;
  label: string;
  type?: string;
  defaultValue?: string;
}

export function ListingEditor({ convId, onJobStarted }: Props) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState("general");
  const [jsonText, setJsonText] = React.useState("");

  const { data } = useQuery({
    queryKey: ["listing", convId],
    queryFn: () => api.listings.get(convId),
  });

  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs.list,
    refetchInterval: 2000,
  });
  const listingJob = jobs?.find((j: any) => j.conversation_id === convId && j.status !== "cancelled");

  const updateMutation = useMutation({
    mutationFn: (listing: any) => api.listings.update(convId, listing),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["listing", convId] }),
  });

  React.useEffect(() => {
    if (data?.listing) setJsonText(JSON.stringify(data.listing, null, 2));
  }, [data?.listing]);

  const tabs = ["general", "ebay", "poshmark", "mercari", "depop", "etsy", "json", "log"];

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
    <div className="listing-editor">
      <div className="editor-header pywebview-drag-region">
        <span className="editor-title">Listing</span>
        {data?.can_send && <span className="editor-ready">Ready</span>}
      </div>

      <div className="tab-group">
        {tabs.map((tab) => (
          <button key={tab} className={`tab-btn${activeTab === tab ? " active" : ""}`} onClick={() => setActiveTab(tab)}>
            {tab === "json" ? "JSON" : tab === "log" ? "Fill log" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      <div className="editor-body">
        {activeTab === "log" ? (
          listingJob ? (
            <FillLogPanel
              jobId={listingJob.id}
              jobStatus={listingJob.status}
              jobStep={listingJob.current_step}
              vendooItemId={listingJob.vendoo_item_id}
              vendooUrl={listingJob.vendoo_url}
              onFilled={() => queryClient.invalidateQueries({ queryKey: ["listing", convId] })}
              onJobStarted={onJobStarted}
            />
          ) : (
            <p className="text-xs text-muted">No fill log yet. Send this listing to Vendoo to record what gets filled, skipped, or newly seen.</p>
          )
        ) : activeTab === "json" ? (
          <div>
            <textarea
              className="input"
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              style={{ height: 340, fontFamily: "var(--font-mono)", fontSize: 11.5 }}
            />
            <button className="btn btn-primary btn-sm" style={{ marginTop: 8, width: "100%" }} onClick={applyJsonEdit}>
              Apply JSON
            </button>
          </div>
        ) : (
          <StructuredEditor listing={listing} tab={activeTab} onChange={(updated) => updateMutation.mutate(updated)} />
        )}
      </div>

      <div className="editor-footer">
        <SendToVendooButton
          convId={convId}
          canSend={data?.can_send ?? false}
          sendBlockers={data?.errors || []}
          onJobStarted={onJobStarted}
          onOpenFillLog={() => setActiveTab("log")}
        />
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
      init[f.key] = val != null ? String(val) : f.defaultValue || "";
    });
    setLocal(init);
  }, [listing, tab]);

  const handleBlur = (key: string) => {
    if (local[key] == null) return;
    const updated = setNestedValue({ ...listing }, key, coerce(local[key]));
    onChange(updated);
  };

  const generalFields = fields.filter((f) => ["title", "description", "category_path"].includes(f.key));
  const gridFields = fields.filter((f) => !["title", "description", "category_path"].includes(f.key));

  return (
    <div>
      {generalFields.map((f) => (
        <div key={f.key} className="field-row">
          <label className="label">{f.label}</label>
          {f.key === "description" ? (
            <textarea className="input" style={{ height: 100 }} value={local[f.key] || ""} onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })} onBlur={() => handleBlur(f.key)} />
          ) : (
            <input className="input" type={f.type || "text"} value={local[f.key] || ""} onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })} onBlur={() => handleBlur(f.key)} />
          )}
        </div>
      ))}

      <div className="field-grid">
        {gridFields.map((f) => (
          <div key={f.key} className={f.label === "Category" ? "field-row field-full" : "field-row"}>
            <label className="label">{f.label}</label>
            <input className="input" type={f.type || "text"} value={local[f.key] || ""} onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })} onBlur={() => handleBlur(f.key)} />
          </div>
        ))}
      </div>
    </div>
  );
}

function getFieldsForTab(listing: any, tab: string): EditorField[] {
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
        { key: "secondaryColor", label: "Secondary Color" },
        { key: "size", label: "Size" },
        { key: "sku", label: "SKU" },
        { key: "category_path", label: "Category" },
      ];
    case "ebay":
      return specificsFields(listing?.ebay_specifics, "ebay_specifics");
    case "poshmark":
      return [
        { key: "price", label: "Price", type: "number" },
        { key: "poshmark_specifics.originalPrice", label: "Original Price", type: "number", defaultValue: "0" },
        { key: "condition", label: "Condition" },
        { key: "brand", label: "Brand" },
        { key: "primaryColor", label: "Primary Color" },
        { key: "quantity", label: "Quantity", type: "number" },
        ...specificsFields(listing?.poshmark_specifics, "poshmark_specifics", ["originalPrice"]),
      ];
    case "mercari":
      return [
        { key: "price", label: "Price", type: "number" },
        { key: "condition", label: "Condition" },
        { key: "brand", label: "Brand" },
        { key: "quantity", label: "Quantity", type: "number" },
        { key: "mercari_specifics.shippingLabel", label: "Shipping Label", defaultValue: "USPS Ground Advantage" },
        ...specificsFields(listing?.mercari_specifics, "mercari_specifics", ["shippingLabel"]),
      ];
    case "depop":
      return specificsFields(listing?.depop_specifics, "depop_specifics");
    case "etsy":
      return specificsFields(listing?.etsy_specifics, "etsy_specifics");
    default:
      return [];
  }
}

function specificsFields(specs: Record<string, any> | undefined, prefix: string, skip: string[] = []): EditorField[] {
  if (!specs || typeof specs !== "object") return [];
  const fields: EditorField[] = [];
  for (const [key, value] of Object.entries(specs)) {
    if (skip.includes(key)) continue;
    if (key === "category_specifics" && value && typeof value === "object" && !Array.isArray(value)) {
      for (const nested of Object.keys(value)) {
        fields.push({ key: `${prefix}.category_specifics.${nested}`, label: nested });
      }
      continue;
    }
    fields.push({ key: `${prefix}.${key}`, label: key });
  }
  return fields;
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

function SendToVendooButton({
  convId,
  canSend,
  sendBlockers,
  onJobStarted,
  onOpenFillLog,
}: {
  convId: string;
  canSend: boolean;
  sendBlockers: { field?: string; message?: string }[];
  onJobStarted?: () => void;
  onOpenFillLog?: () => void;
}) {
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
    refetchInterval: 2000,
  });

  const rememberJob = (job: any) => {
    if (!job?.id) return;
    queryClient.setQueryData(["jobs"], (old: any[] | undefined) => {
      const rest = (old || []).filter((item) => item.id !== job.id);
      return [job, ...rest];
    });
  };

  const sendMutation = useMutation({
    mutationFn: () => api.jobs.create(convId),
    onSuccess: (job) => {
      setError(null);
      rememberJob(job);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["fill-log"] });
      onJobStarted?.();
    },
    onError: (err: any) => setError(err.message || "Failed to send"),
  });

  const retryMutation = useMutation({
    mutationFn: (jobId: string) => api.jobs.retry(jobId),
    onSuccess: (job) => {
      setError(null);
      rememberJob(job);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["fill-log"] });
      onJobStarted?.();
    },
    onError: (err: any) => setError(err.message || "Failed to retry"),
  });

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => api.jobs.cancel(jobId),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err: any) => setError(err.message || "Failed to cancel"),
  });

  const existingJob = jobs?.find((j: any) => j.conversation_id === convId && j.status !== "cancelled");
  const extensionConnected = extStatus?.connected ?? false;
  const blockerText = sendBlockers
    .map((err) => err.message)
    .filter(Boolean)
    .join(" · ");

  if (existingJob) {
    const isFailed = existingJob.status === "failed";
    const isDispatched = existingJob.status === "dispatched";
    const isCompleted = existingJob.status === "completed";
    const isQueued = existingJob.status === "queued" || existingJob.status === "awaiting_extension";
    const leftoverFilling = isDispatched && existingJob.current_step === "filling_fields";
    const canRestart = (isFailed || isDispatched || isCompleted || isQueued) && !leftoverFilling;
    const canCancel = !isCompleted;
    const buttonLabel = retryMutation.isPending
      ? "Sending..."
      : isFailed
        ? "Retry"
        : isCompleted || isQueued
          ? "Send to Vendoo"
          : "Restart Job";
    return (
      <div className={`job-card${isFailed ? " job-card-error" : ""}`}>
        <div className="job-card-copy">
          <div className="job-card-label">Job Status</div>
          <div className={`job-card-status${isFailed ? " error" : ""}`}>
            {existingJob.status}: {existingJob.current_step || "queued"}
            {existingJob.last_error && <div className="mt-4 text-xs text-error">{existingJob.last_error}</div>}
          </div>
          <FillLogSummary jobId={existingJob.id} onOpenFillLog={onOpenFillLog} />
        </div>
        <div className="job-card-actions">
          {canRestart && (
            <button
              type="button"
              className="btn btn-primary btn-sm job-card-action"
              disabled={retryMutation.isPending || cancelMutation.isPending}
              onClick={() => { setError(null); retryMutation.mutate(existingJob.id); }}
            >
              {buttonLabel}
            </button>
          )}
          {canCancel && (
            <button
              type="button"
              className="btn btn-secondary btn-sm job-card-action"
              disabled={cancelMutation.isPending}
              onClick={() => { setError(null); cancelMutation.mutate(existingJob.id); }}
            >
              {cancelMutation.isPending ? "Cancelling..." : "Cancel"}
            </button>
          )}
        </div>
        {error && <div className="job-card-error-text">{error}</div>}
      </div>
    );
  }

  if (!extensionConnected) {
    return (
      <div style={{ display: "grid", gap: 8, justifyItems: "center", textAlign: "center" }}>
        <div className="text-xs text-muted">Chrome is not connected yet.</div>
        <ConnectChromeButton />
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        className="btn btn-success"
        style={{ width: "100%" }}
        disabled={sendMutation.isPending}
        onClick={() => {
          if (!canSend) {
            setError(blockerText || "Listing is not ready. Add a title, description, price, and at least one photo.");
            return;
          }
          setError(null);
          sendMutation.mutate();
        }}
      >
        {sendMutation.isPending ? "Sending..." : "Send to Vendoo"}
      </button>
      {(error || (!canSend && blockerText)) && (
        <div className="mt-8 text-xs text-error">{error || blockerText}</div>
      )}
    </div>
  );
}
