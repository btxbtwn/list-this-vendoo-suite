import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Job, ListingData, MarketplaceForm } from "../api/types";
import { cloneListing, getListingEditorValue, setListingEditorValue } from "../listingPaths";
import { FillLogPanel } from "./FillLogPanel";
import { PhotoTray } from "./PhotoTray";
import { ItemDetails } from "./ItemDetails";
import { ConnectChromeButton } from "./ConnectChromeButton";
import { OpenListingButton } from "./OpenListingButton";
import { VendooSyncButtons } from "./VendooSyncButtons";
import {
  DEPOP_CATEGORY_OPTIONALS,
  EBAY_CATEGORY_OPTIONALS,
  ETSY_CATEGORY_OPTIONALS,
} from "../marketplaceFields";
import { addToast } from "../ui/toast";
import { ClearListingButton } from "./ClearListingButton";
import { fetchVendooItemLive } from "../api/vendooItemQuery";
import {
  CopyableLlmError,
  jobErrorPrompt,
  validationErrorsPrompt,
} from "./CopyableLlmError";

interface Props {
  convId: string;
  onJobStarted?: () => void;
  onAskChat?: (text: string) => void;
  onCleared?: () => void;
  onOpenBrowser?: (jobId: string) => void;
  browserOpen?: boolean;
}

interface EditorField {
  key: string;
  label: string;
  type?: string;
  defaultValue?: string;
  required?: boolean;
  options?: string[];
}

export function ListingEditor({ convId, onJobStarted, onAskChat, onCleared, onOpenBrowser, browserOpen }: Props) {
  const queryClient = useQueryClient();
  const [reviewTab, setReviewTab] = React.useState<"input" | "forms" | "fields">("input");
  const [editTab, setEditTab] = React.useState("general");
  const [jsonText, setJsonText] = React.useState("");

  const { data: jobs, isLoading: jobsLoading, isFetching: jobsFetching } = useQuery({
    queryKey: ["jobs", convId],
    queryFn: () => api.jobs.list(convId),
    refetchInterval: 2000,
  });
  const listingJob = jobs?.find((j) => j.conversation_id === convId && j.status !== "cancelled");
  const schemaProbeActive = Boolean(
    listingJob?.mode === "schema_probe"
    && ["queued", "awaiting_extension", "dispatched"].includes(String(listingJob?.status || "")),
  );
  const [ensureError, setEnsureError] = React.useState<string | null>(null);
  const ensureDraftMutation = useMutation({
    mutationFn: async (opts?: { importDraft?: boolean }) => {
      const job = await api.jobs.ensureDraft(convId);
      // Live API read stays inside the mutation so attach waits until the draft is loaded.
      // Importing needs blob: preview photos resolved and uploaded by the extension first,
      // since only the Vendoo tab itself can read a blob: URL.
      const fresh = await fetchVendooItemLive(queryClient, job.id, {
        force: true,
        resolvePhotos: Boolean(opts?.importDraft),
      });
      // Linking adopts the draft; plain attach must not overwrite Studio edits.
      const imported = opts?.importDraft ? await api.jobs.importDraft(job.id) : null;
      return { job, fresh, imported };
    },
    onSuccess: ({ job, fresh, imported }) => {
      setEnsureError(null);
      queryClient.setQueryData(["jobs", convId], (old: Job[] | undefined) => {
        const rest = (old || []).filter((item) => item.id !== job.id);
        return [job, ...rest];
      });
      queryClient.invalidateQueries({ queryKey: ["jobs", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      queryClient.invalidateQueries({ queryKey: ["fill-log"] });
      if (imported) {
        queryClient.invalidateQueries({ queryKey: ["photos", convId] });
        addToast({
          type: imported.photo_warnings.length ? "error" : "success",
          title: `Imported Vendoo draft with ${imported.photo_count} photo${imported.photo_count === 1 ? "" : "s"}`,
          description: imported.photo_warnings.join(" ") || imported.listing_title,
        });
      }
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
    mutationFn: (listing: ListingData) => api.listings.update(convId, listing),
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
    // First time seeing this binding with no job yet is the same as a fresh Link:
    // adopt the draft's fields into Forms, not just the live Fields scrape.
    ensureDraftMutation.mutate({ importDraft: true });
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
            {listingJob && onOpenBrowser && (listingJob.vendoo_item_id || listingJob.vendoo_url) && (
              <button
                type="button"
                className="pr-review-open"
                disabled={browserOpen}
                title="Work in the Vendoo draft here: click, type, and point Studio at fields to fill"
                onMouseDown={(event) => event.stopPropagation()}
                onClick={() => onOpenBrowser(listingJob.id)}
              >
                Browser
              </button>
            )}
            <VendooSyncButtons
              convId={convId}
              bound={Boolean(listingJob?.vendoo_item_id || importedItemId)}
              className="pr-review-open"
            />
            <ClearListingButton convId={convId} className="pr-review-clear" onCleared={onCleared} />
          </div>
        </div>
        <div className="pr-review-meta">
          <VendooLinkControl
            convId={convId}
            itemId={importedItemId}
            url={importedUrl}
            onLinked={(linkedItemId) => {
              // Claim the auto-attach key so the effect doesn't race this import.
              ensureAttemptKey.current = `${convId}:${linkedItemId}`;
              queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
              queryClient.invalidateQueries({ queryKey: ["conversations"] });
              queryClient.invalidateQueries({ queryKey: ["jobs", convId] });
              ensureDraftMutation.mutate({ importDraft: true });
            }}
          />
        </div>
        <div className="pr-pills" role="tablist" aria-label="Listing review">
          {(["input", "forms", "fields"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={reviewTab === tab}
              className={`pr-pill${reviewTab === tab ? " is-active" : ""}`}
              onClick={() => setReviewTab(tab)}
            >
              {tab === "input" ? "Input" : tab === "forms" ? "Forms" : "Fields"}
            </button>
          ))}
        </div>
      </div>

      {schemaProbeActive && (
        <div className="pr-notice" role="status">
          Discovering Vendoo marketplace fields for this category… Empty keys will appear on Forms as they arrive.
        </div>
      )}

      <div className={`editor-body${reviewTab === "fields" ? " is-files" : reviewTab === "input" ? " is-input" : ""}`}>
        {reviewTab === "input" ? (
          <>
            <PhotoTray convId={convId} />
            <ItemDetails convId={convId} />
          </>
        ) : reviewTab === "fields" ? (
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
                    ? "This listing already has a Vendoo draft, but its job isn’t loaded yet."
                    : "Send this listing to Vendoo, then open Fields to review each marketplace."}
              </p>
              {ensureError && <p className="text-xs text-error" style={{ marginTop: 8 }}>{ensureError}</p>}
              {importedItemId && !jobsLoading && ensureError && (
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
                  {ensureDraftMutation.isPending || jobsFetching ? "Retrying…" : "Retry"}
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
                convId={convId}
                listing={listing}
                revisionId={data?.current_revision_id}
                tab={editTab}
                onChange={(updated) => updateMutation.mutate(updated)}
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
  convId,
  listing,
  revisionId,
  tab,
  onChange,
}: {
  convId: string;
  listing: ListingData;
  revisionId?: string | null;
  tab: string;
  onChange: (v: ListingData) => void;
}) {
  // What Vendoo says this listing's category actually renders, rather than a
  // list kept by hand here. Falls back to the static one while it loads, or
  // for a category no schema has been fetched for.
  const { data: forms } = useQuery({
    queryKey: ["listing-fields", convId],
    queryFn: () => api.vendooApi.listingFields(convId),
    staleTime: 60_000,
  });
  const fields = React.useMemo(
    () => schemaFieldsForTab(forms?.forms, tab) ?? getFieldsForTab(listing, tab),
    [forms, listing, tab],
  );
  const [local, setLocal] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    const init: Record<string, string> = {};
    fields.forEach((f) => {
      const val = getListingEditorValue(listing, f.key);
      // Schema labels ("Sleeve Length") don't match JSON keys ("sleeveLength");
      // the fields API already resolved the value — use it when the path miss.
      const text = val != null && String(val).trim() !== "" ? String(val) : (f.defaultValue || "");
      init[f.key] = text;
    });
    setLocal(init);
  }, [listing, revisionId, tab, fields]);

  const handleBlur = (key: string) => {
    if (local[key] == null) return;
    const updated = cloneListing(listing);
    for (const field of fields) {
      if (local[field.key] == null) continue;
      setListingEditorValue(updated, field.key, coerce(local[field.key]));
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
            <input className="input" type={f.type || "text"} value={local[f.key] || ""} onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })} onBlur={() => handleBlur(f.key)} />
          )}
        </div>
      ))}

      <div className="field-grid">
        {gridFields.map((f) => (
          <div key={f.key} className={f.label === "Category" ? "field-row field-full" : "field-row"}>
            <label className="label">{f.label}</label>
            <input
              className="input"
              type={f.type || "text"}
              value={local[f.key] || ""}
              // Vendoo only accepts its own options for these, so offer them
              // rather than letting a near-miss be typed in.
              list={f.options?.length ? `${f.key}-options` : undefined}
              onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })}
              onBlur={() => handleBlur(f.key)}
            />
            {f.options?.length ? (
              <datalist id={`${f.key}-options`}>
                {f.options.map((option) => (
                  <option key={option} value={option} />
                ))}
              </datalist>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Fields for this tab from Vendoo's own schema, or null when it has none. */
function schemaFieldsForTab(
  forms: MarketplaceForm[] | undefined,
  tab: string,
): EditorField[] | null {
  const form = forms?.find((entry) => entry.marketplace === tab);
  if (!form?.known || !form.fields.length) return null;
  return form.fields.map((field) => ({
    // Schema keys are Vendoo labels ("Sleeve Length"); listing JSON uses camelCase.
    // getListingEditorValue / setListingEditorValue bridge the two.
    key: `${tab}_specifics.${field.key}`,
    label: field.required ? `${field.label} *` : field.label,
    required: field.required,
    options: field.options,
    defaultValue: field.value != null ? String(field.value) : "",
  }));
}

function getFieldsForTab(listing: ListingData | undefined, tab: string): EditorField[] {
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
        { key: "mercari_specifics.shippingLabel", label: "Shipping Label", defaultValue: "USPS Ground Advantage / 1 - 7 days / $ 5.66 / 0.5 lb" },
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
  specs: unknown,
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

function specificsFields(specs: unknown, prefix: string, skip: string[] = []): EditorField[] {
  if (!specs || typeof specs !== "object") return [];
  const fields: EditorField[] = [];
  for (const [key, value] of Object.entries(specs as Record<string, unknown>)) {
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
  onLinked?: (itemId: string) => void;
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
    onSuccess: (linked) => {
      setEditing(false);
      onLinked?.(linked.vendoo_item_id);
      addToast({
        type: "success",
        title: "Vendoo draft linked",
        description: "Importing its fields and photos through Chrome…",
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

function coerce(val: string): string | number | null {
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
  const bound = Boolean(vendooItemId);

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

  const sendMutation = useMutation({
    mutationFn: async () => {
      if (bound) {
        return { kind: "save" as const, ...(await api.vendooApi.save(convId)) };
      }
      return { kind: "create" as const, ...(await api.vendooApi.create(convId)) };
    },
    onSuccess: (res) => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["jobs", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      queryClient.invalidateQueries({ queryKey: ["listing-fields", convId] });
      queryClient.invalidateQueries({ queryKey: ["fill-log"] });
      queryClient.invalidateQueries({ queryKey: ["vendoo-item"] });
      if (res.kind === "create") {
        const gaps = [...(res.unresolved || []), ...(res.unfilled || [])];
        addToast({
          type: gaps.length ? "error" : "success",
          title: "Sent to Vendoo",
          description: gaps.length
            ? `Draft created. ${gaps.length} field${gaps.length === 1 ? "" : "s"} still need a value.`
            : "Draft created with marketplace fields filled.",
        });
      } else {
        addToast({
          type: "success",
          title: res.updated.length ? "Sent to Vendoo" : "Nothing to send",
          description: res.updated.length
            ? `${res.updated.length} field${res.updated.length === 1 ? "" : "s"} written.`
            : "Vendoo already matches this listing.",
        });
      }
      onJobStarted?.();
    },
    onError: (err: Error) => setError(err.message || "Failed to send"),
  });

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => api.jobs.cancel(jobId),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err: Error) => setError(err.message || "Failed to cancel"),
  });

  const existingJob = jobs?.find(
    (j) => j.conversation_id === convId && j.status !== "cancelled" && j.status !== "imported",
  );
  const isSchemaProbe = existingJob?.mode === "schema_probe";
  const probeActive = Boolean(
    isSchemaProbe && ["queued", "awaiting_extension", "dispatched"].includes(String(existingJob?.status || "")),
  );
  const step = String(existingJob?.current_step || "");
  const apiCreateActive = Boolean(
    existingJob
    && existingJob.status === "dispatched"
    && (step === "vendoo_api_create" || step.startsWith("vendoo_api_")),
  );
  // A browser fix the seller asked chat for is typing into the Vendoo form.
  // Send itself never gets here: it is a Vendoo API call, reported above.
  const formFillActive = Boolean(
    existingJob
    && !isSchemaProbe
    && !apiCreateActive
    && ["queued", "awaiting_extension", "dispatched"].includes(String(existingJob.status || "")),
  );
  const extensionConnected = extStatus?.connected ?? false;
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
  const sendLabel = "Send to Vendoo";

  const startSend = () => {
    if (!canSend) {
      setError(blockerText || "Listing is not ready. Add a title, description, price, and at least one photo.");
      return;
    }
    setError(null);
    sendMutation.mutate();
  };

  if ((probeActive || apiCreateActive || formFillActive) && existingJob) {
    const stepKey = String(existingJob.current_step || "");
    const apiCreateCopy: Record<string, string> = {
      vendoo_api_categories: "Resolving marketplace categories…",
      vendoo_api_specifics: "Reading category fields from Vendoo…",
      vendoo_api_fields: "Filling marketplace fields…",
      vendoo_api_photos: "Uploading photos to Vendoo…",
      vendoo_api_create: "Creating the Vendoo draft…",
    };
    const label = probeActive
      ? "Discovering fields"
      : apiCreateActive
        ? "Sending to Vendoo"
        : "Filling fields in the browser";
    const statusText = probeActive
      ? (existingJob.current_step || existingJob.status)
      : apiCreateActive
        ? (apiCreateCopy[stepKey] || "Working with Vendoo…")
        : `${existingJob.status}: ${existingJob.current_step || "queued"}`;
    return (
      <div className="job-card">
        <div className="job-card-header">
          <div className="job-card-copy">
            <div className="job-card-label">{label}</div>
            <div className="job-card-status">
              {statusText}
              {probeActive && (
                <div className="mt-4 text-xs text-muted">
                  Matching the Vendoo category and reading marketplace fields into this listing.
                </div>
              )}
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
        {existingJob.last_error && (
          <CopyableLlmError
            className="job-card-detail"
            text={existingJob.last_error}
            prompt={jobErrorPrompt(existingJob.last_error, listingTitle)}
            onAskChat={onAskChat}
          />
        )}
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
      className="mt-8"
      text={displayError}
      prompt={uniqueBlockers.length ? blockerPrompt : jobErrorPrompt(displayError, listingTitle)}
      onAskChat={onAskChat}
    />
  ) : null;

  return (
    <div>
      <button
        type="button"
        className="btn btn-success"
        style={{ width: "100%" }}
        disabled={sendMutation.isPending || !canSend}
        title={bound
          ? "Write this listing's changed fields onto the Vendoo draft"
          : "Create a Vendoo draft with marketplace fields filled"}
        onClick={startSend}
      >
        {sendMutation.isPending ? "Sending…" : sendLabel}
      </button>
      {errorCard}
    </div>
  );
}
