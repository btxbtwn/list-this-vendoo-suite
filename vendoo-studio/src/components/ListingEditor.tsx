import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { FillLogPanel } from "./FillLogPanel";
import { ConnectChromeButton } from "./ConnectChromeButton";
import { OpenListingButton } from "./OpenListingButton";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";

interface Props {
  convId: string;
  onJobStarted?: () => void;
  onAskChat?: (text: string) => void;
}

interface EditorField {
  key: string;
  label: string;
  type?: string;
  defaultValue?: string;
}

export function ListingEditor({ convId, onJobStarted, onAskChat }: Props) {
  const queryClient = useQueryClient();
  const [reviewTab, setReviewTab] = React.useState<"forms" | "fields">("forms");
  const [editTab, setEditTab] = React.useState("general");
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
  const { data: marketplaceSettings } = useQuery({
    queryKey: ["settings-marketplaces"],
    queryFn: api.settings.marketplaces,
  });
  const { data: conversation } = useQuery({
    queryKey: ["conversation", convId],
    queryFn: () => api.conversations.get(convId),
  });
  const listingJob = jobs?.find((j: any) => j.conversation_id === convId && j.status !== "cancelled");

  const updateMutation = useMutation({
    mutationFn: (listing: any) => api.listings.update(convId, listing),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["listing", convId] }),
  });

  React.useEffect(() => {
    if (data?.listing) setJsonText(JSON.stringify(data.listing, null, 2));
  }, [data?.listing]);

  const tabs = React.useMemo(() => {
    const selected = new Set(marketplaceSettings?.selected ?? ["ebay", "etsy", "poshmark", "mercari", "depop"]);
    return ["general", ...["ebay", "poshmark", "mercari", "depop", "etsy"].filter((id) => selected.has(id)), "json"];
  }, [marketplaceSettings?.selected]);

  React.useEffect(() => {
    if (!tabs.includes(editTab)) setEditTab("general");
  }, [editTab, tabs]);

  const applyJsonEdit = () => {
    try {
      const parsed = JSON.parse(jsonText);
      updateMutation.mutate(parsed);
    } catch {
      alert("Invalid JSON");
    }
  };

  const listing = data?.listing || {};
  const listingTitle = String(listing.title || "Listing");
  const importedItemId = listingJob?.vendoo_item_id || notesVendooItemId(conversation?.notes);

  return (
    <div className="listing-editor">
      <div className="pr-review-header">
        <div className="pr-review-title-row">
          <h2 className="pr-review-title pywebview-drag-region" title={listingTitle}>{listingTitle}</h2>
          {data?.can_send && <span className="editor-ready">Ready</span>}
          {listingJob && (
            <OpenListingButton
              jobId={listingJob.id}
              vendooItemId={listingJob.vendoo_item_id || importedItemId}
              vendooUrl={listingJob.vendoo_url}
              className="pr-review-open"
            />
          )}
        </div>
        <div className="pr-review-meta pywebview-drag-region">
          {importedItemId
            ? <span className="pr-review-branch">vendoo ← {String(importedItemId).slice(0, 8)}</span>
            : <span className="pr-review-branch">Draft</span>}
        </div>
        <div className="pr-pills" role="tablist" aria-label="Listing review">
          {(["forms", "fields"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={reviewTab === tab}
              className={`pr-pill${reviewTab === tab ? " is-active" : ""}`}
              onClick={() => setReviewTab(tab)}
            >
              {tab === "forms" ? "Forms" : "Fields"}
            </button>
          ))}
        </div>
      </div>

      <div className={`editor-body${reviewTab === "fields" ? " is-files" : ""}`}>
        {reviewTab === "fields" ? (
          listingJob ? (
            <FillLogPanel
              jobId={listingJob.id}
              jobStatus={listingJob.status}
              jobStep={listingJob.current_step}
              vendooItemId={listingJob.vendoo_item_id}
              vendooUrl={listingJob.vendoo_url}
              listing={listing}
              onAskChat={onAskChat}
              onFilled={() => queryClient.invalidateQueries({ queryKey: ["listing", convId] })}
              onJobStarted={onJobStarted}
            />
          ) : (
            <p className="pr-empty">Send this listing to Vendoo, then open Fields to review each marketplace and fill empty fields.</p>
          )
        ) : (
          <>
            <div className="tab-group">
              {tabs.map((tab) => (
                <button key={tab} className={`tab-btn${editTab === tab ? " active" : ""}`} onClick={() => setEditTab(tab)}>
                  {tab === "json" ? "JSON" : tab.charAt(0).toUpperCase() + tab.slice(1)}
                </button>
              ))}
            </div>
            {editTab === "json" ? (
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
              <StructuredEditor
                listing={listing}
                tab={editTab}
                jobId={listingJob?.id}
                jobBusy={listingJob?.status === "dispatched" && listingJob?.current_step === "filling_fields"}
                onChange={(updated) => updateMutation.mutate(updated)}
                onCategoryMatched={() => queryClient.invalidateQueries({ queryKey: ["listing", convId] })}
              />
            )}
          </>
        )}
      </div>

      <div className="editor-footer">
        <SendToVendooButton
          convId={convId}
          canSend={data?.can_send ?? false}
          sendBlockers={data?.errors || []}
          vendooItemId={importedItemId}
          onJobStarted={onJobStarted}
        />
      </div>
    </div>
  );
}

function StructuredEditor({
  listing,
  tab,
  jobId,
  jobBusy,
  onChange,
  onCategoryMatched,
}: {
  listing: any;
  tab: string;
  jobId?: string;
  jobBusy?: boolean;
  onChange: (v: any) => void;
  onCategoryMatched?: () => void;
}) {
  const queryClient = useQueryClient();
  const fields = getFieldsForTab(listing, tab);
  const [local, setLocal] = React.useState<Record<string, string>>({});
  const { data: extStatus } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: 5000,
  });

  const resolveCategory = useMutation({
    mutationFn: () => api.jobs.resolveCategory(jobId || "", local.category_path || listing.category_path),
    onSuccess: (result) => {
      if (result.path) {
        setLocal((current) => ({ ...current, category_path: result.path || "" }));
        addToast({ type: "success", title: "Matched Vendoo category", description: result.path });
      }
      queryClient.invalidateQueries({ queryKey: ["listing"] });
      queryClient.invalidateQueries({ queryKey: ["conversation"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      onCategoryMatched?.();
    },
    onError: (err: any) => {
      addToast({ type: "error", title: "Could not match category", description: err.message || "Vendoo picker search failed" });
    },
  });

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
    const updated = cloneListing(listing);
    for (const field of fields) {
      if (local[field.key] == null) continue;
      setNestedValue(updated, field.key, coerce(local[field.key]));
    }
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
            <>
              <input className="input" type={f.type || "text"} value={local[f.key] || ""} onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })} onBlur={() => handleBlur(f.key)} />
              {f.key === "category_path" && jobId ? (
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ marginTop: 6 }}
                  disabled={!extStatus?.connected || jobBusy || resolveCategory.isPending}
                  title={!extStatus?.connected ? "Connect Chrome to search the Vendoo category picker" : "Search the live Vendoo category picker"}
                  onClick={() => resolveCategory.mutate()}
                >
                  {resolveCategory.isPending ? "Matching on Vendoo…" : "Match on Vendoo"}
                </button>
              ) : null}
            </>
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

function cloneListing(listing: any): any {
  try {
    return JSON.parse(JSON.stringify(listing || {}));
  } catch {
    return { ...(listing || {}) };
  }
}

function setNestedValue(obj: any, path: string, value: any): any {
  const keys = path.split(".");
  const last = keys.pop()!;
  let target = obj;
  for (const k of keys) {
    if (!target[k] || typeof target[k] !== "object") target[k] = {};
    target = target[k];
  }
  target[last] = value;
  return obj;
}

function notesVendooItemId(notes?: string | null): string | null {
  if (!notes) return null;
  try {
    const parsed = JSON.parse(notes);
    const itemId = String(parsed?.vendooItemId || "").trim();
    return itemId || null;
  } catch {
    return null;
  }
}

function coerce(val: string): any {
  if (val === "") return null;
  if (!isNaN(Number(val)) && val.trim() !== "") return Number(val);
  return val;
}

function SendToVendooButton({
  convId,
  canSend,
  sendBlockers,
  vendooItemId,
  onJobStarted,
}: {
  convId: string;
  canSend: boolean;
  sendBlockers: { field?: string; message?: string }[];
  vendooItemId?: string | null;
  onJobStarted?: () => void;
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
  const overwriteItemId = vendooItemId || existingJob?.vendoo_item_id || null;
  const sendLabel = overwriteItemId ? "Update Vendoo listing" : "Send to Vendoo";
  const blockerText = sendBlockers
    .map((err) => err.message)
    .filter(Boolean)
    .join(" · ");

  const confirmOverwriteIfNeeded = async () => {
    if (!overwriteItemId) return true;
    return confirmDialog(
      "Overwrite this existing Vendoo listing?\nThis does not publish. If it is already live, saving may update those marketplace listings.",
    );
  };

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
          ? sendLabel
          : "Restart Job";
    return (
      <div className={`job-card${isFailed ? " job-card-error" : ""}`}>
        <div className="job-card-copy">
          <div className="job-card-label">Job Status</div>
          <div className={`job-card-status${isFailed ? " error" : ""}`}>
            {existingJob.status}: {existingJob.current_step || "queued"}
            {existingJob.last_error && <div className="mt-4 text-xs text-error">{existingJob.last_error}</div>}
          </div>
        </div>
        <div className="job-card-actions">
          {canRestart && (
            <button
              type="button"
              className="btn btn-primary btn-sm job-card-action"
              disabled={retryMutation.isPending || cancelMutation.isPending}
              onClick={async () => {
                if (!(await confirmOverwriteIfNeeded())) return;
                setError(null);
                retryMutation.mutate(existingJob.id);
              }}
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
        onClick={async () => {
          if (!canSend) {
            setError(blockerText || "Listing is not ready. Add a title, description, price, and at least one photo.");
            return;
          }
          if (!(await confirmOverwriteIfNeeded())) return;
          setError(null);
          sendMutation.mutate();
        }}
      >
        {sendMutation.isPending ? "Sending..." : sendLabel}
      </button>
      {(error || (!canSend && blockerText)) && (
        <div className="mt-8 text-xs text-error">{error || blockerText}</div>
      )}
    </div>
  );
}
