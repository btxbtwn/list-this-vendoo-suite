import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { FillLogPanel } from "./FillLogPanel";
import { ConnectChromeButton } from "./ConnectChromeButton";
import { OpenListingButton } from "./OpenListingButton";
import {
  DEPOP_CATEGORY_OPTIONALS,
  EBAY_CATEGORY_OPTIONALS,
  ETSY_CATEGORY_OPTIONALS,
} from "../marketplaceFields";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";
import { ClearListingButton } from "./ClearListingButton";
import { fetchVendooItemLive } from "../api/vendooItemQuery";
import {
  CopyableLlmError,
  completionBlockerPrompt,
  jobErrorPrompt,
  validationErrorsPrompt,
} from "./CopyableLlmError";

interface Props {
  convId: string;
  onJobStarted?: () => void;
  onAskChat?: (text: string) => void;
  onCleared?: () => void;
}

interface EditorField {
  key: string;
  label: string;
  type?: string;
  defaultValue?: string;
}

export function ListingEditor({ convId, onJobStarted, onAskChat, onCleared }: Props) {
  const queryClient = useQueryClient();
  const [reviewTab, setReviewTab] = React.useState<"forms" | "fields">("forms");
  const [editTab, setEditTab] = React.useState("general");
  const [jsonText, setJsonText] = React.useState("");

  const { data: jobs, isLoading: jobsLoading, isFetching: jobsFetching } = useQuery({
    queryKey: ["jobs", convId],
    queryFn: () => api.jobs.list(convId),
    refetchInterval: 2000,
  });
  const listingJob = jobs?.find((j: any) => j.conversation_id === convId && j.status !== "cancelled");
  const schemaProbeActive = Boolean(
    listingJob?.mode === "schema_probe"
    && ["queued", "awaiting_extension", "dispatched"].includes(String(listingJob?.status || "")),
  );
  const [ensureError, setEnsureError] = React.useState<string | null>(null);
  const ensureDraftMutation = useMutation({
    mutationFn: async () => {
      const job = await api.jobs.ensureDraft(convId);
      // Live read stays inside the mutation so Refresh stays pending until Chrome finishes.
      const fresh = await fetchVendooItemLive(queryClient, job.id, { force: true });
      return { job, fresh };
    },
    onSuccess: ({ job, fresh }) => {
      setEnsureError(null);
      queryClient.setQueryData(["jobs", convId], (old: any[] | undefined) => {
        const rest = (old || []).filter((item) => item.id !== job.id);
        return [job, ...rest];
      });
      queryClient.invalidateQueries({ queryKey: ["jobs", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      queryClient.invalidateQueries({ queryKey: ["fill-log"] });
      if (fresh?.error || fresh?.api_error) {
        addToast({
          type: "error",
          title: "Could not fully refresh Vendoo draft",
          description: String(fresh.error || fresh.api_error),
        });
      }
    },
    onError: (err: Error) => {
      setEnsureError(err.message || "Could not load the Vendoo draft fields.");
      addToast({
        type: "error",
        title: "Could not refresh fields",
        description: err.message || "Could not attach this listing to its Vendoo draft.",
      });
    },
  });

  const { data } = useQuery({
    queryKey: ["listing", convId],
    queryFn: () => api.listings.get(convId),
    refetchInterval: schemaProbeActive ? 3000 : false,
  });

  const { data: marketplaceSettings } = useQuery({
    queryKey: ["settings-marketplaces"],
    queryFn: api.settings.marketplaces,
  });
  const { data: conversation } = useQuery({
    queryKey: ["conversation", convId],
    queryFn: () => api.conversations.get(convId),
  });

  const updateMutation = useMutation({
    mutationFn: (listing: any) => api.listings.update(convId, listing),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["listing", convId] }),
  });

  React.useEffect(() => {
    if (data?.listing) setJsonText(JSON.stringify(data.listing, null, 2));
  }, [data?.listing, data?.current_revision_id]);

  React.useEffect(() => {
    if (listingJob?.mode === "schema_probe" && listingJob.status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      queryClient.invalidateQueries({ queryKey: ["fill-log"] });
      queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
    }
  }, [listingJob?.mode, listingJob?.status, listingJob?.id, convId, queryClient]);

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
  const importedUrl = listingJob?.vendoo_url || notesVendooUrl(conversation?.notes);

  React.useEffect(() => {
    if (importedItemId && listingJob?.status === "imported") {
      setReviewTab("fields");
    }
  }, [importedItemId, listingJob?.status, listingJob?.id]);

  const ensureAttemptKey = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (jobsLoading || listingJob || !importedItemId) return;
    const key = `${convId}:${importedItemId}`;
    if (ensureAttemptKey.current === key) return;
    ensureAttemptKey.current = key;
    ensureDraftMutation.mutate();
    // Refresh fields clears ensureAttemptKey before calling mutate again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobsLoading, listingJob?.id, importedItemId, convId]);

  return (
    <div className="listing-editor">
      <div className="pr-review-header">
        <div className="pr-review-title-row">
          <h2 className="pr-review-title pywebview-drag-region" title={listingTitle}>{listingTitle}</h2>
          {data?.can_send && <span className="editor-ready">Ready</span>}
          <div className="pr-review-actions">
            {listingJob && (
              <OpenListingButton
                jobId={listingJob.id}
                vendooItemId={listingJob.vendoo_item_id || importedItemId}
                vendooUrl={listingJob.vendoo_url || importedUrl}
                className="pr-review-open"
              />
            )}
            <ClearListingButton convId={convId} className="pr-review-clear" onCleared={onCleared} />
          </div>
        </div>
        <div className="pr-review-meta">
          <VendooLinkControl
            convId={convId}
            itemId={importedItemId}
            url={importedUrl}
            onLinked={() => {
              ensureAttemptKey.current = null;
              queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
              queryClient.invalidateQueries({ queryKey: ["conversations"] });
              queryClient.invalidateQueries({ queryKey: ["jobs", convId] });
              ensureDraftMutation.mutate();
            }}
          />
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

      {schemaProbeActive && (
        <div className="pr-notice" role="status">
          Discovering Vendoo marketplace fields for this category… Empty keys will appear on Forms as they arrive.
        </div>
      )}

      <div className={`editor-body${reviewTab === "fields" ? " is-files" : ""}`}>
        {reviewTab === "fields" ? (
          listingJob ? (
            <FillLogPanel
              jobId={listingJob.id}
              conversationId={convId}
              jobStatus={listingJob.status}
              jobStep={listingJob.current_step}
              vendooItemId={listingJob.vendoo_item_id || importedItemId}
              vendooUrl={listingJob.vendoo_url || importedUrl}
              listing={listing}
              onAskChat={onAskChat}
              onFilled={() => queryClient.invalidateQueries({ queryKey: ["listing", convId] })}
              onJobStarted={onJobStarted}
            />
          ) : (
            <div className="pr-empty">
              <p>
                {jobsLoading || ensureDraftMutation.isPending
                  ? "Loading fields…"
                  : importedItemId
                    ? "This listing already has a Vendoo draft, but its job isn’t loaded yet. Refresh attaches the draft and reads live fields from Vendoo (Chrome must be connected)."
                    : "Send this listing to Vendoo, then open Fields to review each marketplace and apply missing values."}
              </p>
              {ensureError && <p className="text-xs text-error" style={{ marginTop: 8 }}>{ensureError}</p>}
              {importedItemId && !jobsLoading && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  style={{ marginTop: 12 }}
                  disabled={jobsFetching || ensureDraftMutation.isPending}
                  onClick={() => {
                    setEnsureError(null);
                    ensureAttemptKey.current = null;
                    ensureDraftMutation.reset();
                    ensureDraftMutation.mutate();
                  }}
                >
                  {ensureDraftMutation.isPending || jobsFetching ? "Refreshing…" : "Refresh fields"}
                </button>
              )}
            </div>
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
                revisionId={data?.current_revision_id}
                tab={editTab}
                jobId={listingJob?.id}
                jobBusy={listingJob?.status === "dispatched"}
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
          listingTitle={listingTitle}
          vendooItemId={importedItemId}
          onJobStarted={onJobStarted}
          onAskChat={onAskChat}
        />
      </div>
    </div>
  );
}

function StructuredEditor({
  listing,
  revisionId,
  tab,
  jobId,
  jobBusy,
  onChange,
  onCategoryMatched,
}: {
  listing: any;
  revisionId?: string | null;
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
  }, [listing, revisionId, tab]);

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
      return mergeSpecificsWithDefaults(listing?.ebay_specifics, "ebay_specifics", [
        { key: "ebay_specifics.department", label: "Department" },
        { key: "ebay_specifics.size", label: "Size" },
        { key: "ebay_specifics.sizeType", label: "Size Type" },
        { key: "ebay_specifics.type", label: "Type" },
        { key: "ebay_specifics.conditionDescription", label: "Condition Description" },
        ...EBAY_CATEGORY_OPTIONALS.map((field) => ({
          key: `ebay_specifics.category_specifics.${field.key}`,
          label: field.label,
        })),
      ]);
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
      return mergeSpecificsWithDefaults(
        listing?.depop_specifics,
        "depop_specifics",
        DEPOP_CATEGORY_OPTIONALS.map((field) => ({
          key: `depop_specifics.${field.key}`,
          label: field.label,
        })),
      );
    case "etsy":
      return mergeSpecificsWithDefaults(
        listing?.etsy_specifics,
        "etsy_specifics",
        ETSY_CATEGORY_OPTIONALS.map((field) => ({
          key: `etsy_specifics.category_specifics.${field.key}`,
          label: field.label,
        })),
      );
    default:
      return [];
  }
}

function mergeSpecificsWithDefaults(
  specs: Record<string, any> | undefined,
  prefix: string,
  defaults: EditorField[],
): EditorField[] {
  const existing = specificsFields(specs, prefix);
  const byKey = new Map(existing.map((field) => [field.key.toLowerCase(), field]));
  const ordered = defaults.map((field) => byKey.get(field.key.toLowerCase()) || field);
  const seen = new Set(ordered.map((field) => field.key.toLowerCase()));
  const extras = existing.filter((field) => !seen.has(field.key.toLowerCase()));
  return [...ordered, ...extras];
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

function notesVendooUrl(notes?: string | null): string | null {
  if (!notes) return null;
  try {
    const parsed = JSON.parse(notes);
    const url = String(parsed?.vendooUrl || "").trim();
    return url || null;
  } catch {
    return null;
  }
}

function VendooLinkControl({
  convId,
  itemId,
  url,
  onLinked,
}: {
  convId: string;
  itemId?: string | null;
  url?: string | null;
  onLinked?: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(url || itemId || "");
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!editing) setDraft(url || itemId || "");
  }, [editing, itemId, url]);

  React.useEffect(() => {
    if (!editing) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  const linkMutation = useMutation({
    mutationFn: (value: string) => api.conversations.linkVendoo(convId, value),
    onSuccess: () => {
      setEditing(false);
      onLinked?.();
      addToast({
        type: "success",
        title: "Vendoo draft linked",
        description: "Fields can now read that draft once Chrome is connected.",
      });
    },
    onError: (err: Error) => {
      addToast({
        type: "error",
        title: "Could not link Vendoo draft",
        description: err.message || "Check the link and try again.",
      });
    },
  });

  if (editing) {
    return (
      <form
        className="pr-vendoo-link-form"
        onSubmit={(e) => {
          e.preventDefault();
          const next = draft.trim();
          if (!next || linkMutation.isPending) return;
          linkMutation.mutate(next);
        }}
      >
        <input
          ref={inputRef}
          className="pr-vendoo-link-input"
          value={draft}
          placeholder="Paste Vendoo draft link or item ID"
          aria-label="Vendoo draft link or item ID"
          disabled={linkMutation.isPending}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              setEditing(false);
            }
          }}
        />
        <button
          type="submit"
          className="btn btn-secondary btn-sm"
          disabled={linkMutation.isPending || !draft.trim()}
        >
          {linkMutation.isPending ? "Linking…" : "Link"}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={linkMutation.isPending}
          onClick={() => setEditing(false)}
        >
          Cancel
        </button>
      </form>
    );
  }

  return (
    <button
      type="button"
      className={`pr-review-branch pr-vendoo-link-btn${itemId ? "" : " is-empty"}`}
      title={itemId ? (url || itemId) : "Link an existing Vendoo draft"}
      onClick={() => setEditing(true)}
    >
      {itemId ? `vendoo ← ${String(itemId).slice(0, 8)}` : "Link Vendoo draft"}
    </button>
  );
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
  listingTitle,
  vendooItemId,
  onJobStarted,
  onAskChat,
}: {
  convId: string;
  canSend: boolean;
  sendBlockers: { field?: string; message?: string }[];
  listingTitle?: string;
  vendooItemId?: string | null;
  onJobStarted?: () => void;
  onAskChat?: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = React.useState<string | null>(null);

  const { data: extStatus } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: 5000,
  });

  const { data: jobs } = useQuery({
    queryKey: ["jobs", convId],
    queryFn: () => api.jobs.list(convId),
    refetchInterval: 2000,
  });

  const rememberJob = (job: any) => {
    if (!job?.id) return;
    queryClient.setQueryData(["jobs", convId], (old: any[] | undefined) => {
      const rest = (old || []).filter((item) => item.id !== job.id);
      return [job, ...rest];
    });
    queryClient.setQueryData(["jobs"], (old: any[] | undefined) => {
      const rest = (old || []).filter((item) => item.id !== job.id);
      return [job, ...rest];
    });
  };

  const sendMutation = useMutation({
    mutationFn: () => api.jobs.create(convId, { confirmOverwrite: Boolean(vendooItemId) }),
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

  const existingJob = jobs?.find(
    (j: any) => j.conversation_id === convId && j.status !== "cancelled" && j.status !== "imported",
  );
  // Jobs come back newest-first, so a cancelled head job means the last send was stopped by hand.
  const latestFillJob = jobs?.find((j: any) => j.conversation_id === convId && j.mode !== "schema_probe");
  const cancelledJob = latestFillJob?.status === "cancelled" ? latestFillJob : null;
  const isSchemaProbe = existingJob?.mode === "schema_probe";
  const probeActive = Boolean(
    isSchemaProbe && ["queued", "awaiting_extension", "dispatched"].includes(String(existingJob?.status || "")),
  );
  // Completed/failed schema probes must not capture the Send button — create a real fill job instead.
  const fillJob = isSchemaProbe && !probeActive ? null : existingJob;
  const extensionConnected = extStatus?.connected ?? false;
  const overwriteItemId = vendooItemId || fillJob?.vendoo_item_id || existingJob?.vendoo_item_id || null;
  // Field discovery may already bind a Vendoo draft ID. That is still a first Send from the operator's
  // point of view until a real fill/import job has run for this conversation.
  const hasSentBefore = (jobs || []).some(
    (j: any) =>
      j.conversation_id === convId
      && j.status !== "cancelled"
      && j.mode !== "schema_probe",
  );
  const treatAsUpdate = Boolean(overwriteItemId && hasSentBefore);
  const sendLabel = treatAsUpdate ? "Update Vendoo listing" : "Send to Vendoo";
  const uniqueBlockers = React.useMemo(() => {
    const seen = new Set<string>();
    return sendBlockers.filter((err) => {
      const key = `${err.field || ""}|${err.message || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return Boolean(err.message);
    });
  }, [sendBlockers]);
  const blockerText = uniqueBlockers.map((err) => err.message).join(" · ");

  const confirmOverwriteIfNeeded = async () => {
    if (!treatAsUpdate) return true;
    return confirmDialog(
      "Overwrite this existing Vendoo listing?\nThis does not publish. If it is already live, saving may update those marketplace listings.",
    );
  };

  // Cancelled jobs cannot be retried server-side, so a restart starts a fresh send from current fields.
  const startSend = async () => {
    if (!canSend) {
      setError(blockerText || "Listing is not ready. Add a title, description, price, and at least one photo.");
      return;
    }
    if (!(await confirmOverwriteIfNeeded())) return;
    setError(null);
    sendMutation.mutate();
  };

  if (probeActive && existingJob) {
    return (
      <div className="job-card">
        <div className="job-card-header">
          <div className="job-card-copy">
            <div className="job-card-label">Discovering fields</div>
            <div className="job-card-status">
              {existingJob.current_step || existingJob.status}
              <div className="mt-4 text-xs text-muted">
                Matching the Vendoo category and reading marketplace fields into this listing.
              </div>
            </div>
          </div>
          <div className="job-card-actions">
            <button
              type="button"
              className="btn btn-secondary btn-sm job-card-action"
              disabled={cancelMutation.isPending}
              onClick={() => { setError(null); cancelMutation.mutate(existingJob.id); }}
            >
              {cancelMutation.isPending ? "Cancelling..." : "Cancel"}
            </button>
          </div>
        </div>
        {error && (
          <CopyableLlmError
            className="job-card-detail"
            text={error}
            prompt={jobErrorPrompt(error, listingTitle)}
            onAskChat={onAskChat}
          />
        )}
      </div>
    );
  }

  if (fillJob) {
    const isFailed = fillJob.status === "failed";
    const isDispatched = fillJob.status === "dispatched";
    const isCompleted = fillJob.status === "completed";
    const isQueued = fillJob.status === "queued" || fillJob.status === "awaiting_extension";
    const completionStep = ["awaiting_answers", "completion_blocked", "resolving_fields", "verifying_draft", "verified_complete"].includes(fillJob.current_step || "");
    const queueJobs = (jobs || [])
      .filter((j: any) =>
        ["queued", "awaiting_extension", "dispatched"].includes(String(j.status || ""))
        && j.mode !== "schema_probe",
      )
      .slice()
      .sort((a: any, b: any) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
    const queuePosition = Math.max(1, queueJobs.findIndex((j: any) => j.id === fillJob.id) + 1);
    const queueDepth = queueJobs.length;
    const waitingInQueue = isQueued && (queuePosition > 1 || queueJobs.some((j: any) => j.status === "dispatched" && j.id !== fillJob.id));
    const stepLabel: Record<string, string> = {
      awaiting_answers: "Waiting for draft review",
      completion_blocked: "Completion needs review",
      resolving_fields: "Resolving missing fields",
      verifying_draft: "Checking the saved draft",
      verified_complete: "Saved draft verified complete",
      fields_applied: "Empty fields applied on Vendoo",
    };
    const leftoverFilling = isDispatched && (completionStep || fillJob.current_step === "filling_fields");
    const canRestart = (isFailed || isDispatched || isCompleted) && !leftoverFilling;
    const canCancel = !isCompleted;
    const statusText = waitingInQueue
      ? `Queued (#${queuePosition} of ${queueDepth}) — waiting for the current send to finish`
      : isQueued && fillJob.status === "awaiting_extension"
        ? "Waiting for Chrome"
        : isQueued
          ? (queueDepth > 1 ? `Queued (#${queuePosition} of ${queueDepth})` : "Queued — starting soon")
          : (stepLabel[fillJob.current_step || ""] || `${fillJob.status}: ${fillJob.current_step || "queued"}`);
    const buttonLabel = retryMutation.isPending
      ? "Sending..."
      : isFailed
        ? (completionStep ? "Resume verification" : "Retry")
        : isCompleted
          ? sendLabel
          : "Restart Job";
    return (
      <div className={`job-card${isFailed ? " job-card-error" : ""}`}>
        <div className="job-card-header">
          <div className="job-card-copy">
            <div className="job-card-label">Job Status</div>
            <div className={`job-card-status${isFailed ? " error" : ""}`}>{statusText}</div>
          </div>
          <div className="job-card-actions">
            {canRestart && (
              <button
                type="button"
                className="btn btn-primary btn-sm job-card-action"
                disabled={retryMutation.isPending || cancelMutation.isPending}
                onClick={async () => {
                  if (!completionStep && !(await confirmOverwriteIfNeeded())) return;
                  setError(null);
                  retryMutation.mutate(fillJob.id);
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
                onClick={() => { setError(null); cancelMutation.mutate(fillJob.id); }}
              >
                {cancelMutation.isPending ? "Cancelling..." : "Cancel"}
              </button>
            )}
          </div>
        </div>
        {fillJob.last_error && (
          <CopyableLlmError
            className="job-card-detail"
            text={fillJob.last_error}
            prompt={
              completionStep
                ? completionBlockerPrompt(
                    fillJob.last_error,
                    listingTitle,
                    Array.isArray(fillJob.blocker_fields) ? fillJob.blocker_fields : null,
                  )
                : jobErrorPrompt(
                    fillJob.last_error,
                    listingTitle,
                    Array.isArray(fillJob.blocker_fields) ? fillJob.blocker_fields : null,
                  )
            }
            onAskChat={onAskChat}
          />
        )}
        {error && (
          <CopyableLlmError
            className="job-card-detail"
            text={error}
            prompt={jobErrorPrompt(
              error,
              listingTitle,
              Array.isArray(fillJob.blocker_fields) ? fillJob.blocker_fields : null,
            )}
            onAskChat={onAskChat}
          />
        )}
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

  const displayError = error || (!canSend ? blockerText : "");
  const blockerPrompt = validationErrorsPrompt(
    uniqueBlockers.length ? uniqueBlockers : [{ message: displayError }],
    listingTitle,
  );
  const errorCard = displayError ? (
    <CopyableLlmError
      className={cancelledJob ? "job-card-detail" : "mt-8"}
      text={displayError}
      prompt={uniqueBlockers.length ? blockerPrompt : jobErrorPrompt(displayError, listingTitle)}
      onAskChat={onAskChat}
    />
  ) : null;

  if (cancelledJob) {
    return (
      <div className="job-card">
        <div className="job-card-header">
          <div className="job-card-copy">
            <div className="job-card-label">Job Status</div>
            <div className="job-card-status">
              Cancelled
              <div className="mt-4 text-xs text-muted">
                {canSend
                  ? "Restart sends this listing to Vendoo again using the current fields."
                  : "Fix the fields listed below, then restart."}
              </div>
            </div>
          </div>
          <div className="job-card-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm job-card-action"
              disabled={sendMutation.isPending || !canSend}
              onClick={startSend}
            >
              {sendMutation.isPending ? "Restarting..." : treatAsUpdate ? "Restart update" : "Restart listing"}
            </button>
          </div>
        </div>
        {errorCard}
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        className="btn btn-success"
        style={{ width: "100%" }}
        disabled={sendMutation.isPending || !canSend}
        onClick={startSend}
      >
        {sendMutation.isPending ? "Sending..." : sendLabel}
      </button>
      {errorCard}
    </div>
  );
}
