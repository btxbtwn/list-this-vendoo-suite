import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Job, ListingData, MarketplaceForm } from "../api/types";
import { cloneListing, getListingEditorValue, setListingEditorValue } from "../listingPaths";
import { FillLogPanel } from "./FillLogPanel";
import { PhotoTray } from "./PhotoTray";
import { ItemDetails } from "./ItemDetails";
import { ConnectChromeButton } from "./ConnectChromeButton";
import { SendProgress, sendProgressLabel } from "./SendProgress";
import { ListingBlockers } from "./ListingBlockers";
import { ListingHistory } from "./ListingHistory";
import { blockerTarget, matchingEditorField } from "./listingChanges";
import { VendooSyncStatus } from "./VendooSyncStatus";
import { OpenListingButton } from "./OpenListingButton";
import { MarketplaceLogo } from "./MarketplaceLogo";
import { marketplaceName } from "./marketplaceNames";
import {
  joinMarketplaces,
  marketplacesNeedingRelist,
  relistCallout,
  relistStage,
} from "./relistStatus";
import {
  DEPOP_CATEGORY_OPTIONALS,
  EBAY_CATEGORY_OPTIONALS,
  ETSY_CATEGORY_OPTIONALS,
} from "../marketplaceFields";
import { withDropdownOptions } from "../dropdownOptions";
import { activityPollMs, EXTENSION_STATUS_POLL_MS, fillLogPollMs, jobsPollMs, pollMs } from "../api/polling";
import { addToast } from "../ui/toast";
import { useChatBusy } from "./ChatPanel";
import { fetchVendooItemLive, VENDOO_ITEM_STALE_MS, vendooItemQueryKey } from "../api/vendooItemQuery";
import {
  CopyableLlmError,
  jobErrorPrompt,
  validationErrorsPrompt,
} from "./CopyableLlmError";
import {
  askChatGapsPrompt,
  askChatTargetCount,
  emptyHiddenFields,
  fillFailureEntries,
  hiddenFieldKey,
  hiddenKeySet,
  mergeDraftItem,
  normalizeFieldName,
  sourceFormsForJob,
  withoutHiddenFields,
} from "./fillLogForms";
import { ListingBrowserButton, ListingReviewActions } from "./ListingReviewActions";
import { ListingReviewTabs, type ListingReviewTab } from "./ListingReviewTabs";
import type { BulkListingUploadResult } from "../bulkPhotoUpload";

interface Props {
  convId: string;
  onAskChat?: (text: string) => void;
  onCleared?: () => void;
  onOpenBrowser?: (jobId: string) => void;
  browserOpen?: boolean;
  reviewTab: ListingReviewTab;
  onReviewTabChange: (tab: ListingReviewTab) => void;
  onBulkListingsCreated?: (listings: BulkListingUploadResult[]) => void;
}

interface EditorField {
  key: string;
  label: string;
  type?: string;
  defaultValue?: string;
  required?: boolean;
  options?: string[];
}

export function ListingEditor({
  convId,
  onAskChat,
  onCleared,
  onOpenBrowser,
  browserOpen,
  reviewTab,
  onReviewTabChange,
  onBulkListingsCreated,
}: Props) {
  const queryClient = useQueryClient();
  const [editTab, setEditTab] = React.useState("general");
  const [jsonText, setJsonText] = React.useState("");
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [fieldTarget, setFieldTarget] = React.useState<{ field: string; sequence: number } | null>(null);
  const editorRef = React.useRef<HTMLDivElement>(null);
  const showJsonEditor = React.useCallback(() => setEditTab("json"), []);

  // isFetching is read only where Retry renders: destructuring it here would
  // re-render the whole editor twice on every jobs poll.
  const jobsQuery = useQuery({
    queryKey: ["jobs", convId],
    queryFn: () => api.jobs.list(convId),
    refetchInterval: (query) => jobsPollMs(query.state.data),
  });
  const { data: jobs, isLoading: jobsLoading } = jobsQuery;
  const { data: photos, isLoading: photosLoading } = useQuery({
    queryKey: ["photos", convId],
    queryFn: () => api.conversations.photos(convId),
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
      // Remount on Regenerate/Clear aborts an in-flight refresh; that is not a failure.
      const name = err?.name || "";
      if (name === "AbortError" || name === "CancelledError") return;
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
    onSuccess: (_result, listing) => {
      queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      // A SKU edit is copied into Item Details.
      if ((listing.sku || "") !== (data?.listing?.sku || "")) {
        queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
      }
    },
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

  const openBlocker = (field: string) => {
    const target = blockerTarget(field);
    onReviewTabChange(target.reviewTab);
    setEditTab(tabs.includes(target.tab) ? target.tab : "json");
    setFieldTarget({ field, sequence: Date.now() });
  };
  React.useEffect(() => {
    if (fieldTarget?.field === "photos" && reviewTab === "input") {
      const target = editorRef.current?.querySelector<HTMLElement>(".photo-tray button");
      target?.scrollIntoView({ block: "center" });
      target?.focus();
    }
    if (fieldTarget && editTab === "json" && reviewTab === "forms") {
      const target = editorRef.current?.querySelector<HTMLTextAreaElement>("textarea[aria-label='Listing JSON']");
      target?.focus();
      const keys = fieldTarget.field.split(".");
      const key = keys[keys.length - 1];
      const index = target?.value.indexOf(JSON.stringify(key)) ?? -1;
      if (index >= 0) target?.setSelectionRange(index, index + key.length + 2);
    }
  }, [fieldTarget, reviewTab, editTab]);

  const applyJsonEdit = () => {
    try {
      const parsed = JSON.parse(jsonText);
      updateMutation.mutate(parsed);
    } catch {
      alert("Invalid JSON");
    }
  };

  // Error cards offer "Fix errors" / "Ask chat for fields"; mid-generation the
  // listing is still being written, so those prompts would chase half-done values.
  const chatBusy = useChatBusy(convId);
  // Same query ChatPanel polls: background field fills keep writing after the
  // stream ends, and "Ask chat" beside "Filling discovered fields…" contradicts it.
  const { data: activity } = useQuery({
    queryKey: ["activity", convId],
    queryFn: () => api.conversations.activity(convId),
    refetchInterval: (query) => activityPollMs(Boolean(query.state.data?.busy)),
  });
  const generating = chatBusy || Boolean(activity?.busy) || schemaProbeActive;
  const askChat = generating ? undefined : onAskChat;

  const listing = data?.listing || {};
  const listingTitle = String(listing.title || "Listing");
  const importedItemId = listingJob?.vendoo_item_id || notesVendooItemId(conversation?.notes);
  const importedUrl = listingJob?.vendoo_url || notesVendooUrl(conversation?.notes);

  // Studio writes the Vendoo *form*. Vendoo carries a form change onto a live
  // marketplace listing only when the seller delists and relists it there, so
  // the app says which listings are still on the old copy instead of leaving a
  // regenerated item reading as though it were published.
  const relistMarketplaces = React.useMemo(
    () => marketplacesNeedingRelist(conversation).map(marketplaceName),
    [conversation],
  );
  // Which half is left. After Delist Item the item is live nowhere, which the
  // banner has to say plainly — that is the state most easily walked away from.
  const stage = React.useMemo(() => relistStage(conversation), [conversation]);
  const relistDone = useMutation({
    mutationFn: () => api.vendooApi.relistDone(convId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
  const liveMarketplaces = React.useMemo(() => {
    const sold = conversation?.vendoo_sold_dates || {};
    return (conversation?.vendoo_marketplaces || [])
      .filter((id) => !sold[id])
      .map(marketplaceName);
  }, [conversation]);

  // Opening an imported draft selects Fields once. The parent creates a new
  // callback on each render; that must not reset the seller's tab selection.
  const openImportedFields = React.useEffectEvent(() => onReviewTabChange("fields"));
  React.useEffect(() => {
    if (importedItemId && listingJob?.status === "imported") {
      openImportedFields();
    }
  }, [importedItemId, listingJob?.status, listingJob?.id]);

  const ensureAttemptKey = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (jobsLoading || photosLoading || listingJob || !importedItemId) return;
    const key = `${convId}:${importedItemId}`;
    if (ensureAttemptKey.current === key) return;
    ensureAttemptKey.current = key;
    // Blank linked listing (Clear, or first open with no local photos): import the
    // Vendoo draft. Photos still present means Regenerate/remount — only reattach
    // Fields. importDraft opens Chrome and walks every marketplace tab.
    const hasLocalPhotos = Boolean(photos?.length);
    ensureDraftMutation.mutate({ importDraft: !hasLocalPhotos });
    // Refresh fields clears ensureAttemptKey before calling mutate again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobsLoading, photosLoading, listingJob?.id, importedItemId, convId, photos?.length]);

  return (
    <div className="listing-editor" ref={editorRef}>
      <div className="pr-review-header">
        {/* Desktop: the titlebar breadcrumb already names the listing in full and
            the actions sit beside it, so repeating a truncated copy here only
            costs a row. Mobile has no titlebar and keeps both. */}
        <div className="pr-review-title-row pr-review-chrome-mobile">
          <h2 className="pr-review-title pywebview-drag-region" title={listingTitle}>{listingTitle}</h2>
          <ListingReviewActions
            className="pr-review-chrome-mobile"
            convId={convId}
            onCleared={onCleared}
          >
            <ListingBrowserButton
              convId={convId}
              browserOpen={browserOpen}
              onOpenBrowser={onOpenBrowser}
            />
          </ListingReviewActions>
        </div>
        <div className="pr-review-meta">
          <button type="button" className="btn btn-ghost btn-sm" disabled={!data?.current_revision_id} onClick={() => { setFieldTarget(null); setHistoryOpen(true); }}>History</button>
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
          <MarketplaceLinks urls={conversation?.vendoo_listing_urls} />
          <VendooSyncStatus
            convId={convId}
            bound={Boolean(listingJob?.vendoo_item_id || importedItemId)}
          />
          {conversation?.unsent_edits ? (
            <span
              className="editor-unsent"
              title="This listing has changed since Vendoo last had it. Update Vendoo writes it onto the Vendoo form."
            >
              Unsent edits
            </span>
          ) : null}
          {data?.can_send && !generating && <span className="editor-ready">Ready</span>}
        </div>
        <ListingReviewTabs
          className="pr-review-chrome-mobile"
          value={reviewTab}
          onChange={onReviewTabChange}
        />
      </div>

      {relistMarketplaces.length > 0 && (
        <div
          className="pr-notice is-relist"
          role="status"
          title={`Waiting on a relist: ${relistMarketplaces.join(", ")}`}
        >
          <div className="pr-notice-body">
            <h3 className="pr-relist-title">
              {stage === "list" ? "Finish relisting in Vendoo" : "Relist to show your updates"}
            </h3>
            <p className="pr-relist-summary">{relistCallout(relistMarketplaces, stage)}</p>
            <ol className="pr-relist-steps">
              <li>Open this listing in Vendoo.</li>
              {stage !== "list" && (
                <li>
                  Open the <strong>⋮ menu</strong> beside <strong>Vendoo Form</strong> and choose{" "}
                  <strong>Delist Item</strong>. This removes the item from every marketplace at once.
                </li>
              )}
              <li>List the item again on: <strong>{relistMarketplaces.join(", ")}</strong>.</li>
            </ol>
            <p className="pr-relist-hint">
              Already relisted? Choose <strong>I've relisted</strong> to clear this reminder.
              {" "}This button only clears the reminder.
            </p>
          </div>
          <div className="pr-notice-actions">
            {listingJob ? (
              <OpenListingButton
                className="btn btn-secondary btn-sm pr-notice-action"
                jobId={listingJob.id}
                vendooItemId={importedItemId}
                vendooUrl={importedUrl}
              />
            ) : null}
            <button
              type="button"
              className="btn btn-ghost btn-sm pr-notice-action"
              disabled={relistDone.isPending}
              title="Clear this reminder after you have relisted in Vendoo"
              onClick={() => relistDone.mutate()}
            >
              {relistDone.isPending ? "Clearing…" : "I've relisted"}
            </button>
          </div>
        </div>
      )}

      {schemaProbeActive && (
        <div className="pr-notice" role="status">
          Discovering Vendoo marketplace fields for this category… Empty keys will appear on Forms as they arrive.
        </div>
      )}

      <div className={`editor-body${reviewTab === "fields" ? " is-files" : reviewTab === "input" ? " is-input" : ""}`}>
        {reviewTab === "input" ? (
          <>
            <PhotoTray convId={convId} onBulkListingsCreated={onBulkListingsCreated} />
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
              onAskChat={askChat}
              onFilled={() => queryClient.invalidateQueries({ queryKey: ["listing", convId] })}
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
                  disabled={jobsQuery.isFetching || ensureDraftMutation.isPending}
                  onClick={() => {
                    setEnsureError(null);
                    ensureAttemptKey.current = null;
                    ensureDraftMutation.reset();
                    ensureDraftMutation.mutate();
                  }}
                >
                  {ensureDraftMutation.isPending || jobsQuery.isFetching ? "Retrying…" : "Retry"}
                </button>
              )}
            </div>
          )
        ) : (
          <>
            <div className="tab-group">
              {tabs.map((tab) => (
                <button key={tab} className={`tab-btn${editTab === tab ? " active" : ""}`} onClick={() => { setFieldTarget(null); setEditTab(tab); }}>
                  {tab === "json" ? "JSON" : tab.charAt(0).toUpperCase() + tab.slice(1)}
                </button>
              ))}
            </div>
            {editTab === "json" ? (
              <div>
                <textarea
                  className="input"
                  aria-label="Listing JSON"
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
                target={fieldTarget}
                onMissingField={showJsonEditor}
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
          generating={generating}
          sendBlockers={data?.errors || []}
          listing={listing}
          listingTitle={listingTitle}
          selectedMarketplaces={marketplaceSettings?.selected}
          liveMarketplaces={liveMarketplaces}
          vendooItemId={importedItemId}
          onSelectBlocker={openBlocker}
          onAskChat={askChat}
        />
      </div>
      {historyOpen && data?.current_revision_id && <ListingHistory convId={convId} listing={listing} revisionId={data.current_revision_id}
        busy={generating || Boolean(jobs?.some((job) => ACTIVE_SEND_STATUSES.has(job.status)))} onClose={() => setHistoryOpen(false)} />}
    </div>
  );
}

function StructuredEditor({
  convId,
  listing,
  revisionId,
  tab,
  onChange,
  target,
  onMissingField,
}: {
  convId: string;
  listing: ListingData;
  revisionId?: string | null;
  tab: string;
  onChange: (v: ListingData) => void;
  target: { field: string; sequence: number } | null;
  onMissingField: () => void;
}) {
  const formRef = React.useRef<HTMLDivElement>(null);
  // What Vendoo says this listing's category actually renders, rather than a
  // list kept by hand here. Falls back to the static one while it loads, or
  // for a category no schema has been fetched for.
  const { data: forms, isFetching: fieldsLoading } = useQuery({
    queryKey: ["listing-fields", convId],
    queryFn: () => api.vendooApi.listingFields(convId),
    staleTime: 60_000,
  });
  const { data: dropdownOptions } = useQuery({
    queryKey: ["catalog-dropdown-options"],
    queryFn: api.catalog.dropdownOptions,
    staleTime: Infinity,
  });
  const fields = React.useMemo(
    () =>
      withDropdownOptions(
        schemaFieldsForTab(forms?.forms, tab) ?? getFieldsForTab(listing, tab),
        tab,
        dropdownOptions?.forms,
      ),
    [forms, listing, tab, dropdownOptions?.forms],
  );
  const [local, setLocal] = React.useState<Record<string, string>>({});
  React.useEffect(() => {
    if (!target) return;
    const key = matchingEditorField(fields, target.field);
    if (!key) { if (!fieldsLoading) onMissingField(); return; }
    const input = [...(formRef.current?.querySelectorAll<HTMLElement>("[data-listing-field]") || [])].find((element) => element.dataset.listingField === key);
    input?.scrollIntoView({ block: "center" });
    input?.focus();
  }, [target, fields, fieldsLoading, onMissingField]);

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
    const field = fields.find((entry) => entry.key === key);
    const before = getListingEditorValue(listing, key);
    if (local[key] === (before != null ? String(before) : field?.defaultValue || "")) return;
    const updated = cloneListing(listing);
    setListingEditorValue(updated, key, coerce(local[key]));
    onChange(updated);
  };

  const commitField = (key: string, value: string) => {
    const nextLocal = { ...local, [key]: value };
    setLocal(nextLocal);
    const updated = cloneListing(listing);
    setListingEditorValue(updated, key, coerce(value));
    onChange(updated);
  };

  const generalFields = fields.filter((f) => ["title", "description", "category_path"].includes(f.key));
  const gridFields = fields.filter((f) => !["title", "description", "category_path"].includes(f.key));

  return (
    <div ref={formRef}>
      {generalFields.map((f) => (
        <div key={f.key} className="field-row">
          <label className="label" htmlFor={`listing-field-${f.key}`}>{f.label}</label>
          {f.key === "description" ? (
            <textarea id={`listing-field-${f.key}`} data-listing-field={f.key} className="input" style={{ height: 100 }} value={local[f.key] || ""} onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })} onBlur={() => handleBlur(f.key)} />
          ) : (
            <input id={`listing-field-${f.key}`} data-listing-field={f.key} className="input" type={f.type || "text"} value={local[f.key] || ""} onChange={(e) => setLocal({ ...local, [f.key]: e.target.value })} onBlur={() => handleBlur(f.key)} />
          )}
        </div>
      ))}

      <div className="field-grid">
        {gridFields.map((f) => (
          <div key={f.key} className={f.label === "Category" ? "field-row field-full" : "field-row"}>
            <label className="label" htmlFor={`listing-field-${f.key}`}>{f.label}</label>
            {f.options?.length ? (
              <select
                id={`listing-field-${f.key}`}
                data-listing-field={f.key}
                className="input"
                value={local[f.key] || ""}
                onChange={(e) => commitField(f.key, e.target.value)}
              >
                <option value="">—</option>
                {local[f.key]
                  && !f.options.some((option) => option === local[f.key]) ? (
                  <option value={local[f.key]}>{local[f.key]} (current)</option>
                ) : null}
                {f.options.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            ) : (
              <input
                id={`listing-field-${f.key}`}
                data-listing-field={f.key}
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
    </div>
  );
}

/** Fields for this tab from Vendoo's own schema, or null when it has none. */
function schemaFieldsForTab(
  forms: MarketplaceForm[] | undefined,
  tab: string,
): EditorField[] | null {
  const form = forms?.find((entry) => entry.marketplace === tab);
  if (tab === "general") return null;
  // An unknown leaf still answers with the marketplace's own controls and the
  // values this listing holds, so render whatever rows came back.
  if (!form?.fields.length) return null;
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
        { key: "department", label: "Department" },
        { key: "weight_oz", label: "Package Weight (oz)", type: "number" },
        { key: "package_dimensions_in", label: "Package Dimensions (LxWxH in)" },
      ];
    case "ebay":
      return mergeSpecificsWithDefaults(listing?.ebay_specifics, "ebay_specifics", [
        { key: "ebay_specifics.department", label: "Department" },
        { key: "ebay_specifics.size", label: "Size" },
        { key: "ebay_specifics.sizeType", label: "Size Type" },
        { key: "ebay_specifics.type", label: "Type" },
        { key: "ebay_specifics.pricingFormat", label: "Pricing Format" },
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
        [
          { key: "etsy_specifics.whoMade", label: "Who Made It?" },
          { key: "etsy_specifics.whatIsIt", label: "What Is It?" },
          { key: "etsy_specifics.whenMade", label: "When Was It Made?" },
          ...ETSY_CATEGORY_OPTIONALS.map((field) => ({
            key: `etsy_specifics.category_specifics.${field.key}`,
            label: field.label,
          })),
        ],
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

/** Opens each marketplace's own listing page, alphabetically. */
function MarketplaceLinks({ urls }: { urls?: Record<string, string> }) {
  const entries = Object.entries(urls || {}).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) return null;
  return (
    <span className="pr-marketplace-links">
      {entries.map(([id, url]) => (
        <a
          key={id}
          className="pr-marketplace-link"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open the ${marketplaceName(id)} listing`}
        >
          <MarketplaceLogo id={id} label={`Open the ${marketplaceName(id)} listing`} size={16} />
        </a>
      ))}
    </span>
  );
}

function coerce(val: string): string | number | null {
  if (val === "") return null;
  if (!isNaN(Number(val)) && val.trim() !== "") return Number(val);
  return val;
}

/** Send stays off while generation (or a refine) is still writing the listing. */
export function sendToVendooEnabled(canSend: boolean, generating: boolean, pending = false): boolean {
  return canSend && !generating && !pending;
}

const ACTIVE_SEND_STATUSES = new Set(["queued", "awaiting_extension", "dispatched"]);

/** Prefer a job that is still running over a newer finished one on the same listing. */
export function preferredSendJob<T extends { status?: string | null }>(jobs: T[]): T | undefined {
  return jobs.find((job) => ACTIVE_SEND_STATUSES.has(String(job.status || ""))) ?? jobs[0];
}

/**
 * A second click while this listing's send is already on screen is not another
 * Chrome job. The progress card is the status; the 409 is noise.
 */
export function suppressOwnSendConflict(message: string | null | undefined, ownSendVisible: boolean): string {
  const text = String(message || "").trim();
  if (!text || !ownSendVisible) return text;
  if (/already queued or sending/i.test(text) || /busy with another Vendoo job/i.test(text) || /Chrome is busy with "/i.test(text)) {
    return "";
  }
  return text;
}

function SendToVendooButton({
  convId,
  canSend,
  generating,
  sendBlockers,
  listing,
  listingTitle,
  selectedMarketplaces,
  liveMarketplaces,
  vendooItemId,
  onAskChat,
  onSelectBlocker,
}: {
  convId: string;
  canSend: boolean;
  generating: boolean;
  sendBlockers: { field?: string; message?: string }[];
  listing?: Record<string, unknown>;
  listingTitle?: string;
  selectedMarketplaces?: string[];
  /** Marketplaces already carrying this item, named for the copy under Send. */
  liveMarketplaces?: string[];
  vendooItemId?: string | null;
  onAskChat?: (text: string) => void;
  onSelectBlocker: (field: string) => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = React.useState<string | null>(null);
  const sendLock = React.useRef(false);
  const bound = Boolean(vendooItemId);

  // Vendoo's dropdown lists ride along in the fix prompts, so chat repairs a
  // rejected option (Depop material "Other") with one the dropdown really has.
  const { data: dropdownOptions } = useQuery({
    queryKey: ["catalog-dropdown-options"],
    queryFn: api.catalog.dropdownOptions,
    staleTime: Infinity,
  });

  const { data: extStatus } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: () => pollMs(EXTENSION_STATUS_POLL_MS),
  });

  const { data: jobs } = useQuery({
    queryKey: ["jobs", convId],
    queryFn: () => api.jobs.list(convId),
    refetchInterval: (query) => jobsPollMs(query.state.data),
  });

  const listingJob = jobs?.find((j) => j.conversation_id === convId && j.status !== "cancelled");
  const listingJobId = listingJob?.id;
  const chromeConnected = Boolean(extStatus?.connected);
  const hasDraft = Boolean(vendooItemId || listingJob?.vendoo_item_id || listingJob?.vendoo_url);

  // Same draft + fill-log cache as Fields, so one Ask chat counts the full schema.
  const { data: draft } = useQuery({
    queryKey: vendooItemQueryKey(listingJobId || ""),
    queryFn: ({ signal }) => api.jobs.vendooItem(listingJobId!, { refresh: true, signal }),
    enabled: Boolean(listingJobId && hasDraft && chromeConnected),
    staleTime: VENDOO_ITEM_STALE_MS,
    retry: 1,
  });
  const { data: fillReport } = useQuery({
    queryKey: ["fill-log", listingJobId],
    queryFn: () => api.jobs.fillLog(listingJobId!),
    enabled: Boolean(listingJobId),
    refetchInterval: () => fillLogPollMs(listingJob?.status),
  });
  const { data: hiddenData } = useQuery({
    queryKey: ["settings-hidden-fields", convId],
    queryFn: () => api.settings.hiddenFields(convId),
  });

  const hidden = hiddenData || emptyHiddenFields();
  const { sourceForms, fromVendooDraft } = React.useMemo(
    () => sourceFormsForJob(
      mergeDraftItem(draft),
      fillReport,
      listing,
      selectedMarketplaces,
    ),
    [draft, fillReport, listing, selectedMarketplaces],
  );
  const visibleSourceForms = React.useMemo(
    () => withoutHiddenFields(sourceForms, hidden),
    [sourceForms, hidden],
  );
  const hiddenKeys = React.useMemo(() => hiddenKeySet(hidden), [hidden]);
  const fillFailures = React.useMemo(
    () => (fillReport ? fillFailureEntries(fillReport) : []).filter(
      (entry) => !hiddenKeys.has(
        hiddenFieldKey(entry.marketplace.toLowerCase(), normalizeFieldName(entry.field)),
      ),
    ),
    [fillReport, hiddenKeys],
  );
  const emptyFieldsCount = React.useMemo(
    () => askChatTargetCount(visibleSourceForms, listing, fillFailures, fromVendooDraft),
    [visibleSourceForms, listing, fillFailures, fromVendooDraft],
  );
  const fillEmptyPrompt = React.useMemo(
    () => (emptyFieldsCount
      ? askChatGapsPrompt(
        visibleSourceForms,
        fromVendooDraft,
        listing,
        fillFailures,
        dropdownOptions?.forms,
      )
      : undefined),
    [
      emptyFieldsCount,
      visibleSourceForms,
      fromVendooDraft,
      listing,
      fillFailures,
      dropdownOptions?.forms,
    ],
  );

  const sendMutation = useMutation({
    mutationFn: () => api.jobs.send(convId),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["queue"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      addToast({
        type: "success",
        title: "Added to queue",
        description: "You can move on. The Vendoo draft will be saved in the background.",
      });
    },
    onError: (err: Error) => setError(err.message || "Failed to queue send"),
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

  const existingJob = preferredSendJob(
    (jobs ?? []).filter(
      (j) => j.conversation_id === convId && j.status !== "cancelled" && j.status !== "imported",
    ),
  );
  const isSchemaProbe = existingJob?.mode === "schema_probe";
  const probeActive = Boolean(
    isSchemaProbe && ["queued", "awaiting_extension", "dispatched"].includes(String(existingJob?.status || "")),
  );
  const step = String(existingJob?.current_step || "");
  const apiCreateActive = Boolean(
    existingJob
    && ACTIVE_SEND_STATUSES.has(existingJob.status)
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
  const shownSendError = suppressOwnSendConflict(error, apiCreateActive);
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
  const sendLabel = bound ? "Update Vendoo" : "Send to Vendoo";
  const live = liveMarketplaces || [];
  // Mid-generation Send would ship a half-written listing; otherwise the hint
  // says what Send does — and for a live item, what it deliberately does not.
  const sendEnabled = sendToVendooEnabled(canSend, generating, sendMutation.isPending) && !apiCreateActive && !formFillActive;
  const sendHint = generating
    ? "Wait for generation to finish before sending."
    : !bound
      ? "Creates a Vendoo draft and links it. Nothing is published."
      : live.length
        ? "Writes changed fields onto the Vendoo form. "
          + (live.length > 2
            ? `The live listings on all ${live.length} marketplaces keep`
            : `The live ${joinMarketplaces(live)} ${live.length === 1 ? "listing keeps" : "listings keep"}`)
          + " the old version until you delist and relist in Vendoo. Keeps the photos already in Vendoo."
        : "Writes changed fields onto the linked Vendoo draft. Keeps the photos already in Vendoo. Nothing is published.";

  const startSend = () => {
    if (sendLock.current || sendMutation.isPending) return;
    if (generating) {
      setError("Wait for generation to finish before sending.");
      return;
    }
    if (!canSend) {
      setError(blockerText || "Listing is not ready. Add a title, description, price, and at least one photo.");
      return;
    }
    sendLock.current = true;
    setError(null);
    sendMutation.mutate(undefined, {
      onSettled: () => {
        sendLock.current = false;
      },
    });
  };

  if ((probeActive || apiCreateActive || formFillActive) && existingJob) {
    const stepKey = String(existingJob.current_step || "");
    const label = probeActive
      ? "Discovering fields"
      : apiCreateActive
        ? (bound ? "Updating Vendoo" : "Sending to Vendoo")
        : "Filling fields in the browser";
    const statusText = probeActive
      ? (existingJob.current_step || existingJob.status)
      : apiCreateActive
        ? sendProgressLabel(stepKey, existingJob.send_progress)
        : `${existingJob.status}: ${existingJob.current_step || "queued"}`;
    return (
      <div className="job-card">
        <div className="job-card-header">
          <div className="job-card-copy">
            <div className="job-card-label">{label}</div>
            <div className="job-card-status">
              {apiCreateActive ? (
                <SendProgress label={statusText} startedAt={existingJob.started_at || existingJob.created_at}
                  photos={stepKey === "vendoo_api_photos" ? existingJob.send_progress : undefined} />
              ) : statusText}
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
            prompt={jobErrorPrompt(existingJob.last_error, listingTitle, null, dropdownOptions?.forms)}
            onAskChat={onAskChat}
            emptyFieldsCount={emptyFieldsCount}
            emptyFieldsPrompt={fillEmptyPrompt}
          />
        )}
        {shownSendError && (
          <CopyableLlmError
            className="job-card-detail"
            text={shownSendError}
            prompt={jobErrorPrompt(shownSendError, listingTitle, null, dropdownOptions?.forms)}
            onAskChat={onAskChat}
            emptyFieldsCount={emptyFieldsCount}
            emptyFieldsPrompt={fillEmptyPrompt}
          />
        )}
        {!existingJob.last_error && !shownSendError && (
          // No error to show, but empty fields still deserve their fill button.
          <CopyableLlmError
            className="job-card-detail"
            text=""
            prompt=""
            onAskChat={onAskChat}
            emptyFieldsCount={emptyFieldsCount}
            emptyFieldsPrompt={fillEmptyPrompt}
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
        {!generating && <ListingBlockers issues={uniqueBlockers} onSelect={onSelectBlocker} />}
      </div>
    );
  }

  const displayError = error || (!canSend ? blockerText : "");
  const blockerPrompt = validationErrorsPrompt(
    uniqueBlockers.length ? uniqueBlockers : [{ message: displayError }],
    listingTitle,
    dropdownOptions?.forms,
  );
  // Rendered even without an error so the fill button stays while fields are empty.
  const errorCard = (
    <CopyableLlmError
      className="mt-8"
      text={displayError}
      prompt={uniqueBlockers.length
        ? blockerPrompt
        : jobErrorPrompt(displayError, listingTitle, null, dropdownOptions?.forms)}
      onAskChat={onAskChat}
      emptyFieldsCount={emptyFieldsCount}
      emptyFieldsPrompt={fillEmptyPrompt}
    />
  );

  return (
    <div>
      <button
        type="button"
        className={`${bound ? "btn btn-primary" : "btn btn-success"}${sendMutation.isPending ? " is-busy" : ""}`}
        style={{ width: "100%" }}
        disabled={!sendEnabled}
        aria-busy={sendMutation.isPending}
        title={generating
          ? "Wait for generation to finish before sending"
          : bound
            ? "Write this listing's changed fields onto the Vendoo draft"
            : "Create a Vendoo draft with marketplace fields filled"}
        onClick={startSend}
      >
        {sendMutation.isPending ? (
          <span className="send-btn-busy">
            <span className="send-spinner" aria-hidden="true" />
            {bound ? "Updating…" : "Sending…"}
          </span>
        ) : sendLabel}
      </button>
      {!sendMutation.isPending && <div className="send-hint">{sendHint}</div>}
      {sendMutation.isPending && (
        <SendProgress label={bound ? "Writing marketplace forms to Vendoo…" : "Starting the send…"} />
      )}
      {errorCard}
      {/* Collapsed and below the error card, so opening a group never pushes Fix errors / Ask chat out of view. */}
      {!generating && <ListingBlockers issues={uniqueBlockers} onSelect={onSelectBlocker} />}
    </div>
  );
}
