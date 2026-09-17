import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FillLogReport } from "../api/types";
import {
  fetchVendooItemLive,
  VENDOO_ITEM_STALE_MS,
  vendooItemQueryKey,
} from "../api/vendooItemQuery";
import { addToast } from "../ui/toast";
import { ConnectChromeButton } from "./ConnectChromeButton";
import {
  EMPTY_CELL,
  FILL_FAILURE_STATUSES,
  UNREAD_CELL,
  askChatGapsPrompt,
  emptyFieldsPrompt,
  emptyHiddenFields,
  fieldMatchKey,
  fieldNeedsVendooApply,
  fieldsNeedingListingValues,
  fillFailureEntries,
  filterForms,
  formSyncCounts,
  groupFields,
  hiddenFieldKey,
  hiddenKeySet,
  isProtectedEbayField,
  issueKind,
  issueLabel,
  leftoverEntries,
  leftoverFieldPrompt,
  leftoverGeneratedValue,
  listingFieldEmpty,
  listingTextForField,
  listingValueForField,
  liveStatusClass,
  marketplaceLabel,
  mergeDraftItem,
  normalizeFieldName,
  patchableChangedFields,
  sourceFormsForJob,
  vendooTextForField,
  withoutHiddenFields,
  type DraftField,
  type FormSyncCounts,
  type OpenMenu,
} from "./fillLogForms";

function useVendooDraft(jobId: string, enabled: boolean, liveRefresh = true) {
  return useQuery({
    queryKey: vendooItemQueryKey(jobId),
    // Live hydrate: cache-only reads can overwrite a just-finished Chrome scrape.
    // While Send/verify owns the Vendoo tab, stay on cache so Discovering… cannot race it.
    queryFn: () => api.jobs.vendooItem(jobId, liveRefresh ? { refresh: true } : { cacheOnly: true }),
    enabled,
    staleTime: VENDOO_ITEM_STALE_MS,
    retry: 1,
  });
}
function LiveStatusChip({ status }: { status?: string }) {
  if (!status) return null;
  return (
    <span className={`pr-live-status ${liveStatusClass(status)}`} title={`Vendoo status: ${status}`}>
      {status}
    </span>
  );
}
function FormSyncCountsView({
  counts,
  fromVendooDraft,
}: {
  counts: FormSyncCounts;
  fromVendooDraft: boolean;
}) {
  return (
    <span className="pr-counts">
      {counts.onVendoo > 0 && (
        <span className="pr-add" title={fromVendooDraft ? "Filled on Vendoo" : "Filled in listing JSON"}>
          +{counts.onVendoo}
        </span>
      )}
      {fromVendooDraft && counts.readyToApply > 0 && (
        <span className="pr-ready" title="Listing has a value; Vendoo is still empty">
          ●{counts.readyToApply}
        </span>
      )}
      {counts.notApplicable > 0 && <span className="pr-na">~{counts.notApplicable}</span>}
      {counts.vendooEmpty > 0 && (
        <span className="pr-del" title={fromVendooDraft ? "Empty on Vendoo" : "Empty in listing JSON"}>
          -{counts.vendooEmpty}
        </span>
      )}
    </span>
  );
}

export function FillLogPanel({
  jobId,
  conversationId,
  jobStatus,
  jobStep,
  vendooItemId,
  vendooUrl,
  listing,
  onAskChat,
  onFilled,
  onJobStarted,
}: {
  jobId: string;
  conversationId?: string;
  jobStatus?: string;
  jobStep?: string | null;
  vendooItemId?: string | null;
  vendooUrl?: string | null;
  listing?: Record<string, unknown>;
  onAskChat?: (text: string) => void;
  onFilled?: () => void;
  onJobStarted?: () => void;
}) {
  const queryClient = useQueryClient();
  const report = useFillLog(jobId);
  const { data: extStatus } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: 5000,
  });
  const { data: marketplaceSettings } = useQuery({
    queryKey: ["settings-marketplaces"],
    queryFn: api.settings.marketplaces,
  });
  const hiddenQueryKey = ["settings-hidden-fields", conversationId] as const;
  const { data: hiddenData } = useQuery({
    queryKey: hiddenQueryKey,
    queryFn: () => api.settings.hiddenFields(conversationId),
  });
  const [query, setQuery] = React.useState("");
  const [missingOnly, setMissingOnly] = React.useState(false);
  const [showJson, setShowJson] = React.useState(false);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [openMenu, setOpenMenu] = React.useState<OpenMenu>(null);
  const resolving =
    jobStatus === "dispatched"
    && (jobStep === "resolving_fields" || jobStep === "verifying_draft");
  const filling = jobStatus === "dispatched" && !resolving;
  const hasDraft = Boolean(vendooItemId || vendooUrl);
  const chromeConnected = Boolean(extStatus?.connected);
  const awaitingFill = React.useRef(false);
  const sawFilling = React.useRef(false);
  const fillingRef = React.useRef(filling);
  fillingRef.current = filling;

  const draftQuery = useVendooDraft(jobId, hasDraft, !(resolving || filling));
  const draft = draftQuery.data;
  const [refreshingDraft, setRefreshingDraft] = React.useState(false);
  const { sourceForms, fromVendooDraft } = sourceFormsForJob(
    mergeDraftItem(draft),
    report,
    listing,
    marketplaceSettings?.selected,
  );
  const hidden = hiddenData || emptyHiddenFields();
  const visibleSourceForms = withoutHiddenFields(sourceForms, hidden);
  const hiddenCount = hidden.always.length + hidden.listing.length;
  const sourceKey = visibleSourceForms.map((form) => form.id).join("|");
  const forms = filterForms(visibleSourceForms, query, missingOnly, listing, fromVendooDraft);
  const selectedForm = forms.find((form) => form.id === selected) || forms[0];
  const selectedCounts = selectedForm ? formSyncCounts(selectedForm, listing, fromVendooDraft) : null;

  React.useEffect(() => {
    if (!report) return;
    setValues((prev) => {
      let changed = false;
      const next = { ...prev };
      leftoverEntries(report).forEach((entry) => {
        const generated = leftoverGeneratedValue(listing, entry);
        if (!generated) {
          if (next[entry.id] == null) {
            next[entry.id] = "";
            changed = true;
          }
          return;
        }
        if (!String(next[entry.id] || "").trim()) {
          next[entry.id] = generated;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [report, listing]);

  React.useEffect(() => {
    if (!sourceKey) return;
    const source = sourceKey.split("|");
    setSelected((current) => {
      if (current && source.includes(current)) return current;
      const firstMissing = visibleSourceForms.find((form) => form.missing > 0) || visibleSourceForms[0];
      return firstMissing?.id || null;
    });
  }, [sourceKey]);

  React.useEffect(() => {
    if (!openMenu) return;
    const onPointer = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest(".pr-menu-wrap, .pr-hide-choices, .pr-hide-btn")) return;
      setOpenMenu(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenMenu(null);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [openMenu]);

  const refreshDraftLive = async () => {
    if (!hasDraft) return;
    if (resolving || filling) {
      return;
    }
    setShowJson(false);
    setRefreshingDraft(true);
    try {
      // Always hit Chrome with refresh=true via the shared query so remounts
      // don't replace the live scrape with a server-cache response.
      const fresh = await fetchVendooItemLive(queryClient, jobId, { force: true });
      if (fresh?.error || fresh?.api_error) {
        addToast({
          type: "error",
          title: "Could not fully refresh Vendoo draft",
          description: String(fresh.error || fresh.api_error),
        });
      }
    } catch (error) {
      addToast({ type: "error", title: (error as Error).message || "Could not refresh Vendoo draft" });
    } finally {
      setRefreshingDraft(false);
    }
  };

  const rereadDraft = () => {
    awaitingFill.current = false;
    sawFilling.current = false;
    queryClient.invalidateQueries({ queryKey: ["fill-log", jobId] });
    queryClient.invalidateQueries({ queryKey: ["listing"] });
    if (hasDraft) void refreshDraftLive();
    onFilled?.();
  };

  const fillMutation = useMutation({
    mutationFn: (fields: { id?: string; marketplace?: string; field?: string; value?: string }[]) =>
      api.jobs.fillFields(jobId, fields),
    onSuccess: () => {
      awaitingFill.current = true;
      sawFilling.current = fillingRef.current;
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["fill-log", jobId] });
      queryClient.invalidateQueries({ queryKey: ["listing"] });
      onFilled?.();
      onJobStarted?.();
      window.setTimeout(() => {
        if (awaitingFill.current && !sawFilling.current && !fillingRef.current) rereadDraft();
      }, 8000);
    },
  });
  const busy = fillMutation.isPending || filling || resolving;

  const hideMutation = useMutation({
    mutationFn: (body: {
      marketplace: string;
      field: string;
      label?: string;
      scope: "always" | "listing";
      conversation_id?: string;
    }) => api.settings.hideField(body),
    onSuccess: (payload, body) => {
      queryClient.setQueryData(hiddenQueryKey, { always: payload.always, listing: payload.listing });
      setOpenMenu(null);
      addToast({
        type: "success",
        title: body.scope === "always" ? "Hidden on every listing" : "Hidden on this listing",
      });
    },
    onError: (error) => {
      addToast({ type: "error", title: (error as Error).message || "Could not hide field" });
    },
  });

  const showMutation = useMutation({
    mutationFn: (body: {
      marketplace: string;
      field: string;
      scope: "always" | "listing";
      conversation_id?: string;
    }) => api.settings.showField(body),
    onSuccess: (payload) => {
      queryClient.setQueryData(hiddenQueryKey, { always: payload.always, listing: payload.listing });
      if (payload.always.length + payload.listing.length === 0) setOpenMenu(null);
    },
    onError: (error) => {
      addToast({ type: "error", title: (error as Error).message || "Could not show field" });
    },
  });

  const restoreAllMutation = useMutation({
    mutationFn: () => api.settings.restoreAllHiddenFields(conversationId),
    onSuccess: (payload) => {
      queryClient.setQueryData(hiddenQueryKey, { always: payload.always, listing: payload.listing });
      setOpenMenu(null);
      addToast({ type: "success", title: "Restored all hidden fields" });
    },
    onError: (error) => {
      addToast({ type: "error", title: (error as Error).message || "Could not restore fields" });
    },
  });

  const resolveCategory = useMutation({
    mutationFn: () => api.jobs.resolveCategory(jobId, String(listing?.category_path || "")),
    onSuccess: (result) => {
      addToast({
        type: "success",
        title: "Matched Vendoo category",
        description: result.path || "Saved the picker category onto this listing.",
      });
      queryClient.invalidateQueries({ queryKey: ["listing"] });
      queryClient.invalidateQueries({ queryKey: ["conversation"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: vendooItemQueryKey(jobId) });
      onFilled?.();
    },
    onError: (err: Error) => {
      addToast({ type: "error", title: "Could not match category", description: err.message });
    },
  });

  React.useEffect(() => {
    if (!awaitingFill.current) return;
    if (filling) {
      sawFilling.current = true;
      return;
    }
    if (sawFilling.current) rereadDraft();
  }, [filling]);

  const prevJobStatus = React.useRef(jobStatus);
  React.useEffect(() => {
    const prev = prevJobStatus.current;
    prevJobStatus.current = jobStatus;
    if (!hasDraft || !chromeConnected) return;
    if (jobStatus !== "completed" || prev === "completed" || prev == null) return;
    // Leftover-fill completion already triggers rereadDraft above.
    if (awaitingFill.current) return;
    rereadDraft();
  }, [jobStatus, hasDraft, chromeConnected, onAskChat]);

  const hiddenKeys = hiddenKeySet(hidden);
  const askChatFields = fieldsNeedingListingValues(visibleSourceForms, listing).filter(
    ({ form, field }) => !hiddenKeys.has(hiddenFieldKey(form.id, fieldMatchKey(field))),
  );
  const fillFailures = (report ? fillFailureEntries(report) : []).filter(
    (entry) => !hiddenKeys.has(hiddenFieldKey(entry.marketplace.toLowerCase(), normalizeFieldName(entry.field))),
  );
  const askChatTargets = (() => {
    const seen = new Set<string>();
    let count = 0;
    for (const entry of fillFailures) {
      const key = `${entry.marketplace.toLowerCase()}:${normalizeFieldName(entry.field)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      count += 1;
    }
    for (const { form, field } of askChatFields) {
      const key = `${form.id}:${fieldMatchKey(field)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      count += 1;
    }
    return count;
  })();
  // With a live draft read, Apply is only empty or mismatched fields. Matching
  // controls stay untouched so retries do not re-walk every marketplace form.
  const fillPayload = fromVendooDraft
    ? patchableChangedFields(visibleSourceForms, listing, values)
    : (() => {
        const payload: { id?: string; marketplace: string; field: string; value: string }[] = [];
        const seen = new Set<string>();
        for (const entry of report ? leftoverEntries(report) : []) {
          const key = `${entry.marketplace.toLowerCase()}:${entry.field.toLowerCase()}`;
          if (seen.has(key)) continue;
          const typed = String(values[entry.id] || "").trim();
          const value = typed || listingValueForField(listing, entry.marketplace, {
            key: entry.field,
            label: entry.field,
            value: "",
            missing: true,
          });
          if (!value) continue;
          seen.add(key);
          payload.push({ id: entry.id, marketplace: entry.marketplace, field: entry.field, value });
        }
        return payload;
      })();

  const hideField = (formId: string, field: DraftField, scope: "always" | "listing") => {
    if (scope === "listing" && !conversationId) return;
    if (isProtectedEbayField(formId, field)) {
      addToast({
        type: "error",
        title: "Keep this field visible",
        description: `${field.label} is required for eBay category specifics to load on Vendoo.`,
      });
      setOpenMenu(null);
      return;
    }
    hideMutation.mutate({
      marketplace: formId,
      field: fieldMatchKey(field),
      label: field.label,
      scope,
      conversation_id: conversationId,
    });
  };

  return (
    <div className="fill-log-pr">
      <div className="pr-toolbar">
        <label className="pr-search">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search fields..."
            aria-label="Search marketplace fields"
          />
        </label>
        <button
          type="button"
          className={`pr-icon-btn${missingOnly ? " is-on" : ""}`}
          title={missingOnly
            ? "Show all fields"
            : fromVendooDraft
              ? "Show empty-on-Vendoo fields only"
              : "Show empty-in-listing fields only"}
          aria-pressed={missingOnly}
          aria-label={missingOnly
            ? (fromVendooDraft ? "Showing empty-on-Vendoo fields only" : "Showing empty-in-listing fields only")
            : "Showing all fields"}
          onClick={() => setMissingOnly((value) => !value)}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M2 3h12L9.5 8.5V13l-3 1.5V8.5L2 3z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
          </svg>
        </button>
        {hiddenCount > 0 && (
          <div className="pr-menu-wrap">
            <button
              type="button"
              className={`pr-icon-btn pr-read${openMenu?.kind === "hidden" ? " is-on" : ""}`}
              title="Show hidden fields"
              aria-haspopup="menu"
              aria-expanded={openMenu?.kind === "hidden"}
              onClick={() => setOpenMenu((current) => (current?.kind === "hidden" ? null : { kind: "hidden" }))}
            >
              {hiddenCount} hidden
            </button>
            {openMenu?.kind === "hidden" && (
              <div className="pr-menu pr-menu-wide" role="menu">
                <button
                  type="button"
                  className="pr-menu-item-action"
                  style={{ width: "100%", marginBottom: 8 }}
                  disabled={restoreAllMutation.isPending}
                  onClick={() => restoreAllMutation.mutate()}
                >
                  {restoreAllMutation.isPending ? "Restoring…" : "Show all"}
                </button>
                {[
                  ...hidden.always.map((item) => ({ ...item, scope: "always" as const })),
                  ...hidden.listing.map((item) => ({ ...item, scope: "listing" as const })),
                ].map((item) => (
                  <div key={`${item.scope}:${item.marketplace}:${item.field}`} className="pr-hidden-row">
                    <div className="pr-hidden-copy">
                      <span className="pr-hidden-name">{item.label || item.field}</span>
                      <span className="pr-hidden-meta">
                        {marketplaceLabel(item.marketplace)} · {item.scope === "always" ? "Always" : "This listing"}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="pr-menu-item-action"
                      disabled={showMutation.isPending || (item.scope === "listing" && !conversationId)}
                      onClick={() =>
                        showMutation.mutate({
                          marketplace: item.marketplace,
                          field: item.field,
                          scope: item.scope,
                          conversation_id: conversationId,
                        })
                      }
                    >
                      Show
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {hasDraft && (
          <button
            type="button"
            className="pr-icon-btn pr-read"
            disabled={draftQuery.isFetching || refreshingDraft}
            onClick={() => {
              void refreshDraftLive();
            }}
            title={chromeConnected ? "Re-read the live Vendoo form" : "Connect Chrome to refresh from Vendoo"}
          >
            {draftQuery.isFetching || refreshingDraft ? "Discovering…" : draft ? "Refresh" : "Read draft"}
          </button>
        )}
        {draft?.ok && (
          <button type="button" className="pr-icon-btn pr-read" onClick={() => setShowJson((value) => !value)}>
            {showJson ? "Hide JSON" : "JSON"}
          </button>
        )}
      </div>

      {draftQuery.isFetching && (
        <p className="pr-notice">
          Opening each marketplace form and expanding optional fields so Studio can list every empty field…
        </p>
      )}

      {hasDraft && !fromVendooDraft && !draftQuery.isFetching && (
        <p className="pr-notice">
          {chromeConnected
            ? "Read the Vendoo draft to compare listing JSON against the live form."
            : "Connect Chrome, then read the Vendoo draft to compare listing JSON against the live form."}
        </p>
      )}

      {draftQuery.error && (
        <div className="text-xs text-error">{(draftQuery.error as Error).message || "Could not read the Vendoo draft"}</div>
      )}
      {draft?.api_error && <div className="pr-meta">API: {draft.api_error}</div>}

      {!sourceForms.length ? (
        <div className="pr-empty">
          <p>
            {draftQuery.isFetching
              ? "Discovering every marketplace form and optional field…"
              : !chromeConnected && hasDraft
                ? "Connect Chrome to read Vendoo fields. Ask chat can still write values, then Apply types only empty or changed fields."
                : hasDraft
                  ? "Read the Vendoo draft to compare listing JSON against each marketplace form."
                  : "Send this listing to Vendoo to review each marketplace form. After generate, Studio also discovers live Vendoo fields once the category is known."}
          </p>
          {!chromeConnected && hasDraft && <ConnectChromeButton />}
        </div>
      ) : !forms.length ? (
        <div className="pr-empty">
          <p>
            {!visibleSourceForms.length
              ? "Every field is hidden. Restore hidden fields to see them here."
              : missingOnly
                ? "No missing fields match this filter."
                : "No fields match this search."}
          </p>
        </div>
      ) : (
        <div className="pr-split">
          <div className="pr-files">
            <div className="pr-files-head">
              <span>Forms</span>
              <span className="pr-files-count">{forms.length}</span>
            </div>
            <div className="pr-tree" role="list">
              {forms.map((form) => {
                const counts = formSyncCounts(form, listing, fromVendooDraft);
                return (
                <button
                  key={form.id}
                  type="button"
                  className={`pr-row${selectedForm?.id === form.id ? " is-active" : ""}`}
                  onClick={() => setSelected(form.id)}
                >
                  <span className="pr-name">{form.label}</span>
                  <LiveStatusChip status={form.liveStatus} />
                  <FormSyncCountsView counts={counts} fromVendooDraft={fromVendooDraft} />
                </button>
                );
              })}
            </div>
          </div>
          {selectedForm && (
            <div className="pr-diff">
              <div className="pr-diff-head">
                <span className="pr-diff-path">{selectedForm.label}</span>
                <LiveStatusChip status={selectedForm.liveStatus} />
                {selectedCounts && (
                  <FormSyncCountsView counts={selectedCounts} fromVendooDraft={fromVendooDraft} />
                )}
              </div>
              <div className="pr-diff-body">
                {!selectedForm.fields.length ? (
                  <div className="pr-empty">
                    <p>
                      {selectedForm.liveStatus
                        ? `Vendoo status: ${selectedForm.liveStatus}. Studio doesn’t fill this marketplace yet.`
                        : "No fields to show for this marketplace."}
                    </p>
                  </div>
                ) : (
                  groupFields(selectedForm.fields).map((group) => (
                  <div key={group.label || "fields"} className="pr-section-block">
                    {group.label ? <div className="pr-section">{group.label}</div> : null}
                    <div className="pr-field-table-head" aria-hidden="true">
                      <span className="pr-field-table-gap" />
                      <span>Field</span>
                      <span>Listing</span>
                      <span>Vendoo</span>
                      <span />
                    </div>
                    {group.fields.map((field) => {
                      const leftover = field.leftover;
                      const menuKey = `${selectedForm.id}:${field.key}`;
                      const menuOpen = openMenu?.kind === "field" && openMenu.key === menuKey;
                      const canHide = !isProtectedEbayField(selectedForm.id, field);
                      const listingText = listingTextForField(listing, selectedForm.id, field);
                      const listingEmpty = listingFieldEmpty(listing, selectedForm.id, field);
                      const vendooText = vendooTextForField(field);
                      const applyValue = listingText || (leftover
                        ? (String(values[leftover.id] ?? "").trim() || leftoverGeneratedValue(listing, leftover, field))
                        : "");
                      const rowClass = field.notApplicable
                        ? "is-na"
                        : !fromVendooDraft
                          ? "is-unknown"
                          : field.missing
                            ? "is-del"
                            : "is-add";
                      const gutter = field.notApplicable ? "~" : !fromVendooDraft ? "?" : field.missing ? "-" : "+";
                      const listingCell = field.notApplicable
                        ? "Does not apply"
                        : (listingText || EMPTY_CELL);
                      const vendooCell = !fromVendooDraft
                        ? UNREAD_CELL
                        : (vendooText || EMPTY_CELL);
                      return (
                        <div key={field.key} className={`pr-field-row ${rowClass}`}>
                          <span className="pr-field-gutter">{gutter}</span>
                          <span className="pr-field-name">{field.label}</span>
                          <span className={`pr-field-cell${listingEmpty && !field.notApplicable ? " is-empty" : " is-filled"}`}>
                            {listingCell}
                          </span>
                          <span className={`pr-field-cell${
                            !fromVendooDraft
                              ? " is-unknown"
                              : field.missing && !field.notApplicable
                                ? " is-empty"
                                : " is-filled"
                          }`}>
                            {vendooCell}
                          </span>
                          <div className="pr-field-row-actions">
                            {leftover && !field.notApplicable && (
                              <span className={`pr-issue-badge is-${issueKind(leftover)}`} title={leftover.reason || issueLabel(leftover)}>
                                {issueLabel(leftover)}
                              </span>
                            )}
                            {onAskChat && !field.notApplicable && (
                              listingEmpty
                              || (leftover && FILL_FAILURE_STATUSES.has(leftover.status))
                            ) && (
                              <button
                                type="button"
                                className="pr-read"
                                disabled={busy}
                                onClick={() => onAskChat(leftover && FILL_FAILURE_STATUSES.has(leftover.status)
                                  ? leftoverFieldPrompt(listing, leftover, applyValue || vendooText)
                                  : emptyFieldsPrompt([{ ...selectedForm, fields: [field] }], fromVendooDraft, listing))}
                              >
                                Ask chat
                              </button>
                            )}
                            {!field.notApplicable && applyValue && fromVendooDraft && fieldNeedsVendooApply(field, applyValue) && chromeConnected && (
                              <button
                                type="button"
                                className="pr-read"
                                disabled={busy}
                                onClick={() => fillMutation.mutate([{
                                  id: leftover?.id,
                                  marketplace: selectedForm.id,
                                  field: leftover?.field || field.label,
                                  value: applyValue,
                                }])}
                              >
                                Apply
                              </button>
                            )}
                            {menuOpen && canHide && (
                              <div className="pr-hide-choices">
                                <button
                                  type="button"
                                  disabled={!conversationId || hideMutation.isPending}
                                  onClick={() => hideField(selectedForm.id, field, "listing")}
                                >
                                  This listing
                                </button>
                                <button
                                  type="button"
                                  disabled={hideMutation.isPending}
                                  onClick={() => hideField(selectedForm.id, field, "always")}
                                >
                                  Always
                                </button>
                              </div>
                            )}
                            {canHide && (
                              <button
                                type="button"
                                className="pr-hide-btn"
                                aria-label={menuOpen ? `Cancel hiding ${field.label}` : `Hide ${field.label}`}
                                aria-expanded={menuOpen}
                                title="Hide this field"
                                onClick={() => setOpenMenu(menuOpen ? null : { kind: "field", key: menuKey })}
                              >
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                                  <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                                </svg>
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ))
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {(onAskChat || hasDraft) && (
        <div className="pr-actions">
          <p className="pr-notice">
            Ask chat only for fields generation could not resolve. After generate, Studio fills discovered listing values and applies them on Vendoo when Chrome is connected. Nothing is published.
          </p>
          {hasDraft && (
            <div className="pr-action">
              <button
                type="button"
                className="btn btn-sm"
                disabled={resolveCategory.isPending || busy || !chromeConnected}
                title={!chromeConnected ? "Connect Chrome to search the Vendoo category picker" : "Search the live Vendoo category picker and save the match"}
                onClick={() => resolveCategory.mutate()}
              >
                {resolveCategory.isPending ? "Setting category…" : "Set Vendoo category"}
              </button>
              <p className="pr-action-hint">Picks the matching category in Vendoo. Start here if the category is wrong.</p>
            </div>
          )}
          {onAskChat && (
            <div className="pr-action">
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy || askChatTargets === 0}
                title="Send empty listing fields and Apply/Send failures to chat. Does not change Vendoo yet."
                onClick={() => onAskChat(askChatGapsPrompt(
                  visibleSourceForms,
                  fromVendooDraft,
                  listing,
                  fillFailures,
                ))}
              >
                {askChatTargets
                  ? `Ask chat for ${askChatTargets} field${askChatTargets === 1 ? "" : "s"}`
                  : "Ask chat for fields"}
              </button>
              <p className="pr-action-hint">
                Empty listing values and failed Apply/Send fields — writes listing JSON only, not Vendoo.
              </p>
            </div>
          )}
          <div className="pr-action">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy || fillPayload.length === 0 || !chromeConnected}
              title={
                !chromeConnected
                  ? "Connect Chrome to type these values into the Vendoo draft"
                  : resolving
                    ? "Wait for field repair to finish before applying"
                  : fillPayload.length
                    ? "Type listing values into empty Vendoo draft fields"
                    : "Ask chat to write listing values first"
              }
              onClick={() => fillMutation.mutate(fillPayload)}
            >
              {fillMutation.isPending || filling
                ? "Applying on Vendoo…"
                : resolving
                  ? (jobStep === "verifying_draft" ? "Checking draft…" : "Resolving fields…")
                : fillPayload.length
                  ? `Apply ${fillPayload.length} value${fillPayload.length === 1 ? "" : "s"} on Vendoo`
                  : "Apply values on Vendoo"}
            </button>
            <p className="pr-action-hint">
              {!chromeConnected
                ? "Connect Chrome to type listing values into the Vendoo draft."
                : resolving
                  ? "Waiting on the listing assistant to resolve saved-draft gaps. Does not publish."
                : fillPayload.length
                  ? "Listing has these values; Vendoo draft fields are still empty."
                  : "Ask chat to write listing values first, then apply them here."}
            </p>
          </div>
        </div>
      )}

      {fillPayload.length > 0 && !busy && (
        <p className="pr-notice">
          {fillPayload.length} listing value{fillPayload.length === 1 ? "" : "s"} ready for Vendoo.
          Review the Listing and Vendoo columns above, then click Apply on Vendoo.
        </p>
      )}

      {fillMutation.error && (
        <div className="text-xs text-error">{(fillMutation.error as Error).message || "Failed to apply values on Vendoo"}</div>
      )}

      {showJson && draft?.ok && (
        <pre className="fill-log-vendoo-json">
          {JSON.stringify({ source: draft.source, item_id: draft.item_id, url: draft.url, item: draft.item, form: draft.form }, null, 2)}
        </pre>
      )}
    </div>
  );
}

function useFillLog(jobId: string): FillLogReport | undefined {
  const { data } = useQuery({
    queryKey: ["fill-log", jobId],
    queryFn: () => api.jobs.fillLog(jobId),
    enabled: Boolean(jobId),
    refetchInterval: 2000,
  });
  return data;
}
