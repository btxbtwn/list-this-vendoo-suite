import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FillLogReport } from "../api/types";
import {
  VENDOO_ITEM_STALE_MS,
  vendooItemQueryKey,
} from "../api/vendooItemQuery";
import { addToast } from "../ui/toast";
import { ConnectChromeButton } from "./ConnectChromeButton";
import {
  EMPTY_CELL,
  FILL_FAILURE_STATUSES,
  UNREAD_CELL,
  emptyFieldsPrompt,
  emptyHiddenFields,
  fieldMatchKey,
  filterForms,
  formSyncCounts,
  groupFields,
  isProtectedEbayField,
  issueKind,
  issueLabel,
  leftoverEntries,
  leftoverFieldPrompt,
  leftoverGeneratedValue,
  listingFieldEmpty,
  listingTextForField,
  liveStatusClass,
  marketplaceLabel,
  mergeDraftItem,
  sourceFormsForJob,
  vendooTextForField,
  withoutHiddenFields,
  type DraftField,
  type FormSyncCounts,
  type OpenMenu,
} from "./fillLogForms";

function useVendooDraft(jobId: string, enabled: boolean) {
  return useQuery({
    queryKey: vendooItemQueryKey(jobId),
    // Tab-free API read of the saved item (session via Chrome; no Vendoo tab).
    queryFn: () => api.jobs.vendooItem(jobId, { refresh: true }),
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
  vendooItemId,
  vendooUrl,
  listing,
  onAskChat,
  onFilled,
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
  // Ask-chat prompts carry each field's real dropdown list, not just its name.
  const { data: dropdownOptions } = useQuery({
    queryKey: ["catalog-dropdown-options"],
    queryFn: api.catalog.dropdownOptions,
    staleTime: Infinity,
  });
  const { data: schemaForms } = useQuery({
    queryKey: ["listing-fields", conversationId],
    queryFn: () => api.vendooApi.listingFields(conversationId || ""),
    enabled: Boolean(conversationId),
    staleTime: 60_000,
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
  const hasDraft = Boolean(vendooItemId || vendooUrl);
  const chromeConnected = Boolean(extStatus?.connected);

  const draftQuery = useVendooDraft(jobId, hasDraft && chromeConnected);
  const draft = draftQuery.data;
  const { sourceForms, fromVendooDraft } = sourceFormsForJob(
    mergeDraftItem(draft),
    report,
    listing,
    marketplaceSettings?.selected,
    schemaForms?.forms,
  );
  const hidden = hiddenData || emptyHiddenFields();
  const visibleSourceForms = withoutHiddenFields(sourceForms, hidden);
  const hiddenCount = hidden.always.length + hidden.listing.length;
  const sourceKey = visibleSourceForms.map((form) => form.id).join("|");
  const forms = filterForms(visibleSourceForms, query, missingOnly, listing);
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

  const prevJobStatus = React.useRef(jobStatus);
  React.useEffect(() => {
    const prev = prevJobStatus.current;
    prevJobStatus.current = jobStatus;
    if (!hasDraft || !chromeConnected) return;
    if (jobStatus !== "completed" || prev === "completed" || prev == null) return;
    queryClient.invalidateQueries({ queryKey: vendooItemQueryKey(jobId) });
    queryClient.invalidateQueries({ queryKey: ["fill-log", jobId] });
    onFilled?.();
  }, [jobStatus, hasDraft, chromeConnected, jobId, queryClient, onFilled]);

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
            : "Show empty-in-listing fields only"}
          aria-pressed={missingOnly}
          aria-label={missingOnly
            ? "Showing empty-in-listing fields only"
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
        {draft?.ok && (
          <button type="button" className="pr-icon-btn pr-read" onClick={() => setShowJson((value) => !value)}>
            {showJson ? "Hide JSON" : "JSON"}
          </button>
        )}
      </div>

      {draftQuery.isFetching && (
        <p className="pr-notice">Reading the Vendoo draft…</p>
      )}

      {hasDraft && !fromVendooDraft && !draftQuery.isFetching && (
        <p className="pr-notice">
          {chromeConnected
            ? "Waiting for the Vendoo draft to load."
            : "Connect Chrome to compare listing JSON against the Vendoo draft."}
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
              ? "Reading the Vendoo draft…"
              : !chromeConnected && hasDraft
                ? "Connect Chrome to read Vendoo fields. Ask chat can still write listing values."
                : hasDraft
                  ? "Could not load marketplace fields from this Vendoo draft yet."
                  : "Send this listing to Vendoo to review each marketplace form."}
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
                              (listingEmpty && (!fromVendooDraft || field.missing))
                              || (leftover && FILL_FAILURE_STATUSES.has(leftover.status))
                            ) && (
                              <button
                                type="button"
                                className="pr-read"
                                onClick={() => onAskChat(leftover && FILL_FAILURE_STATUSES.has(leftover.status)
                                  ? leftoverFieldPrompt(listing, leftover, applyValue || vendooText, dropdownOptions?.forms)
                                  : emptyFieldsPrompt(
                                    [{ ...selectedForm, fields: [field] }],
                                    fromVendooDraft,
                                    listing,
                                    dropdownOptions?.forms,
                                  ))}
                              >
                                Ask chat
                              </button>
                            )}
                            {menuOpen && canHide && (
                              <div className="pr-hide-choices">
                                <button
                                  type="button"
                                  disabled={!conversationId || hideMutation.isPending}
                                  onClick={() => hideField(selectedForm.id, field, "listing")}
                                  title="Hide on this listing only — drops it from Fields and Ask chat"
                                >
                                  This listing
                                </button>
                                <button
                                  type="button"
                                  disabled={hideMutation.isPending}
                                  onClick={() => hideField(selectedForm.id, field, "always")}
                                  title="Hide on every listing — drops it from Fields and Ask chat"
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
                                title="Hide from Fields and Ask chat"
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
